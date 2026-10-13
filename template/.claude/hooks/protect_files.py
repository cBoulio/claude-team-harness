"""PreToolUse hook (Edit|Write|MultiEdit|NotebookEdit): block writes Claude shouldn't make.

Blocks:
- the workspace log files (sessions.json, registry.json, errors.json) and hook-errors.log,
  which only the hooks write;
- secret and key files (.env, *.pem, SSH keys), git internals, and lockfiles;
- any write whose new content contains something that looks like a live credential.

Exit code 2 blocks the tool call and shows stderr to Claude. Any bug in this script, or input it
can't parse, exits 0 so the normal permission flow decides (fail open).
"""
import json
import os
import re
import sys
from pathlib import Path

PROTECTED = [
    (r"(^|[\\/])\.env(\.(?!example$|sample$|template$)[^\\/]+)?$", "environment/secret file"),
    (r"(^|[\\/])\.dev\.vars$", "local secrets file"),
    (r"\.(pem|key|p12|pfx|keystore|jks)$", "key or certificate"),
    (r"(^|[\\/])(id_rsa|id_ecdsa|id_ed25519)(\.pub)?$", "SSH key"),
    (r"(^|[\\/])\.git[\\/]", "git internals"),
    (r"(^|[\\/])(package-lock\.json|yarn\.lock|pnpm-lock\.yaml|poetry\.lock|uv\.lock|Cargo\.lock)$",
     "lockfile (regenerate with the package manager instead)"),
    (r"(^|[\\/])\.claude[\\/]settings\.local\.json$", "personal settings file (edit it yourself)"),
]
LOG_FILES = {"errors.json", "sessions.json", "registry.json"}

# High-confidence credential shapes only; generic "password=" text is too common in code to block.
SECRET_CONTENT = [
    (r"-----BEGIN [A-Z ]*PRIVATE KEY-----", "a private key"),
    (r"github_pat_[A-Za-z0-9_]{20,}|\bgh[pousr]_[A-Za-z0-9]{30,}", "a GitHub token"),
    (r"\bsk-ant-[A-Za-z0-9_\-]{20,}", "an Anthropic API key"),
    (r"\bsk-(proj-)?[A-Za-z0-9]{32,}", "an API secret key"),
    (r"\b(sk|rk)_live_[A-Za-z0-9]{10,}", "a live payment secret key"),
    (r"\bAKIA[0-9A-Z]{16}\b", "an AWS access key id"),
    (r"\bxox[abprs]-[A-Za-z0-9\-]{10,}", "a Slack token"),
    (r"\bAIza[0-9A-Za-z_\-]{35}\b", "a Google API key"),
]


def new_content(tool_input: dict) -> str:
    parts = [tool_input.get(k) for k in ("content", "new_string", "new_source")]
    for edit in tool_input.get("edits") or []:
        if isinstance(edit, dict):
            parts.append(edit.get("new_string"))
    return "\n".join(p for p in parts if isinstance(p, str))


def check(tool_input: dict, project_dir: str | None) -> str | None:
    """Return the reason a write is blocked, or None if it may proceed."""
    path = tool_input.get("file_path") or tool_input.get("notebook_path") or ""
    if not isinstance(path, str):
        path = ""
    if project_dir and path:
        root = Path(project_dir).resolve()
        target = Path(path) if Path(path).is_absolute() else root / path
        try:
            target = target.resolve()
        except OSError:
            target = None
        if target is not None:
            if target.parent == root and target.name in LOG_FILES:
                return (f"{target.name} is written by hooks only. "
                        "Use `python .claude/hooks/log_issue.py` to add or resolve issues")
            if target == root / ".claude" / "hooks" / "hook-errors.log":
                return "hook-errors.log is written by hooks only"
    for pattern, reason in PROTECTED:
        if path and re.search(pattern, path, re.IGNORECASE):
            return f"{reason}; ask the user to change it manually"
    content = new_content(tool_input)
    for pattern, what in SECRET_CONTENT:
        if re.search(pattern, content):
            return (f"the new content contains what looks like {what}. Keep secrets in an untracked "
                    "env file or a secret manager and reference them by name")
    return None


def main() -> int:
    try:
        data = json.load(sys.stdin)
        tool_input = data.get("tool_input") if isinstance(data, dict) else None
        if not isinstance(tool_input, dict):
            return 0
        reason = check(tool_input, os.environ.get("CLAUDE_PROJECT_DIR"))
    except Exception:  # fail open: a guard bug must not wedge the session
        return 0
    if reason:
        path = tool_input.get("file_path") or tool_input.get("notebook_path") or "file"
        print(f"Blocked write to {path}: {reason}.", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
