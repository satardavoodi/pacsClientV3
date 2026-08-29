"""Are the 2 ui_services failures caused by the overlay fix? Measure, do not argue."""
import shutil, subprocess, sys, tempfile
from pathlib import Path
ROOT = Path(__file__).resolve().parents[3]
FILES = ["PacsClient/components/loading_overlay.py",
         "PacsClient/pacs/patient_tab/ui/patient_ui/vtk_widget/qt_fast_container.py"]
TESTS = ["tests/code/ui_services/test_report_assign_rendering.py::test_login_carries_the_user_identity_ids",
         "tests/code/ui_services/test_status_report_sorting.py::test_status_flags_are_stashed_on_the_widget_to_avoid_recompute"]

def run(label):
    p = subprocess.run([sys.executable, "-m", "pytest", *TESTS, "-q", "-p", "no:cacheprovider",
                        "--no-header", "-rf"], cwd=str(ROOT), capture_output=True)
    out = p.stdout.decode("utf-8", errors="replace")
    tail = [l for l in out.strip().splitlines() if "passed" in l or "failed" in l]
    print("%-14s %s" % (label, tail[-1] if tail else "(no summary)"))
    return {l.split("::")[-1].split()[0] for l in out.splitlines() if l.startswith("FAILED ")}

with_fix = run("WITH fix:")
tmp = Path(tempfile.mkdtemp(prefix="ui_services_delta_"))
baks = {}
for rel in FILES:
    baks[rel] = tmp / Path(rel).name
    shutil.copy2(ROOT / rel, baks[rel])
print("backups ->", tmp)
try:
    for rel in FILES:
        src = subprocess.run(["git", "show", f"HEAD:{rel}"], cwd=str(ROOT),
                             capture_output=True, check=True).stdout.decode("utf-8", "replace")
        (ROOT / rel).write_text(src, encoding="utf-8", newline="")
    without = run("WITHOUT fix:")
finally:
    for rel, b in baks.items():
        shutil.copy2(b, ROOT / rel)
    print("restored both files")

print("\nfailures WITH fix   :", sorted(with_fix))
print("failures WITHOUT fix:", sorted(without))
caused = with_fix - without
print("\nCAUSED BY THE FIX:", sorted(caused) if caused else "NONE - both pre-existing")
