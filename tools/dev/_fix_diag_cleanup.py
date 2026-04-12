"""Remove DIAG-WHEEL-ERROR remnant from _vw_scroll.py"""
import os

path = os.path.join(
    os.path.dirname(__file__), "..", "..",
    "PacsClient", "pacs", "patient_tab", "ui", "patient_ui",
    "vtk_widget", "_vw_scroll.py",
)
path = os.path.normpath(path)

with open(path, "r", encoding="utf-8") as f:
    lines = f.readlines()

# Find and remove lines 1089-1091 (0-indexed: 1088-1090)
# Line 1089: comment "# ... Even on error..."
# Line 1090: print(f"[DIAG-WHEEL-ERROR]...")
# Line 1091: import traceback; traceback.print_exc()
new_lines = []
skip_next = 0
for i, line in enumerate(lines):
    if skip_next > 0:
        skip_next -= 1
        continue
    if '[DIAG-WHEEL-ERROR]' in line:
        # Also remove the comment line before it (if it's the "Even on error" comment)
        if new_lines and 'Even on error' in new_lines[-1]:
            new_lines.pop()
        # Skip this line and the next (traceback.print_exc())
        skip_next = 1
        continue
    new_lines.append(line)

with open(path, "w", encoding="utf-8") as f:
    f.writelines(new_lines)

print(f"Done. Removed DIAG lines. New line count: {len(new_lines)} (was {len(lines)})")
