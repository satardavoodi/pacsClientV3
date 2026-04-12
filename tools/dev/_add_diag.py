"""Add diagnostic print to the exception handler in wheelEvent."""
import pathlib
p = pathlib.Path(r"c:\AI-Pacs codes\aipacs-pydicom2d\PacsClient\pacs\patient_tab\ui\patient_ui\vtk_widget\_vw_scroll.py")
content = p.read_text(encoding="utf-8")

old = '            logger.warning(f"[WHEEL] Exception (consuming to prevent zoom): {e}")\n            event.accept()\n\n    def keyPressEvent'
new = '            print(f"[DIAG-WHEEL-ERROR] {e}", flush=True)\n            import traceback; traceback.print_exc()\n            logger.warning(f"[WHEEL] Exception (consuming to prevent zoom): {e}")\n            event.accept()\n\n    def keyPressEvent'

assert old in content, "NOT FOUND"
content = content.replace(old, new, 1)
p.write_text(content, encoding="utf-8")
print("OK - added error diagnostic")
