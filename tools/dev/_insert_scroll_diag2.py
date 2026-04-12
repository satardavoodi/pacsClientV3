"""Insert FAST-SCROLL-0 diagnostic at wheelEvent entry in _vw_scroll.py."""
import pathlib

path = pathlib.Path(r"PacsClient\pacs\patient_tab\ui\patient_ui\vtk_widget\_vw_scroll.py")
lines = path.read_text(encoding="utf-8").splitlines(keepends=True)

inserted = False
for i, line in enumerate(lines):
    if "def wheelEvent(self, event):" in line and i > 850:
        # Find the docstring end (next line after multiline comment)
        # Insert after the docstring
        for j in range(i + 1, min(i + 10, len(lines))):
            if '"""' in lines[j] and j > i + 1:
                indent = "        "
                diag = indent + 'print(f"[FAST-SCROLL-0] VTKWidget.wheelEvent FIRED qt_bridge={self._qt_bridge_active} backend={getattr(self, \'_active_backend\', \'?\')}", flush=True)\n'
                lines.insert(j + 1, diag)
                inserted = True
                print(f"Inserted at line {j + 2}")
                break
            elif lines[j].strip().startswith('"""'):
                # single-line closing
                indent = "        "
                diag = indent + 'print(f"[FAST-SCROLL-0] VTKWidget.wheelEvent FIRED qt_bridge={self._qt_bridge_active} backend={getattr(self, \'_active_backend\', \'?\')}", flush=True)\n'
                lines.insert(j + 1, diag)
                inserted = True
                print(f"Inserted at line {j + 2}")
                break
        break

if inserted:
    path.write_text("".join(lines), encoding="utf-8")
    print("Done.")
else:
    print("Target not found!")
