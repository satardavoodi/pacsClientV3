"""Count lines in all Python files and report those with 2000+ lines."""
import os

results = []
skip_dirs = {'backups', '.venv', '__pycache__', '.git', 'node_modules', 'output'}

for root, dirs, files in os.walk('.'):
    dirs[:] = [d for d in dirs if d not in skip_dirs]
    for f in files:
        if not f.endswith('.py'):
            continue
        path = os.path.join(root, f)
        try:
            with open(path, 'r', encoding='utf-8', errors='ignore') as fh:
                lines = sum(1 for _ in fh)
            if lines >= 2000:
                results.append((lines, path))
        except Exception:
            pass

results.sort(reverse=True)
print(f"{'Lines':>7}  {'File'}")
print("-" * 80)
for lc, path in results:
    print(f"{lc:7d}  {path}")
print(f"\n--- Total: {len(results)} files with 2000+ lines ---")
