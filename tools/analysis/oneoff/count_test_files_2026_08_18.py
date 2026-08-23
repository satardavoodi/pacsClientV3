"""One-off: count test files / domain folders under tests/code.

`tests/INDEX_BY_GUARD.md` claims its cumulative numbers are "counted directly,
not from the dashboard" — this is what does the counting, so the claim stays
true when the numbers are refreshed.

Run:  .venv\\Scripts\\python.exe tools\\analysis\\oneoff\\count_test_files_2026_08_18.py
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3] / "tests" / "code"

def domain(p: Path) -> str:
    parts = p.parent.relative_to(ROOT).parts
    return parts[0] if parts else ""


files = sorted(p for p in ROOT.rglob("test_*.py") if p.is_file())
folders = sorted({d for d in map(domain, files) if d})

print(f"tests/code root: {ROOT}")
print(f"test_*.py files : {len(files)}")
print(f"domain folders  : {len(folders)}")
print()
for name in folders:
    n = sum(1 for p in files if domain(p) == name)
    print(f"  {n:4d}  {name}")

loose = [p for p in files if p.parent == ROOT]
if loose:
    print(f"\n  {len(loose):4d}  <directly under tests/code>")

catalog = ROOT.parents[1] / "docs" / "plans" / "architecture" / "REGRESSION_CATALOG.md"
rows = re.findall(r"^\| 20\d\d-\d\d-\d\d \|", catalog.read_text(encoding="utf-8"), re.M)
print(f"\nregression catalog rows: {len(rows)}")
