import json
import re

from conftest import REPO, TEMPLATE_HOOKS, run_script

DOC = """---
title: Sample dossier
date: 2026-03-04
author: researcher
status: final
tags: alpha, beta
summary: The short answer is yes.
---

# Sample dossier

## Bottom line

- First **bold** point with `code`
- Second point with a [link](https://example.com/page) and [1]
  1. nested ordered item

> [!VERDICT]
> Use option A.

Paragraph between callouts.

> [!RISK]
> Something could break.

## Comparison

| Option | Cost | Notes |
|--------|-----:|-------|
| A | $0 | uses a \\| pipe |
| B | $10 | *italic* |

### Details

```python
print("<b>not html</b>")
```

<script>alert('x')</script>

A [bad link](javascript:alert(1)) here.

---

1. one
2. two

See https://example.com/docs. And `https://example.com/in-code`.
"""


def make_doc(workspace, name="2026-03-04-sample.md", text=DOC):
    path = workspace / "research" / "docs" / name
    path.write_text(text, encoding="utf-8")
    return path


def test_render_all(workspace, hook):
    make_doc(workspace)
    result = hook("render_research.py", args=["--all"])
    assert result.returncode == 0, result.stderr
    page = (workspace / "research" / "site" / "2026-03-04-sample.html").read_text(encoding="utf-8")
    assert "<title>Sample dossier</title>" in page
    assert "Test Workspace // research" in page
    assert page.count("<h1") == 1  # the repeated H1 is dropped
    assert '<blockquote class="callout verdict"><p><span class="callout-label">VERDICT</span>Use option A.' in page
    assert 'class="callout risk"' in page
    assert "<strong>bold</strong>" in page and "<code>code</code>" in page and "<em>italic</em>" in page
    assert '<a href="https://example.com/page" target="_blank" rel="noopener noreferrer">link</a>' in page
    assert '<th style="text-align:right">Cost</th>' in page and "uses a | pipe" in page
    assert '<ol><li>nested ordered item</li></ol>' in page
    assert "&lt;script&gt;" in page and "<script>" not in page
    assert "&lt;b&gt;not html&lt;/b&gt;" in page
    assert "javascript:" not in page
    assert 'id="bottom-line"' in page and 'href="#comparison"' in page and 'href="#details"' in page
    assert "status-final" in page and "#alpha" in page
    assert '<a href="https://example.com/docs" target="_blank" rel="noopener noreferrer">' \
           'https://example.com/docs</a>.' in page
    assert "<code>https://example.com/in-code</code>" in page

    index = (workspace / "research" / "site" / "index.html").read_text(encoding="utf-8")
    assert 'href="2026-03-04-sample.html"' in index and "The short answer is yes." in index


def test_render_as_hook(workspace, hook):
    doc = make_doc(workspace)
    payload = {"hook_event_name": "PostToolUse", "tool_name": "Write", "tool_input": {"file_path": str(doc)}}
    result = hook("render_research.py", payload)
    assert result.returncode == 0
    out = json.loads(result.stdout)
    assert out["hookSpecificOutput"]["hookEventName"] == "PostToolUse"
    assert "2026-03-04-sample.html" in out["hookSpecificOutput"]["additionalContext"]


def test_hook_ignores_other_files_and_bad_input(workspace, hook):
    other = {"tool_name": "Write", "tool_input": {"file_path": str(workspace / "CLAUDE.md")}}
    for payload in [other, "", "nope", "[]", {"tool_input": None}]:
        result = hook("render_research.py", payload)
        assert result.returncode == 0 and result.stdout == ""
    assert not (workspace / "research" / "site").exists()


def test_hook_never_fails_the_tool_call(workspace, hook):
    doc = workspace / "research" / "docs" / "broken.md"
    doc.write_bytes(b"\xff\xfe not utf-8 \x80")
    result = hook("render_research.py", {"tool_name": "Write", "tool_input": {"file_path": str(doc)}})
    assert result.returncode == 0
    assert "render_research failed" in result.stderr


def test_empty_index(workspace, hook):
    assert hook("render_research.py", args=["--all"]).returncode == 0
    index = (workspace / "research" / "site" / "index.html").read_text(encoding="utf-8")
    assert "No research yet" in index


def strip_volatile(html_text: str) -> str:
    return re.sub(r"<footer>.*?</footer>", "", html_text.replace("\r\n", "\n"), flags=re.S)


def test_committed_example_site_is_current(tmp_path):
    """examples/research/site and docs/ must match what the renderer produces today."""
    import shutil
    root = tmp_path / "ex"
    shutil.copytree(REPO / "examples" / "research" / "docs", root / "research" / "docs")
    result = run_script(TEMPLATE_HOOKS / "render_research.py", ["--root", str(root), "--all"])
    assert result.returncode == 0, result.stderr
    for fresh in (root / "research" / "site").glob("*.html"):
        for committed_dir in (REPO / "examples" / "research" / "site", REPO / "docs"):
            committed = committed_dir / fresh.name
            assert committed.exists(), f"{committed} missing; run scripts/render-examples.py"
            assert strip_volatile(committed.read_text(encoding="utf-8")) == \
                strip_volatile(fresh.read_text(encoding="utf-8")), \
                f"{committed} is stale; run scripts/render-examples.py"
