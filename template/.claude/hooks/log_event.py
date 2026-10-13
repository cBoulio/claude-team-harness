"""Logging hook: records sessions, tool usage, models, versions, and errors as JSON in the workspace root.

Wired to several hook events in .claude/settings.json and dispatches on `hook_event_name`:

- sessions.json  one record per Claude Code session (timing, models, version, prompt count,
                 tools, subagents, apps touched, token usage)
- registry.json  running totals: tools, MCP servers, subagents, models, Claude Code versions,
                 apps, plus the most recent tool calls
- errors.json    tool failures and API failures (manual issues are added with log_issue.py)

Prompt text is never stored, only counted. Tool inputs are summarized, clipped, and redacted.

Model, version, and token usage aren't in most hook inputs, so Stop/SessionEnd read them from the
session transcript, scanning only the bytes added since the last scan.
"""
import json
import re
from datetime import datetime
from pathlib import Path

from _store import app_for_path, clip, now_iso, safe_main, update_json

SCHEMA_VERSION = 1
RECENT_CALLS_KEPT = 200
ERRORS_KEPT = 2000
APP_IN_TEXT = re.compile(r"apps[\\/]([A-Za-z0-9._-]+)")
TOKEN_FIELDS = {
    "input_tokens": "input",
    "output_tokens": "output",
    "cache_read_input_tokens": "cache_read",
    "cache_creation_input_tokens": "cache_write",
}
HIGH_SEVERITY_API_ERRORS = {"authentication_failed", "billing_error", "account_on_hold",
                            "oauth_org_not_allowed", "cloud_credential_error"}


def sessions_default() -> dict:
    return {"schema_version": SCHEMA_VERSION, "updated_at": None, "sessions": {}}


def registry_default() -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "updated_at": None,
        "totals": {"sessions": 0, "tool_calls": 0, "tool_failures": 0},
        "tools": {},
        "mcp_servers": {},
        "subagents": {},
        "models": {},
        "claude_code_versions": {},
        "apps": {},
        "recent_tool_calls": [],
    }


def errors_default() -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "updated_at": None,
        "summary": {"total": 0, "open": 0, "by_kind": {}, "open_by_severity": {}},
        "next_id": 1,
        "errors": [],
    }


def empty_tokens() -> dict:
    return {name: 0 for name in TOKEN_FIELDS.values()}


def as_dict(value) -> dict:
    return value if isinstance(value, dict) else {}


# ---------------------------------------------------------------- helpers

def session_record(data: dict, event: dict) -> dict:
    sid = str(event.get("session_id") or "unknown")
    s = data["sessions"].setdefault(sid, {
        "session_id": sid,
        "status": "active",
        "title": None,
        "started_at": now_iso(),
        "ended_at": None,
        "duration_minutes": None,
        "last_activity_at": None,
        "start_source": None,
        "end_reason": None,
        "cwd": None,
        "entrypoint": None,
        "git_branch": None,
        "permission_mode": None,
        "effort": None,
        "claude_code_versions": [],
        "models": {},
        "prompts": 0,
        "tool_calls": 0,
        "tool_failures": 0,
        "interrupts": 0,
        "compactions": 0,
        "tools": {},
        "subagents": {},
        "apps": {},
        "tokens": {"main": empty_tokens(), "subagents": empty_tokens()},
        "transcript": {"path": None, "bytes_scanned": 0, "last_request_id": None, "last_request_usage": None},
    })
    s["last_activity_at"] = now_iso()
    s["cwd"] = event.get("cwd") or s["cwd"]
    s["permission_mode"] = event.get("permission_mode") or s["permission_mode"]
    effort = event.get("effort")
    if isinstance(effort, dict):
        effort = effort.get("level")
    s["effort"] = effort or s["effort"]
    if event.get("transcript_path"):
        s["transcript"]["path"] = event["transcript_path"]
    return s


def bump(counter: dict, key: str, by: int = 1) -> None:
    counter[key] = counter.get(key, 0) + by


def touch(entry: dict, at: str) -> None:
    entry.setdefault("first_seen_at", at)
    entry["last_seen_at"] = at


def detect_app(tool_input: dict, cwd) -> str:
    """Name of the app a tool call touched, or "workspace" for workspace-level work."""
    for key in ("file_path", "notebook_path", "path"):
        app = app_for_path(tool_input.get(key))
        if app:
            return app
    for key in ("command", "pattern", "description", "prompt"):
        value = tool_input.get(key)
        if isinstance(value, str):
            m = APP_IN_TEXT.search(value)
            if m and m.group(1) != "REGISTRY.md":
                return m.group(1)
    return app_for_path(cwd) or "workspace"


def summarize_input(tool: str, ti: dict) -> str | None:
    if tool in ("Bash", "PowerShell", "Monitor"):
        return clip(ti.get("command"), 200)
    if tool in ("Read", "Write", "Edit", "MultiEdit", "NotebookEdit"):
        return clip(ti.get("file_path") or ti.get("notebook_path"), 200)
    if tool in ("Grep", "Glob"):
        return clip(f"{ti.get('pattern')} in {ti.get('path') or '.'}", 200)
    if tool == "WebFetch":
        return clip(ti.get("url"), 200)
    if tool == "WebSearch":
        return clip(ti.get("query"), 200)
    if tool in ("Agent", "Task"):
        return clip(f"{ti.get('subagent_type') or 'general-purpose'}: {ti.get('description')}", 200)
    if tool == "Skill":
        return clip(ti.get("skill"), 200)
    return clip(ti, 200)


def add_error(data: dict, entry: dict) -> None:
    entry = {"id": f"ERR-{data['next_id']:04d}", "logged_at": now_iso(), "status": "open", **entry}
    data["next_id"] += 1
    data["errors"].append(entry)
    del data["errors"][:-ERRORS_KEPT]
    summarize_errors(data)


def summarize_errors(data: dict) -> None:
    errors = data["errors"]
    by_kind, by_severity = {}, {}
    for e in errors:
        bump(by_kind, e.get("kind", "unknown"))
        if e.get("status") == "open":
            bump(by_severity, e.get("severity", "medium"))
    data["summary"] = {
        "total": len(errors),
        "open": sum(1 for e in errors if e.get("status") == "open"),
        "by_kind": by_kind,
        "open_by_severity": by_severity,
    }


# ---------------------------------------------------------------- transcript scanning

def scan_transcript(path, offset: int, last_rid, last_usage) -> dict:
    """Read transcript lines after `offset`; return versions, models, tokens, and the new offset.

    Each API response can span several transcript lines sharing one requestId, so token usage is
    counted once per requestId (taking the largest values seen). A requestId that continues from
    the previous scan only adds its increase.
    """
    result = {"offset": offset, "versions": set(), "models": {}, "tokens": empty_tokens(),
              "entrypoint": None, "git_branch": None, "last_rid": last_rid, "last_usage": last_usage}
    if not path:
        return result
    p = Path(path)
    try:
        size = p.stat().st_size
    except OSError:
        return result
    if size < offset:  # transcript was rewritten; start over
        offset, last_rid, last_usage = 0, None, None
    with open(p, "rb") as f:
        f.seek(offset)
        chunk = f.read()
    end = chunk.rfind(b"\n") + 1  # leave a partially written last line for next time
    result["offset"] = offset + end

    usage_by_rid: dict[str, dict] = {}
    order: list[str] = []
    for raw in chunk[:end].splitlines():
        try:
            line = json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
        if not isinstance(line, dict):
            continue
        if line.get("version"):
            result["versions"].add(line["version"])
        result["entrypoint"] = line.get("entrypoint") or result["entrypoint"]
        result["git_branch"] = line.get("gitBranch") or result["git_branch"]
        msg = line.get("message")
        if line.get("type") != "assistant" or not isinstance(msg, dict):
            continue
        model = msg.get("model")
        rid = line.get("requestId") or msg.get("id")
        usage = as_dict(msg.get("usage"))
        if not rid:
            continue
        if rid not in usage_by_rid:
            order.append(rid)
            usage_by_rid[rid] = {"model": model, **empty_tokens()}
        for src, dst in TOKEN_FIELDS.items():
            value = usage.get(src)
            if isinstance(value, int):
                usage_by_rid[rid][dst] = max(usage_by_rid[rid][dst], value)

    for rid in order:
        u = usage_by_rid[rid]
        prior = last_usage if rid == last_rid and last_usage else empty_tokens()
        for name in TOKEN_FIELDS.values():
            result["tokens"][name] += max(0, u[name] - prior.get(name, 0))
        model = u["model"]
        if model and model != "<synthetic>" and rid != last_rid:
            bump(result["models"], model)
    if order:
        result["last_rid"] = order[-1]
        result["last_usage"] = {k: v for k, v in usage_by_rid[order[-1]].items() if k != "model"}
    return result


def apply_scan_to_session(session: dict, scan: dict, token_bucket: str) -> tuple[set, set]:
    """Fold a scan into the session record; return (versions, models) the session hadn't seen yet."""
    new_versions = {v for v in scan["versions"] if v not in session["claude_code_versions"]}
    new_models = {m for m in scan["models"] if m not in session["models"]}
    session["claude_code_versions"].extend(sorted(new_versions))
    for model, requests in scan["models"].items():
        bump(session["models"], model, requests)
    for name, value in scan["tokens"].items():
        session["tokens"][token_bucket][name] += value
    session["entrypoint"] = scan["entrypoint"] or session["entrypoint"]
    session["git_branch"] = scan["git_branch"] or session["git_branch"]
    return new_versions, new_models


def apply_scan_to_registry(scan: dict, new_versions: set, new_models: set) -> None:
    def mutate(reg):
        at = now_iso()
        for v in scan["versions"]:
            entry = reg["claude_code_versions"].setdefault(v, {"sessions": 0})
            entry["sessions"] += int(v in new_versions)
            touch(entry, at)
        for model, requests in scan["models"].items():
            entry = reg["models"].setdefault(model, {"sessions": 0, "requests": 0})
            entry["sessions"] += int(model in new_models)
            entry["requests"] += requests
            touch(entry, at)

    if scan["versions"] or scan["models"]:
        update_json("registry.json", registry_default(), mutate)


def sync_transcript(event: dict) -> None:
    """Scan the main transcript for new lines and fold the results into sessions + registry."""
    holder = {}

    def mutate(data):
        s = session_record(data, event)
        t = s["transcript"]
        scan = scan_transcript(t["path"], t["bytes_scanned"], t["last_request_id"], t["last_request_usage"])
        t["bytes_scanned"], t["last_request_id"], t["last_request_usage"] = (
            scan["offset"], scan["last_rid"], scan["last_usage"])
        holder["scan"] = scan
        holder["new"] = apply_scan_to_session(s, scan, "main")

    update_json("sessions.json", sessions_default(), mutate)
    if "scan" in holder:
        apply_scan_to_registry(holder["scan"], *holder["new"])


# ---------------------------------------------------------------- event handlers

def on_session_start(event: dict) -> None:
    source = event.get("source")
    model = event.get("model")
    is_new = {}

    def mutate(data):
        is_new["value"] = str(event.get("session_id") or "unknown") not in data["sessions"]
        s = session_record(data, event)
        s["status"] = "active"
        s["start_source"] = s["start_source"] or source
        if source in ("resume", "clear", "compact", "fork") and not is_new["value"]:
            s.setdefault("restarts", []).append({"at": now_iso(), "source": source})
        if isinstance(model, str) and model and model not in s["models"]:
            s["models"][model] = 0

    update_json("sessions.json", sessions_default(), mutate)

    def reg(data):
        if is_new.get("value"):
            data["totals"]["sessions"] += 1

    update_json("registry.json", registry_default(), reg)


def on_prompt(event: dict) -> None:
    def mutate(data):
        s = session_record(data, event)
        s["prompts"] += 1  # count only; prompt text is never stored
        if event.get("session_title"):
            s["title"] = clip(event["session_title"], 120)

    update_json("sessions.json", sessions_default(), mutate)


def on_tool(event: dict, failed: bool) -> None:
    at = now_iso()
    tool = str(event.get("tool_name") or "unknown")
    ti = as_dict(event.get("tool_input"))
    app = detect_app(ti, event.get("cwd"))
    duration = event.get("duration_ms")
    interrupted = bool(event.get("is_interrupt"))
    agent_type = event.get("agent_type") or None  # set when the call ran inside a subagent
    is_agent_call = tool in ("Agent", "Task")

    def reg(data):
        data["totals"]["tool_calls"] += 1
        t = data["tools"].setdefault(tool, {"calls": 0, "failures": 0, "total_duration_ms": 0,
                                            "avg_duration_ms": None})
        t["calls"] += 1
        if failed:
            t["failures"] += 1
            data["totals"]["tool_failures"] += 1
        if isinstance(duration, (int, float)):
            t["total_duration_ms"] += int(duration)
            t["avg_duration_ms"] = round(t["total_duration_ms"] / t["calls"])
        touch(t, at)

        if tool.startswith("mcp__"):
            server = as_dict(event.get("mcp_server")).get("name") or tool.split("__")[1]
            m = data["mcp_servers"].setdefault(server, {"calls": 0, "failures": 0, "tools": {}})
            m["calls"] += 1
            m["failures"] += int(failed)
            bump(m["tools"], tool.split("__", 2)[-1])
            touch(m, at)

        if is_agent_call:
            sub = ti.get("subagent_type") or "general-purpose"
            a = data["subagents"].setdefault(sub, {"invocations": 0, "failures": 0, "models": {}})
            a["invocations"] += 1
            a["failures"] += int(failed)
            model = as_dict(event.get("tool_response")).get("resolvedModel")
            if model:
                bump(a["models"], model)
            touch(a, at)

        ap = data["apps"].setdefault(app, {"tool_calls": 0, "tool_failures": 0})
        ap["tool_calls"] += 1
        ap["tool_failures"] += int(failed)
        touch(ap, at)

        data["recent_tool_calls"].append({
            "at": at,
            "session_id": event.get("session_id"),
            "tool": tool,
            "ok": not failed,
            "duration_ms": duration if isinstance(duration, (int, float)) else None,
            "app": app,
            "agent": agent_type,
            "input": summarize_input(tool, ti),
        })
        del data["recent_tool_calls"][:-RECENT_CALLS_KEPT]

    update_json("registry.json", registry_default(), reg)

    def sess(data):
        s = session_record(data, event)
        s["tool_calls"] += 1
        bump(s["tools"], tool)
        bump(s["apps"], app)
        if failed:
            s["tool_failures"] += 1
            s["interrupts"] += int(interrupted)
        if is_agent_call:
            bump(s["subagents"], ti.get("subagent_type") or "general-purpose")

    update_json("sessions.json", sessions_default(), sess)

    if failed and not interrupted:
        update_json("errors.json", errors_default(), lambda data: add_error(data, {
            "kind": "tool_failure",
            "severity": "low",
            "source": "hook:PostToolUseFailure",
            "title": f"{tool} failed",
            "details": clip(event.get("error"), 1500),
            "app": app,
            "session_id": event.get("session_id"),
            "agent": agent_type,
            "tool_name": tool,
            "tool_input": summarize_input(tool, ti),
            "resolved_at": None,
            "resolution": None,
        }))


def on_stop_failure(event: dict) -> None:
    kind = str(event.get("error") or "unknown")
    update_json("errors.json", errors_default(), lambda data: add_error(data, {
        "kind": "api_failure",
        "severity": "high" if kind in HIGH_SEVERITY_API_ERRORS else "medium",
        "source": "hook:StopFailure",
        "title": f"Turn ended with API error: {clip(kind, 80)}",
        "details": clip(event.get("error_details"), 1500),
        "app": app_for_path(event.get("cwd")) or "workspace",
        "session_id": event.get("session_id"),
        "resolved_at": None,
        "resolution": None,
    }))


def on_subagent_stop(event: dict) -> None:
    scan = scan_transcript(event.get("agent_transcript_path"), 0, None, None)
    scan["versions"] = set()  # the main transcript already records the version
    scan["entrypoint"] = scan["git_branch"] = None
    holder = {}

    def mutate(data):
        holder["new"] = apply_scan_to_session(session_record(data, event), scan, "subagents")

    update_json("sessions.json", sessions_default(), mutate)
    apply_scan_to_registry(scan, *holder["new"])


def on_pre_compact(event: dict) -> None:
    def mutate(data):
        s = session_record(data, event)
        s["compactions"] += 1

    update_json("sessions.json", sessions_default(), mutate)


def on_session_end(event: dict) -> None:
    sync_transcript(event)

    def mutate(data):
        s = session_record(data, event)
        s["status"] = "ended"
        s["ended_at"] = now_iso()
        s["end_reason"] = event.get("reason")
        try:
            started = datetime.fromisoformat(s["started_at"])
            ended = datetime.fromisoformat(s["ended_at"])
            s["duration_minutes"] = round((ended - started).total_seconds() / 60, 1)
        except (TypeError, ValueError):
            pass

    update_json("sessions.json", sessions_default(), mutate)


HANDLERS = {
    "SessionStart": on_session_start,
    "UserPromptSubmit": on_prompt,
    "PostToolUse": lambda e: on_tool(e, failed=False),
    "PostToolUseFailure": lambda e: on_tool(e, failed=True),
    "Stop": sync_transcript,
    "StopFailure": on_stop_failure,
    "SubagentStop": on_subagent_stop,
    "PreCompact": on_pre_compact,
    "SessionEnd": on_session_end,
}


def main(event: dict) -> None:
    handler = HANDLERS.get(event.get("hook_event_name"))
    if handler:
        handler(event)


if __name__ == "__main__":
    safe_main(main)
