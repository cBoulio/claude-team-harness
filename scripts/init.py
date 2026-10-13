"""Create a new Claude Code team workspace from this template.

    python scripts/init.py ../acme-workspace --name "Acme Platform"
    python scripts/init.py ~/work/ws --python python3 --no-git

Copies template/ into the target folder, fills in the workspace name and Python command,
adds scripts/add-app.py, writes .claude/workspace.json, and runs `git init -b main` (unless
--no-git). Standard library only.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
TEMPLATE = REPO / "template"
TEXT_SUFFIXES = {".md", ".json", ".py", ".txt", ""}
RENAMES = {"_gitignore": ".gitignore"}
SKIP_DIRS = {"__pycache__", ".pytest_cache"}


def default_python() -> str:
    return "python" if os.name == "nt" else "python3"


def title_from_dir(path: Path) -> str:
    return path.name.replace("-", " ").replace("_", " ").title() or "Workspace"


def copy_template(target: Path, replacements: dict) -> list[Path]:
    written = []
    for src in sorted(TEMPLATE.rglob("*")):
        rel = src.relative_to(TEMPLATE)
        if any(part in SKIP_DIRS for part in rel.parts) or src.suffix == ".pyc":
            continue
        dest = target.joinpath(*[RENAMES.get(p, p) for p in rel.parts])
        if src.is_dir():
            dest.mkdir(parents=True, exist_ok=True)
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        if src.suffix in TEXT_SUFFIXES:
            text = src.read_text(encoding="utf-8")
            for key, value in replacements.items():
                text = text.replace("{{" + key + "}}", value)
            dest.write_text(text, encoding="utf-8", newline="\n")
        else:
            shutil.copy2(src, dest)
        written.append(dest)
    return written


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("target", help="folder to create the workspace in (must be empty or missing)")
    parser.add_argument("--name", help="workspace name (default: from the folder name)")
    parser.add_argument("--python", default=default_python(),
                        help="command hooks use to run Python (default: %(default)s)")
    parser.add_argument("--no-git", action="store_true", help="don't run git init")
    parser.add_argument("--force", action="store_true", help="allow a non-empty target folder")
    args = parser.parse_args(argv)

    target = Path(args.target).expanduser().resolve()
    if target.exists() and any(target.iterdir()) and not args.force:
        print(f"error: {target} is not empty (use --force to write into it anyway)", file=sys.stderr)
        return 1
    if (target / ".claude" / "settings.json").exists() and args.force:
        print(f"error: {target} already has .claude/settings.json; refusing to overwrite", file=sys.stderr)
        return 1
    if any(c in args.python for c in "\"'`$;&|"):
        print("error: --python must be a plain command such as python3 or py", file=sys.stderr)
        return 1

    name = (args.name or title_from_dir(target)).strip()
    target.mkdir(parents=True, exist_ok=True)
    replacements = {"WORKSPACE_NAME": name, "PYTHON": args.python, "DATE": date.today().isoformat()}
    written = copy_template(target, replacements)

    scripts = target / "scripts"
    scripts.mkdir(exist_ok=True)
    shutil.copy2(REPO / "scripts" / "add-app.py", scripts / "add-app.py")
    (target / ".claude" / "workspace.json").write_text(
        json.dumps({"name": name, "python": args.python, "created": date.today().isoformat(),
                    "template": "claude-team-harness"}, indent=2) + "\n",
        encoding="utf-8", newline="\n")

    git_note = "skipped (--no-git)"
    if not args.no_git:
        if shutil.which("git"):
            result = subprocess.run(["git", "init", "-b", "main"], cwd=target, capture_output=True, text=True)
            git_note = "initialized (branch main)" if result.returncode == 0 else f"failed: {result.stderr.strip()}"
        else:
            git_note = "skipped (git not found)"

    print(f"Created workspace '{name}' at {target}")
    print(f"  {len(written) + 2} files written; git: {git_note}")
    print("\nNext steps:")
    print(f"  cd {target}")
    print(f"  {args.python} scripts/add-app.py example-api --repo https://github.com/<org>/example-api.git "
          "--stack \"Node.js\" --purpose \"Public REST API\"")
    print("  claude            # start a session; hooks begin logging to sessions.json")
    print("  Edit the 'Team conventions' section of CLAUDE.md for your team.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
