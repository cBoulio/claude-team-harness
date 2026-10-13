"""Shared helpers for the workspace hooks: redaction and locked, atomic JSON updates.

Hooks for parallel tool calls run at the same time, so every read-modify-write takes a lock
file first and replaces the target atomically. Logging must never break a session: callers
wrap their work in `safe_main`, which swallows errors, records them in hook-errors.log, and
always exits 0.

Python standard library only, so the hooks run anywhere Python 3.10+ is installed.
"""
import json
import os
import re
import sys
import tempfile
import time
import traceback
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(os.environ.get("CLAUDE_PROJECT_DIR") or Path(__file__).resolve().parents[2])
HOOK_ERROR_LOG = ROOT / ".claude" / "hooks" / "hook-errors.log"
LOG_FILES = ("sessions.json", "registry.json", "errors.json")
LOCK_TIMEOUT_S = 5.0
STALE_LOCK_S = 30.0

# Strings that look like credentials are masked before anything is written to disk.
# Patterns with a capture group keep group 1 (the label) and mask the rest.
SECRET_PATTERNS = [
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?(-----END [A-Z ]*PRIVATE KEY-----|$)"),
    re.compile(r"github_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(r"\bsk-(?:ant-)?[A-Za-z0-9_\-]{20,}"),
    re.compile(r"\b(?:sk|pk|rk|whsec)_(?:live|test)_[A-Za-z0-9]{10,}"),
    re.compile(r"\bwhsec_[A-Za-z0-9]{20,}"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b"),
    re.compile(r"\bxox[abprs]-[A-Za-z0-9\-]{10,}"),
    re.compile(r"\beyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}"),
    re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._\-]{20,}"),
    re.compile(r"(?i)(://[^/\s:@]+:)[^@\s/]+(?=@)"),
    re.compile(r"(?i)((?:password|passwd|pwd|secret|token|api[_-]?key|access[_-]?key)[\"']?\s*[=:]\s*[\"']?)[^\s\"',;]+"),
]


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def redact(text: str) -> str:
    for pattern in SECRET_PATTERNS:
        if pattern.groups and pattern.pattern.startswith("(?i)("):
            text = pattern.sub(lambda m: m.group(1) + "[REDACTED]", text)
        else:
            text = pattern.sub("[REDACTED]", text)
    return text


def clip(value, limit: int = 300):
    """Redact and shorten a value for logging. Non-strings are JSON-encoded first."""
    if value is None:
        return None
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
    text = redact(text)
    return text if len(text) <= limit else text[:limit] + f"... [+{len(text) - limit} chars]"


def read_stdin_json() -> dict:
    """Parse the hook event from stdin. Anything that isn't a JSON object becomes {}."""
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError, UnicodeDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def app_for_path(path) -> str | None:
    """Return the app name if `path` is inside apps/<name>/, else None."""
    if not path or not isinstance(path, str):
        return None
    try:
        rel = Path(path).resolve().relative_to((ROOT / "apps").resolve())
    except (ValueError, OSError):
        return None
    return rel.parts[0] if rel.parts and rel.parts[0] != "REGISTRY.md" else None


@contextmanager
def _locked(target: Path):
    lock = target.with_name(target.name + ".lock")
    deadline = time.monotonic() + LOCK_TIMEOUT_S
    while True:
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(fd)
            break
        except FileExistsError:
            try:
                if time.time() - lock.stat().st_mtime > STALE_LOCK_S:
                    lock.unlink(missing_ok=True)
                    continue
            except FileNotFoundError:
                continue
            if time.monotonic() > deadline:
                raise TimeoutError(f"lock busy: {lock}")
            time.sleep(0.02)
    try:
        yield
    finally:
        lock.unlink(missing_ok=True)


def update_json(name: str, default: dict, mutate) -> None:
    """Load ROOT/name (or `default`), call mutate(data) in place, and write it back pretty-printed."""
    target = ROOT / name
    with _locked(target):
        try:
            data = json.loads(target.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise json.JSONDecodeError("not an object", "", 0)
        except FileNotFoundError:
            data = default
        except json.JSONDecodeError:
            # Keep the unreadable file for inspection instead of silently overwriting it.
            target.replace(target.with_name(f"{target.stem}.corrupt-{int(time.time())}.json"))
            data = default
        mutate(data)
        data["updated_at"] = now_iso()
        fd, tmp = tempfile.mkstemp(dir=target.parent, prefix=f".{target.stem}-", suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.write("\n")
        for attempt in range(20):
            try:
                os.replace(tmp, target)
                break
            except PermissionError:
                # Windows: a reader (editor, viewer) briefly holds the file open.
                time.sleep(0.05 * (attempt + 1))
        else:
            os.unlink(tmp)
            raise PermissionError(f"could not replace {target}")


def log_hook_error(script: str) -> None:
    """Append the current exception to hook-errors.log. Never raises."""
    try:
        HOOK_ERROR_LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(HOOK_ERROR_LOG, "a", encoding="utf-8") as f:
            f.write(f"{now_iso()} {script}\n{redact(traceback.format_exc())}\n")
    except OSError:
        pass


def safe_main(fn) -> None:
    """Run fn(event); never raise or exit non-zero, so logging can't block Claude."""
    try:
        fn(read_stdin_json())
    except Exception:
        log_hook_error(Path(sys.argv[0]).name)
    sys.exit(0)
