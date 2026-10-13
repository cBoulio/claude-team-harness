import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
TEMPLATE_HOOKS = REPO / "template" / ".claude" / "hooks"


def fake_secret(prefix: str, length: int = 36) -> str:
    """Build a credential-shaped string at runtime so no literal token sits in the repo."""
    return prefix + ("aB3" * length)[:length]


def run_script(script: Path, args=(), stdin=None, root: Path | None = None, cwd: Path | None = None):
    env = {k: v for k, v in os.environ.items() if k != "CLAUDE_PROJECT_DIR"}
    if root is not None:
        env["CLAUDE_PROJECT_DIR"] = str(root)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    if isinstance(stdin, (dict, list)):
        stdin = json.dumps(stdin)
    return subprocess.run([sys.executable, str(script), *args], input=stdin, capture_output=True,
                          text=True, encoding="utf-8", env=env, cwd=cwd or root or REPO, timeout=60)


@pytest.fixture
def workspace(tmp_path) -> Path:
    """A fresh workspace created by scripts/init.py (no git)."""
    target = tmp_path / "ws"
    result = run_script(REPO / "scripts" / "init.py", [str(target), "--name", "Test Workspace",
                                                       "--python", "python", "--no-git"])
    assert result.returncode == 0, result.stderr
    return target


@pytest.fixture
def hook(workspace):
    """Run a hook from the workspace copy with CLAUDE_PROJECT_DIR set to the workspace."""
    def _run(name: str, payload=None, args=()):
        return run_script(workspace / ".claude" / "hooks" / name, args, stdin=payload, root=workspace)
    return _run


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))
