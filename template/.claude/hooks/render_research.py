"""Render research dossiers (research/docs/*.md) into a static HTML site (research/site/).

Runs as a PostToolUse hook on Write|Edit|MultiEdit: when a markdown file under research/docs/
changes, its page and the index are rebuilt. It can also be run by hand:

    python .claude/hooks/render_research.py --all              # rebuild every page + index
    python .claude/hooks/render_research.py <file.md> ...      # rebuild some pages + index
    python .claude/hooks/render_research.py --root DIR --all   # use DIR instead of the workspace root

Docs may start with front matter:

    ---
    title: Choosing a vector store for a small team
    date: 2026-10-01
    author: researcher
    status: final            # draft | final | superseded
    tags: search, databases
    summary: One or two sentences shown on the page header and the index card.
    ---

Callouts are blockquotes whose first line is [!NOTE], [!TIP], [!WARNING], [!RISK], or [!VERDICT].
Raw HTML in docs is escaped, and only http(s), mailto, relative, and #anchor links are kept.
Standard library only. As a hook it never fails the tool call: errors go to stderr and exit 0.
"""
import html
import json
import os
import re
import sys
from datetime import date
from pathlib import Path


def _apply_root_flag(argv: list[str]) -> list[str]:
    """Handle --root before _store is imported, since _store reads CLAUDE_PROJECT_DIR at import."""
    if "--root" in argv:
        i = argv.index("--root")
        if i + 1 < len(argv):
            os.environ["CLAUDE_PROJECT_DIR"] = str(Path(argv[i + 1]).resolve())
            return argv[:i] + argv[i + 2:]
    return argv


ARGS = _apply_root_flag(sys.argv[1:]) if __name__ == "__main__" else []

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _markdown import render as render_markdown  # noqa: E402
from _store import ROOT, now_iso  # noqa: E402

DOCS = ROOT / "research" / "docs"
SITE = ROOT / "research" / "site"


def workspace_name() -> str:
    try:
        data = json.loads((ROOT / ".claude" / "workspace.json").read_text(encoding="utf-8"))
        return str(data.get("name") or "Workspace")
    except (OSError, ValueError, AttributeError):
        return "Workspace"


# ---------------------------------------------------------------- parsing

def split_front_matter(text: str) -> tuple[dict, str]:
    meta: dict = {}
    text = text.lstrip("﻿")
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            for line in text[3:end].strip().splitlines():
                if ":" in line:
                    key, value = line.split(":", 1)
                    meta[key.strip().lower()] = value.strip().strip('"').strip("'")
            text = text[end + 4:].lstrip("\n")
    if "tags" in meta:
        meta["tags"] = [t.strip() for t in meta["tags"].strip("[]").split(",") if t.strip()]
    return meta, text


def first_heading(body: str) -> str | None:
    m = re.search(r"^#\s+(.+)$", body, re.M)
    return m.group(1).strip() if m else None


def load_doc(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    meta, body = split_front_matter(text)
    title = meta.get("title") or first_heading(body) or path.stem.replace("-", " ").title()
    # Drop a leading H1 that repeats the title; the page header shows it.
    if first_heading(body) == title:
        body = re.sub(r"^#\s+.+\n?", "", body, count=1, flags=re.M)
    words = len(re.findall(r"\w+", body))
    return {
        "path": path,
        "slug": path.stem,
        "title": title,
        "date": meta.get("date") or date.fromtimestamp(path.stat().st_mtime).isoformat(),
        "author": meta.get("author", "unknown"),
        "status": re.sub(r"[^a-z-]", "", meta.get("status", "draft").lower()) or "draft",
        "tags": meta.get("tags", []),
        "summary": meta.get("summary", ""),
        "minutes": max(1, round(words / 230)),
        "body": body,
    }


# ---------------------------------------------------------------- templates

CSS = r"""
:root {
  --bg: #05070d; --panel: #0d1424cc; --line: #1b2a4a;
  --text: #c9d6ee; --dim: #7d8db0; --cyan: #00f0ff; --mag: #ff2bd6; --lime: #9dff3c;
  --amber: #ffb02e; --red: #ff3b5c; --violet: #9b6bff; --head: #eaf6ff;
  --mono: "JetBrains Mono", "Cascadia Code", Consolas, monospace;
  --display: "Orbitron", "JetBrains Mono", Consolas, sans-serif;
}
* { box-sizing: border-box; }
html { scroll-behavior: smooth; }
body {
  margin: 0; background: var(--bg); color: var(--text); font: 15px/1.7 var(--mono);
  background-image:
    linear-gradient(rgba(0,240,255,.035) 1px, transparent 1px),
    linear-gradient(90deg, rgba(0,240,255,.035) 1px, transparent 1px),
    radial-gradient(ellipse at top, #0c1a3a 0%, var(--bg) 60%);
  background-size: 40px 40px, 40px 40px, 100% 100%;
  background-attachment: fixed;
}
a { color: var(--cyan); text-decoration: none; border-bottom: 1px dashed rgba(0,240,255,.4); }
a:hover { color: var(--mag); border-bottom-color: var(--mag); }
.topbar {
  position: sticky; top: 0; z-index: 40; display: flex; align-items: center; gap: 16px;
  padding: 10px 24px; background: rgba(5,7,13,.88); backdrop-filter: blur(8px);
  border-bottom: 1px solid var(--line); font-size: 12px; letter-spacing: .12em; text-transform: uppercase;
}
.topbar .brand { font-family: var(--display); color: var(--cyan); border: 0; }
.topbar .path { color: var(--dim); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.wrap { max-width: 1240px; margin: 0 auto; padding: 32px 24px 80px; }
.hero { position: relative; padding: 28px 28px 24px; margin-bottom: 28px; border: 1px solid var(--line);
  background: linear-gradient(135deg, rgba(0,240,255,.07), rgba(255,43,214,.05)); }
.hero::before { content: ""; position: absolute; left: 0; top: 0; width: 120px; height: 2px; background: var(--cyan); }
.kicker { color: var(--mag); font-size: 12px; letter-spacing: .3em; text-transform: uppercase; }
h1.title { font-family: var(--display); font-size: clamp(26px, 4vw, 40px); line-height: 1.15; margin: 8px 0 14px; color: var(--head); }
.meta { display: flex; flex-wrap: wrap; gap: 8px; }
.chip { font-size: 11px; letter-spacing: .1em; text-transform: uppercase; padding: 3px 10px; border: 1px solid var(--line); color: var(--dim); background: rgba(13,20,36,.8); }
.chip.status-final { color: var(--lime); border-color: rgba(157,255,60,.5); }
.chip.status-draft { color: var(--amber); border-color: rgba(255,176,46,.5); }
.chip.status-superseded { color: var(--red); border-color: rgba(255,59,92,.5); }
.chip.tag { color: var(--cyan); border-color: rgba(0,240,255,.35); }
.summary { margin: 16px 0 0; color: #dbe7ff; max-width: 80ch; }
.layout { display: grid; grid-template-columns: 250px minmax(0, 1fr); gap: 32px; align-items: start; }
.toc { position: sticky; top: 64px; max-height: calc(100vh - 90px); overflow: auto; padding: 16px; border: 1px solid var(--line); background: var(--panel); font-size: 12.5px; }
.toc::before { content: "// CONTENTS"; display: block; color: var(--mag); letter-spacing: .25em; font-size: 11px; margin-bottom: 8px; }
.toc ul { list-style: none; margin: 0; padding-left: 10px; }
.toc > div > ul { padding-left: 0; }
.toc li { margin: 4px 0; }
.toc a { border: 0; color: var(--dim); }
.toc a:hover { color: var(--cyan); }
article { min-width: 0; padding: 8px 32px 32px; border: 1px solid var(--line); background: var(--panel); }
article h2 { font-family: var(--display); font-size: 21px; color: var(--cyan); margin: 40px 0 12px; padding-bottom: 6px; border-bottom: 1px solid var(--line); letter-spacing: .04em; }
article h3 { font-size: 16px; color: var(--head); margin: 28px 0 8px; }
.headerlink { opacity: 0; margin-left: 8px; border: 0; font-size: .8em; }
h2:hover .headerlink, h3:hover .headerlink { opacity: .6; }
strong { color: #ffffff; }
code { font-family: var(--mono); font-size: .9em; color: var(--lime); background: rgba(157,255,60,.07); padding: 1px 5px; border: 1px solid rgba(157,255,60,.15); }
pre { overflow: auto; padding: 14px 16px; background: #03050a; border: 1px solid var(--line); border-left: 3px solid var(--mag); }
pre code { background: none; border: 0; padding: 0; color: #b8ffd0; }
ul, ol { padding-left: 22px; }
li::marker { color: var(--mag); }
hr { border: 0; height: 1px; background: linear-gradient(90deg, transparent, var(--cyan), transparent); margin: 32px 0; }
.table-wrap { overflow-x: auto; margin: 16px 0; border: 1px solid var(--line); }
table { border-collapse: collapse; width: 100%; font-size: 13px; }
th { text-align: left; color: var(--cyan); background: rgba(0,240,255,.07); text-transform: uppercase; letter-spacing: .08em; font-size: 11.5px; }
th, td { padding: 8px 12px; border-bottom: 1px solid var(--line); vertical-align: top; }
blockquote { margin: 16px 0; padding: 10px 16px; border-left: 3px solid var(--violet); background: rgba(155,107,255,.07); color: #dcd2ff; }
blockquote p { margin: 6px 0; }
.callout-label { display: inline-block; margin-right: 10px; font-size: 11px; letter-spacing: .2em; font-weight: 700; }
.callout.note { border-color: var(--cyan); background: rgba(0,240,255,.06); } .callout.note .callout-label { color: var(--cyan); }
.callout.tip { border-color: var(--lime); background: rgba(157,255,60,.06); } .callout.tip .callout-label { color: var(--lime); }
.callout.warning { border-color: var(--amber); background: rgba(255,176,46,.07); } .callout.warning .callout-label { color: var(--amber); }
.callout.risk { border-color: var(--red); background: rgba(255,59,92,.08); } .callout.risk .callout-label { color: var(--red); }
.callout.verdict { border-color: var(--mag); background: rgba(255,43,214,.08); } .callout.verdict .callout-label { color: var(--mag); }
.grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(min(320px, 100%), 1fr)); gap: 18px; }
.card { display: block; padding: 18px 18px 16px; border: 1px solid var(--line); background: var(--panel); color: var(--text); transition: border-color .2s, transform .2s; }
.card:hover { border-color: var(--cyan); color: var(--text); transform: translateY(-2px); }
.card h2 { font-family: var(--display); font-size: 17px; color: var(--head); margin: 6px 0 8px; line-height: 1.3; }
.card p { color: var(--dim); font-size: 13px; margin: 0 0 12px; }
.card .date { color: var(--mag); font-size: 11px; letter-spacing: .2em; }
.empty { color: var(--dim); padding: 40px; border: 1px dashed var(--line); text-align: center; }
footer { margin-top: 40px; color: var(--dim); font-size: 11px; letter-spacing: .15em; text-transform: uppercase; text-align: center; }
@media (max-width: 900px) { .layout { grid-template-columns: 1fr; } .toc { position: static; max-height: none; } article { padding: 4px 16px 24px; } .wrap { padding: 20px 16px 60px; } }
@media (prefers-reduced-motion: reduce) { * { transition: none !important; } html { scroll-behavior: auto; } }
"""

FONTS = ('<link rel="preconnect" href="https://fonts.googleapis.com">'
         '<link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;700'
         '&family=Orbitron:wght@600;800&display=swap" rel="stylesheet">')


def shell(title: str, path_label: str, body: str) -> str:
    brand = f"{workspace_name()} // research"
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)}</title>
{FONTS}
<style>{CSS}</style>
</head>
<body>
<div class="topbar"><a class="brand" href="index.html">{html.escape(brand)}</a><span class="path">{html.escape(path_label)}</span></div>
<div class="wrap">
{body}
<footer>rendered {html.escape(now_iso())} &middot; research renderer</footer>
</div>
</body>
</html>
"""


def chips(doc: dict) -> str:
    parts = [f'<span class="chip">{html.escape(doc["date"])}</span>',
             f'<span class="chip status-{html.escape(doc["status"])}">{html.escape(doc["status"])}</span>',
             f'<span class="chip">by {html.escape(doc["author"])}</span>',
             f'<span class="chip">{doc["minutes"]} min read</span>']
    parts += [f'<span class="chip tag">#{html.escape(t)}</span>' for t in doc["tags"]]
    return "".join(parts)


def render_page(doc: dict) -> Path:
    content, toc = render_markdown(doc["body"])
    summary = f'<p class="summary">{html.escape(doc["summary"])}</p>' if doc["summary"] else ""
    body = f"""<header class="hero">
<div class="kicker">// research dossier</div>
<h1 class="title">{html.escape(doc["title"])}</h1>
<div class="meta">{chips(doc)}</div>
{summary}
</header>
<div class="layout">
<nav class="toc">{toc}</nav>
<article>{content}</article>
</div>"""
    SITE.mkdir(parents=True, exist_ok=True)
    out = SITE / f"{doc['slug']}.html"
    out.write_text(shell(doc["title"], f"/ {doc['slug']}", body), encoding="utf-8", newline="\n")
    return out


def render_index() -> Path:
    docs = sorted((load_doc(p) for p in DOCS.glob("*.md")), key=lambda d: d["date"], reverse=True)
    if docs:
        cards = "".join(
            f'<a class="card" href="{html.escape(d["slug"])}.html">'
            f'<div class="date">{html.escape(d["date"])}</div>'
            f'<h2>{html.escape(d["title"])}</h2>'
            f'<p>{html.escape(d["summary"] or "")}</p>'
            f'<div class="meta">{chips(d)}</div></a>'
            for d in docs)
        grid = f'<div class="grid">{cards}</div>'
    else:
        grid = '<div class="empty">No research yet. Docs written to research/docs/ appear here.</div>'
    body = f"""<header class="hero">
<div class="kicker">// archive</div>
<h1 class="title">Research index</h1>
<div class="meta"><span class="chip">{len(docs)} dossier{"s" if len(docs) != 1 else ""}</span></div>
</header>
{grid}"""
    SITE.mkdir(parents=True, exist_ok=True)
    out = SITE / "index.html"
    out.write_text(shell("Research index", "/ index", body), encoding="utf-8", newline="\n")
    return out


def render(paths: list[Path]) -> list[Path]:
    written = [render_page(load_doc(p)) for p in paths]
    written.append(render_index())
    return written


# ---------------------------------------------------------------- entry points

def run_hook() -> None:
    try:
        event = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError, UnicodeDecodeError):
        return
    if not isinstance(event, dict):
        return
    ti = event.get("tool_input")
    path = ti.get("file_path") if isinstance(ti, dict) else None
    if not isinstance(path, str) or not path:
        return
    p = Path(path)
    if not p.is_absolute():
        p = Path(event.get("cwd") or ROOT) / p
    p = p.resolve()
    try:
        p.relative_to(DOCS.resolve())
    except ValueError:
        return
    if p.suffix.lower() != ".md" or not p.exists():
        return
    page, _ = render([p])
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PostToolUse",
        "additionalContext": f"Research page rendered: {page}",
    }}))


def main(args: list[str]) -> int:
    if not args:
        try:
            run_hook()
        except Exception as e:  # never fail a tool call over rendering
            print(f"render_research failed: {e}", file=sys.stderr)
        return 0
    if args == ["--all"]:
        targets = sorted(DOCS.glob("*.md"))
    else:
        targets = [Path(a).resolve() for a in args]
    for out in render(targets):
        print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main(ARGS))
