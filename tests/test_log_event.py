import json
import sys

from conftest import REPO, TEMPLATE_HOOKS, fake_secret, load


def test_sample_logs_match_schema():
    """The synthetic samples in examples/logs carry every key the hooks write."""
    sys.path.insert(0, str(TEMPLATE_HOOKS))
    try:
        import log_event
    finally:
        sys.path.pop(0)
    samples = REPO / "examples" / "logs"
    for name, default in [("sessions.json", log_event.sessions_default()),
                          ("registry.json", log_event.registry_default()),
                          ("errors.json", log_event.errors_default())]:
        data = load(samples / name)
        assert set(default) <= set(data), name
        assert data["schema_version"] == log_event.SCHEMA_VERSION
    record_keys = {"session_id", "status", "title", "started_at", "ended_at", "duration_minutes",
                   "tokens", "transcript", "apps", "subagents", "tools", "models", "prompts"}
    for s in load(samples / "sessions.json")["sessions"].values():
        assert record_keys <= set(s)


def base(event: str, **extra) -> dict:
    return {"session_id": "s-1", "hook_event_name": event, "cwd": "/tmp/ws",
            "permission_mode": "default", "transcript_path": None, **extra}


def test_session_lifecycle_and_tool_counts(workspace, hook):
    transcript = workspace / "t.jsonl"
    lines = [
        {"type": "user", "version": "2.9.0", "entrypoint": "cli", "gitBranch": "main"},
        {"type": "assistant", "requestId": "r1",
         "message": {"model": "claude-model-a", "usage": {"input_tokens": 10, "output_tokens": 5}}},
        {"type": "assistant", "requestId": "r1",
         "message": {"model": "claude-model-a", "usage": {"input_tokens": 10, "output_tokens": 7}}},
        {"type": "assistant", "requestId": "r2",
         "message": {"model": "claude-model-a", "usage": {"input_tokens": 3, "output_tokens": 1,
                                                          "cache_read_input_tokens": 100}}},
    ]
    transcript.write_text("\n".join(json.dumps(x) for x in lines) + "\n", encoding="utf-8")

    assert hook("log_event.py", base("SessionStart", source="startup", model="claude-model-a")).returncode == 0
    assert hook("log_event.py", base("UserPromptSubmit", prompt="please fix the login bug")).returncode == 0
    app_file = str(workspace / "apps" / "example-api" / "src" / "index.js")
    hook("log_event.py", base("PostToolUse", tool_name="Edit", tool_input={"file_path": app_file},
                              tool_response={}, duration_ms=12))
    hook("log_event.py", base("PostToolUse", tool_name="Agent",
                              tool_input={"subagent_type": "code-reviewer", "description": "review"},
                              tool_response={"resolvedModel": "claude-model-b"}))
    hook("log_event.py", base("PostToolUse", tool_name="mcp__github__list_issues", tool_input={}))
    hook("log_event.py", base("PostToolUseFailure", tool_name="Bash",
                              tool_input={"command": "npm test --prefix apps/example-api"},
                              error="exit 1: 2 tests failed"))
    end = hook("log_event.py", base("SessionEnd", reason="prompt_input_exit", transcript_path=str(transcript)))
    assert end.returncode == 0

    sessions = load(workspace / "sessions.json")
    s = sessions["sessions"]["s-1"]
    assert s["status"] == "ended" and s["end_reason"] == "prompt_input_exit"
    assert s["prompts"] == 1
    assert s["tool_calls"] == 4 and s["tool_failures"] == 1
    assert s["apps"]["example-api"] == 2
    assert s["subagents"] == {"code-reviewer": 1}
    assert s["claude_code_versions"] == ["2.9.0"]
    assert s["tokens"]["main"] == {"input": 13, "output": 8, "cache_read": 100, "cache_write": 0}
    assert s["models"]["claude-model-a"] == 2
    # Prompt text is never stored.
    assert "login bug" not in (workspace / "sessions.json").read_text(encoding="utf-8")

    reg = load(workspace / "registry.json")
    assert reg["totals"] == {"sessions": 1, "tool_calls": 4, "tool_failures": 1}
    assert reg["tools"]["Edit"]["avg_duration_ms"] == 12
    assert reg["mcp_servers"]["github"]["tools"] == {"list_issues": 1}
    assert reg["subagents"]["code-reviewer"]["models"] == {"claude-model-b": 1}
    assert reg["claude_code_versions"]["2.9.0"]["sessions"] == 1
    assert len(reg["recent_tool_calls"]) == 4

    errors = load(workspace / "errors.json")
    assert errors["summary"]["open"] == 1
    e = errors["errors"][0]
    assert e["id"] == "ERR-0001" and e["kind"] == "tool_failure" and e["app"] == "example-api"


def test_transcript_scan_is_incremental(workspace, hook):
    transcript = workspace / "t.jsonl"
    first = {"type": "assistant", "requestId": "r1", "message": {"model": "m", "usage": {"output_tokens": 5}}}
    transcript.write_text(json.dumps(first) + "\n", encoding="utf-8")
    hook("log_event.py", base("Stop", transcript_path=str(transcript)))
    more = {"type": "assistant", "requestId": "r1", "message": {"model": "m", "usage": {"output_tokens": 9}}}
    with open(transcript, "a", encoding="utf-8") as f:
        f.write(json.dumps(more) + "\n")
    hook("log_event.py", base("Stop", transcript_path=str(transcript)))
    s = load(workspace / "sessions.json")["sessions"]["s-1"]
    assert s["tokens"]["main"]["output"] == 9  # the continued request only adds its increase
    assert s["models"] == {"m": 1}


def test_secrets_are_redacted_before_write(workspace, hook):
    secrets = [fake_secret("ghp_"), fake_secret("sk-ant-api03-", 40), fake_secret("AKIA", 16).upper(),
               fake_secret("xoxb-", 24)]
    cmd = (f"curl -H 'Authorization: Bearer {fake_secret('', 32)}' https://api.example.com "
           f"&& export GH={secrets[0]} ANTHROPIC={secrets[1]} AWS={secrets[2]} SLACK={secrets[3]} "
           f"password=hunter2hunter2 && psql postgres://admin:s3cretpw@db.example.com/app")
    hook("log_event.py", base("PostToolUseFailure", tool_name="Bash", tool_input={"command": cmd},
                              error=f"failed with token={secrets[0]}"))
    hook("log_event.py", base("StopFailure", error="authentication_failed",
                              error_details=f"invalid key {secrets[1]}"))
    everything = "".join((workspace / n).read_text(encoding="utf-8")
                         for n in ("registry.json", "errors.json", "sessions.json"))
    for s in secrets + ["hunter2hunter2", "s3cretpw"]:
        assert s not in everything
    assert "[REDACTED]" in everything
    errors = load(workspace / "errors.json")
    assert errors["errors"][1]["severity"] == "high"


def test_fail_open_on_malformed_input(hook):
    for payload in ["", "not json", "[1, 2, 3]", "null", '{"hook_event_name": 5}',
                    json.dumps(base("PostToolUse", tool_name=None, tool_input="oops", duration_ms="x"))]:
        result = hook("log_event.py", payload)
        assert result.returncode == 0, (payload, result.stderr)
        assert result.stdout == ""


def test_fail_open_when_log_file_is_unwritable(workspace, hook):
    (workspace / "sessions.json").mkdir()  # a directory where a file should be: writing must fail
    result = hook("log_event.py", base("SessionStart", source="startup"))
    assert result.returncode == 0
    log = workspace / ".claude" / "hooks" / "hook-errors.log"
    assert log.exists() and "log_event.py" in log.read_text(encoding="utf-8")


def test_corrupt_log_is_preserved(workspace, hook):
    (workspace / "registry.json").write_text("{ broken", encoding="utf-8")
    assert hook("log_event.py", base("SessionStart", source="startup")).returncode == 0
    assert load(workspace / "registry.json")["totals"]["sessions"] == 1
    assert list(workspace.glob("registry.corrupt-*.json"))
