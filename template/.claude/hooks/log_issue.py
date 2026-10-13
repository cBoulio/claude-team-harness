"""Log, resolve, and list issues in the workspace errors.json.

Hooks record tool and API failures automatically; use this for problems found while working
(bugs, broken setups, flaky tests, things to follow up on).

    python .claude/hooks/log_issue.py add "Title" --details "..." --severity high --app example-api
    python .claude/hooks/log_issue.py resolve ERR-0007 --resolution "Fixed in abc123"
    python .claude/hooks/log_issue.py list [--all] [--app example-api]

Text is redacted for secrets before it is written.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _store import ROOT, clip, now_iso, update_json  # noqa: E402
from log_event import add_error, errors_default, summarize_errors  # noqa: E402

SEVERITIES = ("low", "medium", "high", "critical")


def cmd_add(args) -> int:
    created = {}

    def mutate(data):
        add_error(data, {
            "kind": args.kind,
            "severity": args.severity,
            "source": "manual",
            "title": clip(args.title, 200),
            "details": clip(args.details, 4000),
            "app": args.app,
            "session_id": args.session,
            "resolved_at": None,
            "resolution": None,
        })
        created["id"] = data["errors"][-1]["id"]
        created["title"] = data["errors"][-1]["title"]

    update_json("errors.json", errors_default(), mutate)
    print(f"Logged {created['id']}: {created['title']}")
    return 0


def cmd_resolve(args) -> int:
    found = {}

    def mutate(data):
        for e in data["errors"]:
            if e["id"].upper() == args.id.upper():
                e["status"] = "resolved"
                e["resolved_at"] = now_iso()
                e["resolution"] = clip(args.resolution, 2000)
                found["ok"] = True
        summarize_errors(data)

    update_json("errors.json", errors_default(), mutate)
    if not found:
        print(f"No issue with id {args.id}", file=sys.stderr)
        return 1
    print(f"Resolved {args.id.upper()}")
    return 0


def cmd_list(args) -> int:
    try:
        data = json.loads((ROOT / "errors.json").read_text(encoding="utf-8"))
    except FileNotFoundError:
        print("No issues logged yet.")
        return 0
    rows = [e for e in data.get("errors", [])
            if (args.all or e.get("status") == "open") and (not args.app or e.get("app") == args.app)]
    for e in rows:
        print(f"{e['id']}  {e.get('status', ''):8} {e.get('severity', ''):8} {e.get('kind', ''):13} "
              f"{e.get('app') or '-':14} {e.get('title')}")
    print(f"\n{len(rows)} shown; summary: {json.dumps(data.get('summary'))}")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    add = sub.add_parser("add", help="log a new issue")
    add.add_argument("title")
    add.add_argument("--details")
    add.add_argument("--severity", choices=SEVERITIES, default="medium")
    add.add_argument("--kind", default="issue", help="issue, bug, config, flaky-test, follow-up, ...")
    add.add_argument("--app", help="app name under apps/, or omit for workspace-level")
    add.add_argument("--session", help="Claude Code session id, if known")
    add.set_defaults(func=cmd_add)

    res = sub.add_parser("resolve", help="mark an issue resolved")
    res.add_argument("id")
    res.add_argument("--resolution", required=True)
    res.set_defaults(func=cmd_resolve)

    ls = sub.add_parser("list", help="list open issues")
    ls.add_argument("--all", action="store_true", help="include resolved")
    ls.add_argument("--app", help="only issues for this app")
    ls.set_defaults(func=cmd_list)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
