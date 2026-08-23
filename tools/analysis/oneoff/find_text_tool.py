"""Locate the viewer's TEXT annotation tool: button, handler, and paint path."""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
ROOTS = [ROOT / "PacsClient", ROOT / "modules"]
SKIP = {".venv", "site-packages", "__pycache__", "builder", "backups", "node_modules"}

PATTERNS = {
    "button/label": re.compile(r"""(["'])\s*(Text|TEXT|Add Text|متن)\s*\1"""),
    "tool-name":    re.compile(r"""["']text["']\s*[,:\)\]]"""),
    "def":          re.compile(r"^\s*def\s+\w*text\w*\s*\(", re.I),
    "annot":        re.compile(r"\btext_annot\w*|\bannot\w*_text\b|TextAnnotation|add_text\b", re.I),
    "qgraphicstext": re.compile(r"QGraphicsTextItem|QGraphicsSimpleTextItem|drawText\("),
    "inputdialog":  re.compile(r"QInputDialog\.getText|getMultiLineText"),
}


def files():
    for r in ROOTS:
        for p in r.rglob("*.py"):
            if any(s in p.parts for s in SKIP):
                continue
            yield p


hits: dict[str, list[str]] = {k: [] for k in PATTERNS}
for p in files():
    try:
        lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        continue
    for i, line in enumerate(lines, 1):
        for key, pat in PATTERNS.items():
            if pat.search(line):
                rel = p.relative_to(ROOT).as_posix()
                hits[key].append(f"{rel}:{i}: {line.strip()[:130]}")

for key in PATTERNS:
    rows = hits[key]
    print(f"\n===== {key}  ({len(rows)}) =====")
    for r in rows[:45]:
        print("  " + r)
    if len(rows) > 45:
        print(f"  ... +{len(rows) - 45} more")
