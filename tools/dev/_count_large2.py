"""Count lines in all project Python files (excluding third-party builds)."""
import os

results = []
skip_dirs = {
    'backups', '.venv', '__pycache__', '.git', 'node_modules', 'output',
    'build',  # skip MPR build artifacts
}
skip_path_fragments = [
    'NewMPR2Slicer',
    'slicer_custom_app',
    '.venv',
    'backups',
]

for root, dirs, files in os.walk('.'):
    # Skip entire subtrees
    dirs[:] = [
        d for d in dirs
        if d not in skip_dirs
        and not any(frag in root for frag in skip_path_fragments)
    ]
    if any(frag in root for frag in skip_path_fragments):
        continue

    for f in files:
        if not f.endswith('.py'):
            continue
        path = os.path.join(root, f)
        try:
            with open(path, 'r', encoding='utf-8', errors='ignore') as fh:
                lines = sum(1 for _ in fh)
            if lines >= 1500:
                results.append((lines, path))
        except Exception:
            pass

results.sort(reverse=True)
print(f"{'Lines':>7}  {'File'}")
print("-" * 100)
for lc, path in results:
    print(f"{lc:7d}  {path}")
print(f"\n--- Total: {len(results)} files with 1500+ lines (project code only) ---")
