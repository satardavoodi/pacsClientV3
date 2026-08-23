"""One-off: prove tests/code/ui_services/test_gui_thread_disk_paths.py FAILS pre-fix.

Swaps the three touched source files for their HEAD versions, runs the new guard
file, then restores the working-tree versions in a finally block and verifies the
restore byte-for-byte.
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(r"E:\ai-pacs\ai-pacs codes\ai-pacs beta version")
RELS = [
    "PacsClient/pacs/patient_tab/utils/utils.py",
    "PacsClient/pacs/workstation_ui/home_ui/patient_table_widget.py",
    "PacsClient/pacs/workstation_ui/settings_ui/storage_cleanup_panel.py",
]
TEST = "tests/code/ui_services/test_gui_thread_disk_paths.py"


def head_bytes(rel):
    out = subprocess.run(["git", "show", "HEAD:" + rel], cwd=str(ROOT),
                         capture_output=True)
    if out.returncode != 0:
        raise SystemExit("git show failed for %s: %s" % (rel, out.stderr[:400]))
    return out.stdout


def main():
    working = {rel: (ROOT / rel).read_bytes() for rel in RELS}
    heads = {rel: head_bytes(rel) for rel in RELS}
    try:
        for rel in RELS:
            (ROOT / rel).write_bytes(heads[rel])
        print("== running the new guards against HEAD sources ==")
        proc = subprocess.run(
            [str(ROOT / ".venv" / "Scripts" / "python.exe"), "-m", "pytest",
             TEST, "-q", "-p", "no:debugging", "--no-header", "-p", "no:randomly",
             "--tb=no", "-p", "no:cacheprovider"],
            cwd=str(ROOT), capture_output=True, text=True,
            encoding="utf-8", errors="replace")
        tail = [ln for ln in proc.stdout.splitlines() if ln.strip()][-32:]
        print("\n".join(tail))
    finally:
        for rel in RELS:
            (ROOT / rel).write_bytes(working[rel])
        ok = all((ROOT / rel).read_bytes() == working[rel] for rel in RELS)
        print()
        print("working tree restored:", ok)
        if not ok:
            print("!! RESTORE FAILED — restore manually from git", file=sys.stderr)
            return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
