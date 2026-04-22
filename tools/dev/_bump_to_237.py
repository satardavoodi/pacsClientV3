"""One-shot version bump 2.3.5 -> 2.3.7 (+ date)."""
from pathlib import Path
import glob

files = [
    'main.py', 'pyproject.toml', 'build_nuitka.py', 'README.md', 'docs/README.md',
    'builder/docs/WINDOWS_RELEASE_FLOW.md', 'builder/docs/INSTALLER_QA_CHECKLIST.md',
    'builder/plugin package/packages/module_package_feed.json',
]
files += glob.glob('builder/plugin package/packages/*/module_package.json')

for f in files:
    p = Path(f)
    if not p.exists():
        print('Missing:', f)
        continue
    c = p.read_text(encoding='utf-8')
    c2 = c.replace('2.3.5', '2.3.7').replace('2026-04-19', '2026-04-22')
    if c != c2:
        p.write_text(c2, encoding='utf-8')
        print('Updated:', f)
