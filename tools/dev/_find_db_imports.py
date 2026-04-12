"""Find all files that import from database.core or database."""
import os
import re

results = []
skip = {'backups', '.venv', '__pycache__', '.git', 'NewMPR2Slicer', 'slicer_custom_app'}

for root, dirs, files in os.walk('.'):
    dirs[:] = [d for d in dirs if d not in skip and not any(s in root for s in skip)]
    for f in files:
        if not f.endswith('.py'):
            continue
        path = os.path.join(root, f)
        try:
            with open(path, 'r', encoding='utf-8', errors='ignore') as fh:
                content = fh.read()
        except:
            continue
        # Look for any import from database  
        if re.search(r'from\s+database[\.\s]|import\s+database', content):
            # Find the specific imports
            matches = re.findall(r'(?:from\s+database[.\w]*\s+import\s+[\w\s,*()\\]+|from\s+database\s+import\s+[\w\s,*()\\]+)', content)
            results.append((path, matches))

print(f"{'File':<80}  Imports from database")
print('-'*120)
for path, matches in sorted(results):
    print(f"\n{path}")
    for m in matches:
        print(f"  {m.strip()[:120]}")
print(f"\n--- Total: {len(results)} files import from database ---")
