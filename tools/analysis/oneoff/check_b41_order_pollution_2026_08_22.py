"""One-off: are the 4 test_fast_viewer_pipeline b41 failures mine, or pre-existing
cross-test pollution from the run ORDER?

Runs the same ui_services -> system -> fast_viewer_pipeline order twice: once with
the working tree, once with the three 2026-08-22 files swapped for their HEAD
versions. Same result in both = not caused by the change.
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
ARGS = [
    "tests/code/ui_services", "tests/code/system",
    "tests/code/viewer/test_fast_viewer_pipeline.py",
]
PY = str(ROOT / ".venv" / "Scripts" / "python.exe")


def run(label):
    proc = subprocess.run(
        [PY, "-m", "pytest", *ARGS, "-q", "-p", "no:debugging", "--no-header",
         "-p", "no:randomly", "--tb=no", "-p", "no:cacheprovider"],
        cwd=str(ROOT), capture_output=True, text=True,
        encoding="utf-8", errors="replace")
    b41 = sorted(ln.split("::")[-1] for ln in proc.stdout.splitlines()
                 if ln.startswith("FAILED") and "b41" in ln)
    total = [ln for ln in proc.stdout.splitlines() if " passed" in ln]
    print("%-9s b41 failures: %d  %s" % (label, len(b41), total[-1] if total else "?"))
    for name in b41:
        print("            %s" % name)
    return set(b41)


def main():
    working = {rel: (ROOT / rel).read_bytes() for rel in RELS}
    with_fix = run("WORKING")
    try:
        for rel in RELS:
            out = subprocess.run(["git", "show", "HEAD:" + rel], cwd=str(ROOT),
                                 capture_output=True)
            if out.returncode != 0:
                raise SystemExit("git show failed: %s" % rel)
            (ROOT / rel).write_bytes(out.stdout)
        at_head = run("HEAD")
    finally:
        for rel in RELS:
            (ROOT / rel).write_bytes(working[rel])
        ok = all((ROOT / rel).read_bytes() == working[rel] for rel in RELS)
        print()
        print("working tree restored:", ok)
        if not ok:
            print("!! RESTORE FAILED", file=sys.stderr)
            return 2
    print()
    if with_fix == at_head:
        print("SAME in both -> the b41 failures are NOT caused by the 08-22 change.")
    else:
        print("DIFFERENT -> introduced by the change:", sorted(with_fix - at_head))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
