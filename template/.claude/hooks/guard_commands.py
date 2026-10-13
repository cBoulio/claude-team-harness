"""PreToolUse hook (Bash|PowerShell): block destructive shell commands in every app.

Exit code 2 blocks the tool call and shows stderr to Claude. Any bug in this script, or input it
can't parse, exits 0 so the normal permission flow decides (fail open).
"""
import json
import re
import sys

# `git`, optionally followed by global options such as `-C apps/example-api` or `-c key=value`.
GIT = r"\bgit(?:\s+-[Cc]\s+\S+|\s+--[\w-]+(?:=\S+)?)*\s+"

BLOCKED = [
    (r"\brm\s+(-[A-Za-z]*\s+)*-[A-Za-z]*[rR][A-Za-z]*\s+(-[A-Za-z]+\s+)*"
     r"(/|/\*|~|~/|\$HOME|\$\{HOME\}|[A-Za-z]:[\\/]?|\.|\./|\*)(\s|$|;|&|\|)",
     "recursive delete of a root, home, or whole working directory"),
    (r"\bRemove-Item\b.*-Recurse.*\s['\"]?([A-Za-z]:\\?|~|\$HOME|\$env:USERPROFILE|\\)['\"]?(\s|$|;)",
     "recursive delete of a root or home path"),
    (r"\b(rd|rmdir)\s+/s\b.*\s[A-Za-z]:\\?(\s|$)", "recursive delete of a drive root"),
    (GIT + r"push\b(?=[^;&|]*\s(--force(?!-with-lease)\b|-f\b|\+\S+))",
     "force push (use --force-with-lease, and ask first)"),
    (GIT + r"reset\s+(.*\s)?--hard\b", "hard reset discards work (ask the user first)"),
    (GIT + r"clean\s+(-[A-Za-z]*\s+)*-[A-Za-z]*f", "git clean deletes untracked files (ask the user first)"),
    (GIT + r"(checkout|restore)\s+(--\s+)?\.(\s|$|;|&)", "discarding all working-tree changes (ask the user first)"),
    (r"\b(format|diskpart)\b\s+[A-Za-z]:", "disk formatting"),
    (r"\bmkfs(\.\w+)?\b", "disk formatting"),
    (r"\bdd\b.*\bof=/dev/", "raw write to a device"),
    (r":\(\)\s*\{\s*:\|:&\s*\};:", "fork bomb"),
    (r"\b(curl|wget|iwr|Invoke-WebRequest)\b[^|]*\|\s*(sudo\s+)?(ba|z)?sh\b", "piping a download straight into a shell"),
]


def check(command: str) -> str | None:
    """Return the reason a command is blocked, or None if it may run."""
    for pattern, reason in BLOCKED:
        if re.search(pattern, command, re.IGNORECASE):
            return reason
    return None


def main() -> int:
    try:
        data = json.load(sys.stdin)
        tool_input = data.get("tool_input") if isinstance(data, dict) else None
        command = tool_input.get("command") if isinstance(tool_input, dict) else None
        if not isinstance(command, str):
            return 0
        reason = check(command)
    except Exception:  # fail open: a guard bug must not wedge the session
        return 0
    if reason:
        print(f"Blocked command: {reason}. If this is really intended, ask the user to run it.",
              file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
