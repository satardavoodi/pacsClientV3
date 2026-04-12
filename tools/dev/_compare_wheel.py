"""
Compare original vs split wheelEvent — byte-for-byte.
Also test if the forwarding super() chain works at runtime.
"""
import sys, os, re, difflib

ROOT = r"c:\AI-Pacs codes\aipacs-pydicom2d"
BACKUP = os.path.join(ROOT, "PacsClient", "pacs", "patient_tab", "ui", "patient_ui", "widget_viewer.py.bak_phase5d")
SPLIT = os.path.join(ROOT, "PacsClient", "pacs", "patient_tab", "ui", "patient_ui", "vtk_widget", "_vw_scroll.py")
WIDGET = os.path.join(ROOT, "PacsClient", "pacs", "patient_tab", "ui", "patient_ui", "vtk_widget", "widget.py")

def extract_method(content, method_name):
    """Extract a full method body from source."""
    pattern = rf'^( +)def {method_name}\(self.*?\):'
    match = re.search(pattern, content, re.MULTILINE)
    if not match:
        return None, 0
    indent = len(match.group(1))
    start = match.start()
    lines = content[start:].split('\n')
    method_lines = [lines[0]]
    for line in lines[1:]:
        stripped = line.rstrip()
        if stripped == '':
            method_lines.append(line)
            continue
        line_indent = len(line) - len(line.lstrip())
        if line_indent <= indent and stripped:
            break
        method_lines.append(line)
    return '\n'.join(method_lines), len(method_lines)

with open(BACKUP, 'r', encoding='utf-8', errors='ignore') as f:
    backup_content = f.read()
with open(SPLIT, 'r', encoding='utf-8', errors='ignore') as f:
    split_content = f.read()
with open(WIDGET, 'r', encoding='utf-8', errors='ignore') as f:
    widget_content = f.read()

# Extract wheelEvent from backup and split
backup_wheel, backup_lines = extract_method(backup_content, 'wheelEvent')
split_wheel, split_lines = extract_method(split_content, 'wheelEvent')
widget_wheel, widget_lines = extract_method(widget_content, 'wheelEvent')

print(f"=== backup wheelEvent: {backup_lines} lines ===")
print(f"=== split  wheelEvent: {split_lines} lines ===")
print(f"=== widget wheelEvent: {widget_lines} lines ===")

# Show widget.py forwarding method
print(f"\n=== widget.py wheelEvent (forwarding method) ===")
print(widget_wheel)

# Diff backup vs split
print(f"\n=== DIFF: backup vs split wheelEvent ===")
backup_lines_list = (backup_wheel or '').split('\n')
split_lines_list = (split_wheel or '').split('\n')

diff = list(difflib.unified_diff(
    backup_lines_list, split_lines_list,
    fromfile='BACKUP', tofile='SPLIT',
    lineterm='', n=1
))
if diff:
    for line in diff[:100]:
        print(line)
else:
    print("  NO DIFFERENCES (identical)")

# ======================
# Check ALL methods in backup vs split
# ======================
print(f"\n\n=== COMPREHENSIVE METHOD CHECK ===")
# Extract all methods from backup VTKWidget class
backup_methods = set()
in_class = False
class_indent = 0
for line in backup_content.split('\n'):
    stripped = line.strip()
    if stripped.startswith('class VTKWidget('):
        in_class = True
        class_indent = len(line) - len(line.lstrip())
        continue
    if in_class:
        line_indent = len(line) - len(line.lstrip()) if line.strip() else 999
        if line_indent <= class_indent and line.strip() and not line.strip().startswith('#') and not line.strip().startswith('"""'):
            break
        m = re.match(r'\s+def (\w+)\(', line)
        if m:
            backup_methods.add(m.group(1))

# Extract all methods from split package
split_methods = set()
split_dir = os.path.join(ROOT, "PacsClient", "pacs", "patient_tab", "ui", "patient_ui", "vtk_widget")
for fname in os.listdir(split_dir):
    if not fname.endswith('.py'):
        continue
    fpath = os.path.join(split_dir, fname)
    with open(fpath, 'r', encoding='utf-8', errors='ignore') as f:
        for line in f:
            m = re.match(r'\s+def (\w+)\(', line)
            if m:
                split_methods.add(m.group(1))

missing = backup_methods - split_methods
extra = split_methods - backup_methods
print(f"  Backup methods: {len(backup_methods)}")
print(f"  Split methods:  {len(split_methods)}")
print(f"  MISSING from split: {len(missing)}")
if missing:
    for m in sorted(missing):
        print(f"    ❌ {m}")
print(f"  Extra in split: {len(extra)}")
if extra:
    for m in sorted(extra):
        print(f"    ➕ {m}")

# Check for super() calls in the split wheelEvent that might chain to QVTK
print(f"\n=== super() calls in split wheelEvent ===")
if split_wheel:
    for i, line in enumerate(split_wheel.split('\n')):
        if 'super()' in line:
            print(f"  Line {i}: {line.strip()}")
else:
    print("  (no split wheelEvent found)")

# Check for super() calls in widget.py wheelEvent
print(f"\n=== super() calls in widget.py wheelEvent ===")
if widget_wheel:
    for i, line in enumerate(widget_wheel.split('\n')):
        if 'super()' in line:
            print(f"  Line {i}: {line.strip()}")
