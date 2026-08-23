"""One-off: does the report editor now find reception 54800's captures?

The Insert Captured Image button reported "This report is not linked to a
study" on the floor. Cause: a report opened from the Reception Data tab
carries a RECEPTION record (receptionId, nationalCode, patient sub-dict) with
NO StudyInstanceUID, while captures on disk are keyed by study UID.

This replays the real reception shapes through `resolve_study_uids` against
the LIVE database and reports what the picker would show.

Run:  .venv\\Scripts\\python.exe tools\\analysis\\oneoff\\verify_report_study_resolution_2026_08_18.py
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))

OUT = Path(__file__).with_name("_report_study_resolution_out.txt")
LINES: list[str] = []
FAILS: list[str] = []


def say(msg=""):
    LINES.append(str(msg))
    OUT.write_text("\n".join(LINES), encoding="utf-8")
    try:
        sys.__stdout__.write(str(msg) + "\n")
        sys.__stdout__.flush()
    except Exception:
        pass


def check(label, ok, detail=""):
    say(f"  [{'PASS' if ok else 'FAIL'}] {label}{(' - ' + detail) if detail else ''}")
    if not ok:
        FAILS.append(label)


from modules.ai_imaging.ai_module_ui.service_tab.widgets.report_capture_images import (  # noqa: E402
    candidate_patient_ids, list_captured_images_for_studies, resolve_study_uids,
    study_uids_for_patient_id,
)

# The shape reception_data_tab passes as `self.current_data`.
RECEPTION_54800 = {
    "_id": "68a1f0c0deadbeef",
    "receptionId": "54800",
    "nationalCode": "0046922229",
    "patient": {"Name": "پوریا مظاهری فر", "NationalID": "0046922229"},
    "status": "pending",
}

say("1. WHAT THE OLD CODE SAW")
old = str(RECEPTION_54800.get("studyUID") or RECEPTION_54800.get("study_uid") or "")
check("the reception really has no study UID (this was the bug)", old == "",
      f"studyUID={old!r} -> 'not linked to a study'")

say("\n2. CANDIDATE IDENTIFIERS")
say(f"   {candidate_patient_ids(RECEPTION_54800)}")

say("\n3. RESOLUTION AGAINST THE LIVE DB")
uids = resolve_study_uids(RECEPTION_54800)
say(f"   resolved: {uids}")
check("reception 54800 now resolves to at least one study", bool(uids))

say("\n4. WHAT THE PICKER WOULD SHOW")
entries = list_captured_images_for_studies(uids)
say(f"   {len(entries)} captured image(s)")
for uid, path in entries:
    try:
        kb = path.stat().st_size / 1024.0
    except OSError:
        kb = -1
    say(f"      {path.name}   ({kb:.0f} KB)   study …{uid[-14:]}")
check("the picker would list at least one capture for 54800", bool(entries))

say("\n5. AN EXPLICIT STUDY UID STILL WINS (no regression)")
explicit = {"studyUID": "1.2.3.EXPLICIT", "receptionId": "54800"}
check("explicit studyUID short-circuits the DB lookup",
      resolve_study_uids(explicit) == ["1.2.3.EXPLICIT"],
      str(resolve_study_uids(explicit)))

say("\n6. AN UNKNOWN PATIENT RESOLVES TO NOTHING (no cross-patient leak)")
unknown = {"receptionId": "no-such-patient-99999"}
check("an unmatched reception yields []", resolve_study_uids(unknown) == [])

say("\n7. THE KILL SWITCH")
import os
os.environ["AIPACS_REPORT_IMAGE_DB_LOOKUP"] = "0"
check("AIPACS_REPORT_IMAGE_DB_LOOKUP=0 restores the old behaviour",
      resolve_study_uids(RECEPTION_54800) == [])
os.environ.pop("AIPACS_REPORT_IMAGE_DB_LOOKUP", None)

say("\n8. SPOT-CHECK OTHER PATIENTS WITH CAPTURES")
for pid in ("49094", "45857", "44081"):
    got = study_uids_for_patient_id(pid)
    n = len(list_captured_images_for_studies(got))
    say(f"   patient {pid}: {len(got)} study(ies), {n} capture(s)")

say("\n" + "=" * 66)
if FAILS:
    say(f"FAILED ({len(FAILS)}):")
    for f in FAILS:
        say(f"  - {f}")
    sys.exit(1)
say("All resolution checks passed.")
