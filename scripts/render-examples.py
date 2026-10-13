"""Re-render the sample research site in examples/ and copy it to docs/ for GitHub Pages.

    python scripts/render-examples.py

Run this after changing the renderer or the sample dossier; a test fails if they drift.
"""
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
EXAMPLES = REPO / "examples"
RENDERER = REPO / "template" / ".claude" / "hooks" / "render_research.py"
PAGES = REPO / "docs"


def main() -> int:
    site = EXAMPLES / "research" / "site"
    if site.exists():
        shutil.rmtree(site)
    result = subprocess.run([sys.executable, str(RENDERER), "--root", str(EXAMPLES), "--all"])
    if result.returncode != 0:
        return result.returncode
    PAGES.mkdir(exist_ok=True)
    for old in PAGES.glob("*.html"):
        old.unlink()
    for page in site.glob("*.html"):
        shutil.copy2(page, PAGES / page.name)
    (PAGES / ".nojekyll").write_text("", encoding="utf-8")
    print(f"Rendered {len(list(site.glob('*.html')))} pages to {site} and copied them to {PAGES}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
