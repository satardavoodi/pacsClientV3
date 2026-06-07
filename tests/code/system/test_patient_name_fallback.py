"""Guard: empty server PatientName must fall back to the patient ID (44982).

The US/DOC devices for 44982 sent an empty PatientName; the server returns
"" at the patient level and on every study. The home table ingestion now
repairs the DISPLAY name to "Patient <ID>" so the row and the tab opened
from it stay identifiable. Source-level guard (the mixin needs a full home
panel to instantiate; the repair is a self-contained block)."""

from pathlib import Path

SRC = (
    Path(__file__).resolve().parents[3]
    / "PacsClient" / "pacs" / "workstation_ui" / "home_ui" / "home_panel" / "_hp_search.py"
)


def test_empty_name_fallback_block_present():
    src = SRC.read_text(encoding="utf-8", errors="ignore")
    assert 'patient_name = f"Patient {_pid_str}"' in src
    # The repair must run right after extraction, before any consumer.
    extract_at = src.index("patient_name = patient.get('patient_name', 'N/A')")
    repair_at = src.index('patient_name = f"Patient {_pid_str}"')
    assert 0 < repair_at - extract_at < 1200


def test_fallback_logic_semantics():
    """Replicate the block's exact logic against the 44982 payload shapes."""
    def repair(patient_name, patient_id):
        if not str(patient_name or '').strip() or patient_name == 'N/A':
            _pid_str = str(patient_id or '').strip()
            if _pid_str and _pid_str != 'N/A':
                patient_name = f"Patient {_pid_str}"
        return patient_name

    assert repair("", "44982") == "Patient 44982"        # the live case
    assert repair(None, "44982") == "Patient 44982"
    assert repair("  ", "44982") == "Patient 44982"
    assert repair("N/A", "44982") == "Patient 44982"
    assert repair("DOE^JOHN", "44982") == "DOE^JOHN"     # real names untouched
    assert repair("", "") == ""                          # nothing to fall back to
    assert repair("", "N/A") == ""
