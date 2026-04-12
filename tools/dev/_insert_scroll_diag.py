"""Insert FAST-SCROLL-4 diagnostic into _vw_scroll.py Qt bridge path."""
import pathlib

path = pathlib.Path(r"PacsClient\pacs\patient_tab\ui\patient_ui\vtk_widget\_vw_scroll.py")
lines = path.read_text(encoding="utf-8").splitlines(keepends=True)

inserted = False
for i, line in enumerate(lines):
    if "_fast = bool(_wheel or _stack_drag)" in line and i > 490:
        indent = "                "
        diag = indent + 'print(f"[FAST-SCROLL-4] set_slice({slice_index}) qt_bridge=True fast={_fast}", flush=True)\n'
        lines.insert(i + 1, diag)
        inserted = True
        print(f"Inserted at line {i + 2}")
        break

if inserted:
    path.write_text("".join(lines), encoding="utf-8")
    print("Done.")
else:
    print("Target line not found!")
