"""Guard: the reception SERVICES cache (2026-08-08).

The reception panel's "Services (N)" is the only place in AI-PACS that knows what the
patient was actually BOOKED for. It is the strongest single input for EchoMind's region
gating — DICOM states laterality in 18% of studies, and a body part alone cannot tell
"CT chest" from "CT angiography of the chest" — and until now it arrived from the
reception API, lived in one widget's `current_data`, and vanished with the widget.

Two things are load-bearing:

  1. The payload is stored VERBATIM. It is not our schema; normalising it into columns
     would start losing fields the first time reception changed one.
  2. A read never raises. A consumer asking "what was this booked as?" must be able to
     accept "we do not know" — the gate falls back to the full prompt, which is safe.
"""

import os
import sys

import pytest

_THIS = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.normpath(os.path.join(_THIS, "..", "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from database import ai_reception_db as rdb

PID = "__test_services__"

#: Real shape, from the live reception payload for study 53516.
SERVICES = [
    {"Service": "سی تی اسکن قفسه سینه با و بدون کنتراست", "Qty": 1, "ServiceGroup": "سی تی اسکن"},
    {"Service": "سی تی اسکن شکم و لگن با و بدون تزریق", "Qty": 2, "ServiceGroup": "سی تی اسکن"},
]


@pytest.fixture(autouse=True)
def _clean():
    yield
    try:
        from database._pool import get_db_connection
        with get_db_connection() as conn:
            conn.cursor().execute(
                "DELETE FROM ai_reception_services WHERE patient_id LIKE '__test%'")
            conn.commit()
    except Exception:
        pass


def test_services_round_trip_verbatim():
    """Persian text, quantities and group names must survive unchanged — the gate reads
    the service TEXT, so a mangled string is a silently wrong region."""
    assert rdb.ai_save_reception_services(PID, SERVICES) == 2
    assert rdb.ai_get_reception_services(PID) == SERVICES


def test_unknown_fields_are_not_dropped():
    """Reception owns this payload. A column-per-field schema would lose whatever they
    add next — including, one day, the service code itself."""
    payload = [{"Service": "x", "Qty": 1, "ServiceGroup": "g",
                "ServiceCode": "701125", "SomethingNew": {"a": [1, 2]}}]
    rdb.ai_save_reception_services(PID, payload)
    assert rdb.ai_get_reception_services(PID) == payload


def test_last_write_wins():
    rdb.ai_save_reception_services(PID, SERVICES)
    rdb.ai_save_reception_services(PID, [{"Service": "only this one"}])
    assert rdb.ai_get_reception_services(PID) == [{"Service": "only this one"}]


def test_an_empty_write_is_refused_and_leaves_the_row_alone():
    """A reception fetch that returns no services must not erase what we already know."""
    rdb.ai_save_reception_services(PID, SERVICES)
    assert rdb.ai_save_reception_services(PID, []) == 0
    assert rdb.ai_save_reception_services(PID, None) == 0
    assert rdb.ai_get_reception_services(PID) == SERVICES


def test_a_missing_patient_id_is_refused():
    assert rdb.ai_save_reception_services("", SERVICES) == 0
    assert rdb.ai_save_reception_services(None, SERVICES) == 0


def test_reading_an_unknown_patient_is_not_an_error():
    assert rdb.ai_get_reception_services("__test_never_seen__") == []
    assert rdb.ai_get_reception_services("") == []
    assert rdb.ai_get_reception_services(None) == []


def test_non_dict_entries_are_dropped_not_stored():
    rdb.ai_save_reception_services(PID, ["a string", None, {"Service": "real"}])
    assert rdb.ai_get_reception_services(PID) == [{"Service": "real"}]


def test_the_names_reach_pacsclient_utils():
    """PacsClient.utils imports these EAGERLY. A name that exists in the db module but
    not in the re-export chain breaks `import PacsClient.utils` — and that import is
    what the whole application starts with."""
    import PacsClient.utils as U
    assert hasattr(U, "ai_save_reception_services")
    assert hasattr(U, "ai_get_reception_services")
