"""One-off: is test_first_batch_then_scroll_loads_rest failing because of the
2026-08-21 streamer change, or was it already failing at HEAD?

Runs the test module's own exec-the-source harness against the HEAD copy of
patient_table_widget.py by pointing its _TABLE constant at that copy.
"""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(r"E:\ai-pacs\ai-pacs codes\ai-pacs beta version")
REL = "PacsClient/pacs/workstation_ui/home_ui/patient_table_widget.py"
sys.path.insert(0, str(ROOT))


def main():
    head = subprocess.run(
        ["git", "show", "HEAD:" + REL], cwd=str(ROOT),
        capture_output=True, text=True, encoding="utf-8", errors="replace")
    if head.returncode != 0:
        print("git show failed:", head.stderr[:500])
        return 1
    tmp = Path(tempfile.gettempdir()) / "patient_table_widget_HEAD.py"
    tmp.write_text(head.stdout, encoding="utf-8")

    sys.path.insert(0, str(ROOT / "tests" / "code" / "system"))
    import importlib
    mod = importlib.import_module("test_local_search_progressive")

    for label, table_path in (("HEAD", tmp), ("WORKING", ROOT / REL)):
        mod._TABLE = table_path
        inst = mod._make_inst()
        rendered = []

        def render_one(item):
            rendered.append(item)
            inst.results_table._rows += 1
            return True

        inst.load_progressive([f"p{i}" for i in range(250)], render_one,
                              batch_size=100)
        print("%-8s first-batch rows rendered = %d  (test asserts 100)"
              % (label, len(rendered)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
