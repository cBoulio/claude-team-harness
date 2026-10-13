import json
import shutil
import subprocess

import pytest

from conftest import REPO, load, run_script

INIT = REPO / "scripts" / "init.py"
HAS_GIT = shutil.which("git") is not None


def git(*args, cwd):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True).stdout


def test_init_produces_working_workspace(workspace):
    expected = [
        "CLAUDE.md", ".gitignore", "apps/REGISTRY.md", "research/docs/.gitkeep",
        ".claude/settings.json", ".claude/workspace.json", "scripts/add-app.py",
        ".claude/hooks/_store.py", ".claude/hooks/_markdown.py", ".claude/hooks/log_event.py",
        ".claude/hooks/log_issue.py", ".claude/hooks/render_research.py",
        ".claude/hooks/guard_commands.py", ".claude/hooks/protect_files.py",
        ".claude/agents/app-explorer.md", ".claude/agents/code-reviewer.md", ".claude/agents/debugger.md",
        ".claude/agents/test-runner.md", ".claude/agents/researcher.md",
        ".claude/skills/onboard-app/SKILL.md", ".claude/skills/app-status/SKILL.md",
    ]
    for rel in expected:
        assert (workspace / rel).is_file(), rel
    assert not (workspace / "_gitignore").exists()
    assert not list(workspace.rglob("__pycache__"))

    for path in workspace.rglob("*"):
        if path.is_file():
            assert "{{" not in path.read_text(encoding="utf-8"), f"unfilled placeholder in {path}"

    assert (workspace / "CLAUDE.md").read_text(encoding="utf-8").startswith("# Test Workspace\n")
    assert load(workspace / ".claude" / "workspace.json")["name"] == "Test Workspace"

    settings = load(workspace / ".claude" / "settings.json")
    events = set(settings["hooks"])
    assert {"PreToolUse", "PostToolUse", "PostToolUseFailure", "SessionStart", "SessionEnd",
            "Stop", "StopFailure", "SubagentStop", "UserPromptSubmit", "PreCompact"} <= events
    commands = [h["command"] for groups in settings["hooks"].values() for g in groups for h in g["hooks"]]
    for command in commands:
        script = command.split("/.claude/hooks/")[1].rstrip('"')
        assert (workspace / ".claude" / "hooks" / script).is_file(), script

    # The hooks run from the new workspace.
    event = {"session_id": "abc", "hook_event_name": "SessionStart", "source": "startup"}
    result = run_script(workspace / ".claude" / "hooks" / "log_event.py", stdin=event, root=workspace)
    assert result.returncode == 0
    assert "abc" in load(workspace / "sessions.json")["sessions"]


def test_gitignore_hides_logs_and_apps(tmp_path):
    if not HAS_GIT:
        pytest.skip("git not installed")
    target = tmp_path / "ws"
    assert run_script(INIT, [str(target), "--python", "python"]).returncode == 0
    assert (target / ".git").is_dir()
    for rel in ("errors.json", "sessions.json", "registry.json", ".claude/settings.local.json",
                ".claude/hooks/hook-errors.log", "apps/example-api/app.js", "research/site/index.html", ".env"):
        p = target / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("{}", encoding="utf-8")
    status = git("status", "--porcelain", "--untracked-files=all", cwd=target)
    for rel in ("errors.json", "sessions.json", "registry.json", "settings.local.json", "hook-errors.log",
                "example-api", "research/site", ".env"):
        assert rel not in status, rel
    for rel in ("CLAUDE.md", "apps/REGISTRY.md", ".claude/settings.json", ".claude/hooks/log_event.py"):
        assert rel in status, rel


def test_init_refuses_non_empty_target(tmp_path):
    target = tmp_path / "ws"
    target.mkdir()
    (target / "keep.txt").write_text("x", encoding="utf-8")
    result = run_script(INIT, [str(target), "--no-git"])
    assert result.returncode == 1 and "not empty" in result.stderr


def test_init_rejects_unsafe_python_command(tmp_path):
    result = run_script(INIT, [str(tmp_path / "ws"), "--python", "python; rm -rf ~", "--no-git"])
    assert result.returncode == 1


def test_init_default_name_and_python3(tmp_path):
    target = tmp_path / "acme-platform"
    assert run_script(INIT, [str(target), "--python", "python3", "--no-git"]).returncode == 0
    assert (target / "CLAUDE.md").read_text(encoding="utf-8").startswith("# Acme Platform\n")
    assert "python3 \\\"$CLAUDE_PROJECT_DIR" in (target / ".claude" / "settings.json").read_text(encoding="utf-8")


@pytest.mark.skipif(not HAS_GIT, reason="git not installed")
def test_add_app_new_and_clone(workspace, tmp_path):
    add_app = workspace / "scripts" / "add-app.py"
    created = run_script(add_app, ["example-api", "--new", "--stack", "Node.js", "--purpose", "Public API"],
                         cwd=workspace)
    assert created.returncode == 0, created.stderr
    app = workspace / "apps" / "example-api"
    assert (app / ".git").is_dir() and (app / "CLAUDE.md").is_file()
    registry = (workspace / "apps" / "REGISTRY.md").read_text(encoding="utf-8")
    assert "_none yet_" not in registry
    assert "| Example Api | `apps/example-api` | Node.js | Public API | active |" in registry

    # Clone from a local repo standing in for a remote.
    upstream = tmp_path / "upstream"
    upstream.mkdir()
    git("init", "-b", "main", cwd=upstream)
    (upstream / "README.md").write_text("worker\n", encoding="utf-8")
    git("add", ".", cwd=upstream)
    git("-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "-m", "init", cwd=upstream)
    cloned = run_script(add_app, ["example-worker", "--repo", str(upstream), "--stack", "Python | Celery",
                                  "--purpose", "Background jobs", "--workspace", str(workspace)], cwd=tmp_path)
    assert cloned.returncode == 0, cloned.stderr
    assert (workspace / "apps" / "example-worker" / "README.md").is_file()
    registry = (workspace / "apps" / "REGISTRY.md").read_text(encoding="utf-8")
    assert "Python \\| Celery" in registry
    assert registry.count("\n") == 4  # header, separator, two rows

    again = run_script(add_app, ["example-api", "--new"], cwd=workspace)
    assert again.returncode == 1 and "already exists" in again.stderr
    bad = run_script(add_app, ["Bad Name", "--new"], cwd=workspace)
    assert bad.returncode == 1


def test_add_app_outside_workspace(tmp_path):
    result = run_script(REPO / "scripts" / "add-app.py", ["x", "--new"], cwd=tmp_path)
    assert result.returncode == 1 and "REGISTRY.md" in result.stderr


def test_template_settings_is_valid_json():
    json.loads((REPO / "template" / ".claude" / "settings.json").read_text(encoding="utf-8"))
