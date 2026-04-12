"""Scan for large Python files (>=800 lines), excluding backups/venv/builder."""
import os

results = []
for root, dirs, files in os.walk('.'):
    dirs[:] = [d for d in dirs if d not in [
        'backups', '.venv', '__pycache__', '.git', 'node_modules', 'builder',
        'external', 'generated-files', 'graphics_runtime', 'hooks',
    ]]
    for f in files:
        if f.endswith('.py'):
            path = os.path.join(root, f)
            try:
                with open(path, 'r', encoding='utf-8', errors='ignore') as fh:
                    lines = sum(1 for _ in fh)
                if lines >= 800:
                    results.append((lines, path))
            except Exception:
                pass

results.sort(reverse=True)
for lc, path in results:
    flag = 'CRITICAL' if lc >= 2000 else 'LARGE' if lc >= 1000 else 'MEDIUM'
    print(f'{lc:6d}  [{flag:8s}]  {path}')
print(f'--- Total: {len(results)} files >= 800 lines')
print(f'    Critical (>=2000): {sum(1 for l,_ in results if l >= 2000)}')
print(f'    Large (>=1000):    {sum(1 for l,_ in results if 1000 <= l < 2000)}')
print(f'    Medium (>=800):    {sum(1 for l,_ in results if 800 <= l < 1000)}')
