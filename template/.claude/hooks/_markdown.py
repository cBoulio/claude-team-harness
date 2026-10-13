"""A small, safe Markdown-to-HTML converter (standard library only).

Covers what research dossiers use: front matter is handled by the caller; this module renders
headings (with ids and a table of contents), paragraphs, ordered and unordered lists (nested by
indentation), fenced code, tables, blockquotes, callouts (`> [!NOTE]` and friends), horizontal
rules, and inline code, bold, italic, and links.

Raw HTML is always escaped, and only http(s), mailto, relative, and #anchor links are kept,
because research text often quotes untrusted web content.
"""
import html
import re

CALLOUTS = {"NOTE": "note", "TIP": "tip", "WARNING": "warning", "RISK": "risk", "VERDICT": "verdict"}
SAFE_HREF = re.compile(r"^(https?:|mailto:|#|\./|\.\./|[A-Za-z0-9_\-./]+(#[\w\-]*)?$)", re.I)

FENCE = re.compile(r"^(\s*)(`{3,}|~{3,})\s*([\w+\-]*)\s*$")
HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
HR = re.compile(r"^\s{0,3}([-*_])(\s*\1){2,}\s*$")
LIST_ITEM = re.compile(r"^(\s*)([-*+]|\d{1,9}[.)])\s+(.*)$")
TABLE_SEP = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)*\|?\s*$")
CALLOUT_START = re.compile(r"^\[!([A-Za-z]+)\]\s*(.*)$")


# ---------------------------------------------------------------- inline

def slugify(text: str, used: set) -> str:
    base = re.sub(r"[^\w\s-]", "", re.sub(r"<[^>]+>", "", text)).strip().lower()
    base = re.sub(r"[\s_]+", "-", base) or "section"
    slug, n = base, 1
    while slug in used:
        n += 1
        slug = f"{base}-{n}"
    used.add(slug)
    return slug


def safe_href(url: str) -> str:
    url = url.strip()
    return url if SAFE_HREF.match(url) else "#"


def inline(text: str) -> str:
    """Render inline markdown. Input is raw text; everything not markup is escaped."""
    stash: list[str] = []

    def keep(fragment: str) -> str:
        stash.append(fragment)
        return f"\x00{len(stash) - 1}\x00"

    text = text.replace("\x00", "")
    # Code spans first, so their contents are never treated as markup.
    text = re.sub(r"(`+)(.+?)\1", lambda m: keep(f"<code>{html.escape(m.group(2).strip())}</code>"), text)

    def link(m):
        label, url = m.group(1), m.group(2)
        href = safe_href(url.split()[0] if url.split() else "")
        attrs = ' target="_blank" rel="noopener noreferrer"' if href.lower().startswith("http") else ""
        return keep(f'<a href="{html.escape(href, quote=True)}"{attrs}>{inline(label)}</a>')

    text = re.sub(r"\[([^\]\n]+)\]\(([^)\s]+(?:\s+\"[^\"]*\")?)\)", link, text)
    text = re.sub(r"<(https?://[^>\s]+)>",
                  lambda m: keep(f'<a href="{html.escape(m.group(1), quote=True)}" target="_blank" '
                                 f'rel="noopener noreferrer">{html.escape(m.group(1))}</a>'), text)
    text = re.sub(r"(?<![\w/\"'=])(https?://[^\s<>()\[\]\"']*[^\s<>()\[\]\"'.,;:!?])",
                  lambda m: keep(f'<a href="{html.escape(m.group(1), quote=True)}" target="_blank" '
                                 f'rel="noopener noreferrer">{html.escape(m.group(1))}</a>'), text)
    text = html.escape(text, quote=False)
    text = re.sub(r"\*\*(?=\S)(.+?)(?<=\S)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"(?<![\w*])__(?=\S)(.+?)(?<=\S)__(?![\w*])", r"<strong>\1</strong>", text)
    text = re.sub(r"(?<![\w*])\*(?=[^\s*])(.+?)(?<=[^\s*])\*(?![\w*])", r"<em>\1</em>", text)
    text = re.sub(r"(?<![\w_])_(?=[^\s_])(.+?)(?<=[^\s_])_(?![\w_])", r"<em>\1</em>", text)
    text = re.sub(r"  $", "<br>", text, flags=re.M)
    while "\x00" in text:
        new = re.sub(r"\x00(\d+)\x00", lambda m: stash[int(m.group(1))], text)
        if new == text:
            break
        text = new
    return text


# ---------------------------------------------------------------- blocks

class Renderer:
    def __init__(self, with_toc: bool = True):
        self.with_toc = with_toc
        self.toc: list[tuple[int, str, str]] = []
        self.used_ids: set = set()

    def convert(self, text: str) -> str:
        lines = text.replace("\r\n", "\n").replace("\r", "\n").expandtabs(4).split("\n")
        return self.blocks(lines)

    def toc_html(self) -> str:
        if not self.toc:
            return ""
        out, depth = ["<div>"], 0
        base = min(level for level, _, _ in self.toc)
        for level, slug, label in self.toc:
            level = level - base + 1
            if level > depth:
                while depth < level:
                    out.append("<ul>")
                    depth += 1
            else:
                out.append("</li>")
                while depth > level:
                    out.append("</ul></li>")
                    depth -= 1
            out.append(f'<li><a href="#{slug}">{label}</a>')
        out.append("</li>")
        while depth > 1:
            out.append("</ul></li>")
            depth -= 1
        out.append("</ul></div>")
        return "".join(out)

    # -- block dispatch

    def blocks(self, lines: list[str]) -> str:
        out: list[str] = []
        i, n = 0, len(lines)
        while i < n:
            line = lines[i]
            if not line.strip():
                i += 1
                continue
            m = FENCE.match(line)
            if m:
                i = self.fenced(lines, i, m, out)
                continue
            m = HEADING.match(line)
            if m:
                self.heading(len(m.group(1)), m.group(2), out)
                i += 1
                continue
            if HR.match(line):
                out.append("<hr>")
                i += 1
                continue
            if line.lstrip().startswith(">"):
                i = self.blockquote(lines, i, out)
                continue
            if "|" in line and i + 1 < n and TABLE_SEP.match(lines[i + 1]) and "-" in lines[i + 1]:
                i = self.table(lines, i, out)
                continue
            if LIST_ITEM.match(line):
                i = self.list_block(lines, i, out)
                continue
            i = self.paragraph(lines, i, out)
        return "\n".join(out)

    def heading(self, level: int, text: str, out: list) -> None:
        content = inline(text)
        if self.with_toc and level in (2, 3):
            slug = slugify(content, self.used_ids)
            self.toc.append((level, slug, content))
            out.append(f'<h{level} id="{slug}">{content}<a class="headerlink" href="#{slug}" '
                       f'title="Link to this section">#</a></h{level}>')
        else:
            out.append(f"<h{level}>{content}</h{level}>")

    def fenced(self, lines, i, m, out) -> int:
        indent, fence, lang = len(m.group(1)), m.group(2), m.group(3)
        body, i = [], i + 1
        while i < len(lines):
            stripped = lines[i].strip()
            if stripped.startswith(fence[0] * len(fence)) and set(stripped) <= {fence[0]}:
                i += 1
                break
            body.append(lines[i][indent:] if lines[i][:indent].strip() == "" else lines[i])
            i += 1
        cls = f' class="language-{html.escape(lang)}"' if lang else ""
        out.append(f"<pre><code{cls}>{html.escape(chr(10).join(body))}</code></pre>")
        return i

    def blockquote(self, lines, i, out) -> int:
        inner = []
        while i < len(lines) and lines[i].lstrip().startswith(">"):
            inner.append(re.sub(r"^\s*>\s?", "", lines[i]))
            i += 1
        m = CALLOUT_START.match(inner[0].strip()) if inner else None
        if m and m.group(1).upper() in CALLOUTS:
            kind = m.group(1).upper()
            inner[0] = m.group(2)
            body = Renderer(with_toc=False).blocks(inner)
            label = f'<span class="callout-label">{kind}</span>'
            body = body.replace("<p>", f"<p>{label}", 1) if body.startswith("<p>") else label + body
            out.append(f'<blockquote class="callout {CALLOUTS[kind]}">{body}</blockquote>')
        else:
            out.append(f"<blockquote>{Renderer(with_toc=False).blocks(inner)}</blockquote>")
        return i

    def table(self, lines, i, out) -> int:
        def cells(row: str) -> list[str]:
            row = row.strip()
            row = row[1:] if row.startswith("|") else row
            row = row[:-1] if row.endswith("|") and not row.endswith("\\|") else row
            return [c.strip().replace("\\|", "|") for c in re.split(r"(?<!\\)\|", row)]

        head = cells(lines[i])
        aligns = []
        for spec in cells(lines[i + 1]):
            left, right = spec.startswith(":"), spec.endswith(":")
            aligns.append("center" if left and right else "right" if right else "left" if left else None)
        i += 2
        rows = []
        while i < len(lines) and lines[i].strip() and "|" in lines[i]:
            rows.append(cells(lines[i]))
            i += 1

        def cell(tag, text, col):
            align = aligns[col] if col < len(aligns) else None
            style = f' style="text-align:{align}"' if align else ""
            return f"<{tag}{style}>{inline(text)}</{tag}>"

        thead = "".join(cell("th", h, c) for c, h in enumerate(head))
        tbody = "".join(
            "<tr>" + "".join(cell("td", row[c] if c < len(row) else "", c) for c in range(len(head))) + "</tr>"
            for row in rows)
        out.append(f'<div class="table-wrap"><table><thead><tr>{thead}</tr></thead>'
                   f"<tbody>{tbody}</tbody></table></div>")
        return i

    def list_block(self, lines, i, out) -> int:
        first = LIST_ITEM.match(lines[i])
        base_indent = len(first.group(1))
        ordered = first.group(2)[0].isdigit()
        items: list[list[str]] = []
        loose = False
        start = int(re.match(r"\d+", first.group(2)).group()) if ordered else 1
        while i < len(lines):
            line = lines[i]
            m = LIST_ITEM.match(line)
            if m and len(m.group(1)) == base_indent and m.group(2)[0].isdigit() == ordered:
                content_indent = len(m.group(1)) + len(m.group(2)) + 1
                items.append([m.group(3)])
                i += 1
                continue
            if not line.strip():
                # A blank line continues the list only if indented content or another item follows.
                j = i + 1
                while j < len(lines) and not lines[j].strip():
                    j += 1
                if j < len(lines):
                    nm = LIST_ITEM.match(lines[j])
                    indent = len(lines[j]) - len(lines[j].lstrip())
                    if (nm and len(nm.group(1)) == base_indent and nm.group(2)[0].isdigit() == ordered) \
                            or indent > base_indent:
                        loose = loose or not (nm and len(nm.group(1)) > base_indent)
                        items[-1].append("")
                        i += 1
                        continue
                break
            indent = len(line) - len(line.lstrip())
            if indent > base_indent:
                strip = min(indent, content_indent)
                items[-1].append(line[strip:])
                i += 1
                continue
            if m or HEADING.match(line) or FENCE.match(line) or line.lstrip().startswith(">") or HR.match(line):
                break
            items[-1].append(line.strip())  # lazy paragraph continuation
            i += 1

        tag = "ol" if ordered else "ul"
        start_attr = f' start="{start}"' if ordered and start != 1 else ""
        rendered = []
        for item in items:
            while item and not item[-1].strip():
                item.pop()
            body = Renderer(with_toc=False).blocks(item)
            if not loose:
                body = re.sub(r"^<p>(.*?)</p>", r"\1", body, count=1, flags=re.S)
            rendered.append(f"<li>{body}</li>")
        out.append(f"<{tag}{start_attr}>" + "".join(rendered) + f"</{tag}>")
        return i

    def paragraph(self, lines, i, out) -> int:
        buf = []
        while i < len(lines):
            line = lines[i]
            if not line.strip() or FENCE.match(line) or HEADING.match(line) or HR.match(line) \
                    or line.lstrip().startswith(">") or (buf and LIST_ITEM.match(line)):
                break
            if buf and "|" in line and i + 1 < len(lines) and TABLE_SEP.match(lines[i + 1]):
                break
            buf.append(line.strip() if not line.endswith("  ") else line.lstrip())
            i += 1
        if not buf:  # a line no other rule took; emit it as text so the loop always advances
            buf.append(lines[i].strip())
            i += 1
        out.append(f"<p>{inline(chr(10).join(buf))}</p>")
        return i


def render(text: str, with_toc: bool = True) -> tuple[str, str]:
    """Return (html, toc_html) for a markdown string."""
    r = Renderer(with_toc=with_toc)
    body = r.convert(text)
    return body, r.toc_html()
