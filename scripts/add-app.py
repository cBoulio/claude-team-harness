"""Add an app to a workspace: clone or create it under apps/<name>/ and add a registry row.

    python scripts/add-app.py example-api --repo https://github.com/<org>/example-api.git \
        --stack "Node.js, Postgres" --purpose "Public REST API"
    python scripts/add-app.py example-worker --new --stack "Python" --purpose "Nightly jobs"

--repo clones an existing repo; --new creates an empty git repo with a starter CLAUDE.md.
Run it from the workspace root, or pass --workspace. Standard library only.
"""
import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path

NAME = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
EMPTY_ROW = re.compile(r"^\|\s*_none yet_\s*\|.*\n?", re.M)

APP_CLAUDE_MD = """# {name}

{purpose}

- **Stack**: {stack}
- **Status**: {status}

## Commands

- Install: _fill in_
- Dev: _fill in_
- Test: _fill in_
- Build/deploy: _fill in_

## Layout

_Key directories and entry points._

## Environment

_Required env vars (names only) and where they're configured._
"""


def cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ").strip()


def in_registry(registry: Path, name: str) -> bool:
    text = registry.read_text(encoding="utf-8")
    return bool(re.search(rf"^\|[^|\n]*\|\s*`apps/{re.escape(name)}/?`\s*\|", text, re.M))


def add_registry_row(registry: Path, name: str, stack: str, purpose: str, status: str) -> None:
    text = EMPTY_ROW.sub("", registry.read_text(encoding="utf-8"))
    if not text.endswith("\n"):
        text += "\n"
    title = name.replace("-", " ").replace("_", " ").title()
    text += f"| {cell(title)} | `apps/{name}` | {cell(stack)} | {cell(purpose)} | {cell(status)} |\n"
    registry.write_text(text, encoding="utf-8", newline="\n")


def run_git(args: list[str], cwd: Path) -> None:
    result = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    if result.returncode != 0:
        raise SystemExit(f"error: git {' '.join(args)} failed:\n{result.stderr.strip()}")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("name", help="app folder name (lowercase, digits, . _ -)")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--repo", help="git URL or path to clone")
    source.add_argument("--new", action="store_true", help="create a new empty app repo")
    parser.add_argument("--stack", default="?", help="short stack description for the registry")
    parser.add_argument("--purpose", default="?", help="one-line purpose for the registry")
    parser.add_argument("--status", default="active", help="registry status (default: %(default)s)")
    parser.add_argument("--workspace", default=".", help="workspace root (default: current folder)")
    args = parser.parse_args(argv)

    workspace = Path(args.workspace).resolve()
    registry = workspace / "apps" / "REGISTRY.md"
    if not registry.exists():
        print(f"error: {registry} not found; run this from a workspace root or pass --workspace",
              file=sys.stderr)
        return 1
    if not NAME.match(args.name):
        print("error: name must be lowercase letters, digits, '.', '_' or '-' (e.g. example-api)",
              file=sys.stderr)
        return 1
    app_dir = workspace / "apps" / args.name
    if app_dir.exists():
        print(f"error: {app_dir} already exists", file=sys.stderr)
        return 1
    if in_registry(registry, args.name):
        print(f"error: {args.name} is already listed in {registry}", file=sys.stderr)
        return 1
    if not shutil.which("git"):
        print("error: git is not on PATH", file=sys.stderr)
        return 1

    if args.repo:
        run_git(["clone", args.repo, str(app_dir)], cwd=workspace)
        action = f"cloned {args.repo}"
    else:
        app_dir.mkdir(parents=True)
        run_git(["init", "-b", "main"], cwd=app_dir)
        (app_dir / "CLAUDE.md").write_text(
            APP_CLAUDE_MD.format(name=args.name, purpose=args.purpose, stack=args.stack, status=args.status),
            encoding="utf-8", newline="\n")
        action = "created a new git repo with a starter CLAUDE.md"

    add_registry_row(registry, args.name, args.stack, args.purpose, args.status)
    print(f"apps/{args.name}: {action}; added to apps/REGISTRY.md")
    if not (app_dir / "CLAUDE.md").exists():
        print("Next: ask Claude to run /onboard-app on it to map the app and write its CLAUDE.md.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
