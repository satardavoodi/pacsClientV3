"""Guard: the reception fetch happens while the physician dictates (2026-08-08).

Recording and transcription are the one stretch of an EchoMind session where the
network is idle and nobody is waiting on us. Fetching the reception record there means
the service list — the strongest input the region gate will have — is already cached by
the time the report chat is minted, instead of the metadata card reading "not detected"
until somebody opens the reception tab.

THE PROPERTY THAT MATTERS MOST is negative: a reception server that is down, slow,
misconfigured or absent must be **indistinguishable, from the composer's side, from one
that was never contacted**. Recording starts an audio stream; nothing in this feature
may delay, block or break that.

Every test here is offline. `fetch_patient_record` is monkeypatched — a test suite that
can reach the reception server is a test suite that fails on the train.
"""

import os
import sys
import threading
import time

import pytest

_THIS = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.normpath(os.path.join(_THIS, "..", "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from modules.EchoMind import reception_prefetch as rp
from modules.network import reception_api_config as rc

PID = "__test_prefetch__"
SERVICES = [{"Service": "سی تی اسکن قفسه سینه", "Qty": 1, "ServiceGroup": "سی تی اسکن"}]


def _clear(pid=PID):
    try:
        from database._pool import get_db_connection
        with get_db_connection() as conn:
            conn.cursor().execute(
                "DELETE FROM ai_reception_services WHERE patient_id LIKE '__test%'")
            conn.commit()
    except Exception:
        pass
    rp._inflight.discard(pid)


@pytest.fixture(autouse=True)
def _isolated(monkeypatch):
    """No test may touch the network."""
    monkeypatch.setattr(rc, "fetch_patient_record",
                        lambda *a, **k: pytest.fail("a test reached the network"))
    _clear()
    yield
    _clear()


def _serve(monkeypatch, record):
    monkeypatch.setattr(rc, "fetch_patient_record", lambda *a, **k: record)


# ── the negative property: it cannot hurt the voice path ────────────────────

def test_a_failing_fetch_is_swallowed_and_still_reports_started(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("reception is on fire")
    monkeypatch.setattr(rc, "fetch_patient_record", boom)
    assert rp.prefetch(patient_id=PID, max_age_s=0, blocking=True) is True
    assert rp._inflight == set() or PID not in rp._inflight


def test_the_in_flight_marker_is_released_even_when_the_fetch_raises(monkeypatch):
    """Otherwise one failed dictation poisons every later one for that patient."""
    monkeypatch.setattr(rc, "fetch_patient_record",
                        lambda *a, **k: (_ for _ in ()).throw(OSError("refused")))
    rp.prefetch(patient_id=PID, max_age_s=0, blocking=True)
    assert PID not in rp._inflight
    _serve(monkeypatch, {"services": SERVICES})
    assert rp.prefetch(patient_id=PID, max_age_s=0, blocking=True) is True


def test_the_background_thread_is_a_daemon(monkeypatch):
    """A reception server that never answers must not hold the workstation open at
    shutdown."""
    seen = {}
    real = threading.Thread

    class Spy(real):
        def __init__(self, *a, **k):
            seen.update(k)
            super().__init__(*a, **k)

    _serve(monkeypatch, {"services": SERVICES})
    monkeypatch.setattr(rp.threading, "Thread", Spy)
    rp.prefetch(patient_id=PID, max_age_s=0)
    assert seen.get("daemon") is True
    time.sleep(0.2)


def test_prefetch_returns_immediately(monkeypatch):
    """It is called on the UI thread while an audio stream is being opened."""
    def slow(*a, **k):
        time.sleep(1.5)
        return {"services": SERVICES}
    monkeypatch.setattr(rc, "fetch_patient_record", slow)
    t0 = time.perf_counter()
    rp.prefetch(patient_id=PID, max_age_s=0)
    assert (time.perf_counter() - t0) < 0.3


def test_the_timeout_is_short_enough_to_matter():
    """8 s, not the reception tab's 30: this runs while somebody is speaking."""
    assert 0 < rp.FETCH_TIMEOUT_S <= 10


# ── it does not stampede ─────────────────────────────────────────────────────

def test_a_fresh_cache_short_circuits(monkeypatch):
    """Re-recording four times in a minute must cost reception one request, not four."""
    _serve(monkeypatch, {"services": SERVICES})
    assert rp.prefetch(patient_id=PID, max_age_s=0, blocking=True) is True
    assert rp.is_fresh(PID, 900) is True
    monkeypatch.setattr(rc, "fetch_patient_record",
                        lambda *a, **k: pytest.fail("refetched a fresh cache"))
    assert rp.prefetch(patient_id=PID, max_age_s=900) is False


def test_a_stale_cache_does_refetch(monkeypatch):
    _serve(monkeypatch, {"services": SERVICES})
    rp.prefetch(patient_id=PID, max_age_s=0, blocking=True)
    assert rp.prefetch(patient_id=PID, max_age_s=0, blocking=True) is True


def test_only_one_fetch_per_patient_at_a_time(monkeypatch):
    _serve(monkeypatch, {"services": SERVICES})
    rp._inflight.add(PID)
    try:
        assert rp.prefetch(patient_id=PID, max_age_s=0) is False
    finally:
        rp._inflight.discard(PID)


# ── what it stores ───────────────────────────────────────────────────────────

def test_services_are_cached_from_the_response(monkeypatch):
    _serve(monkeypatch, {"services": SERVICES, "studyUID": "1.2.3"})
    assert rp.fetch_and_cache(PID) == 1
    from PacsClient.utils import ai_get_reception_services
    assert ai_get_reception_services(PID) == SERVICES


def test_a_response_with_no_services_does_not_erase_a_good_cache(monkeypatch):
    """THE dangerous case. A reception hiccup that returns an empty list must not
    delete a service list we already had — an empty write is 'no news', not 'none'."""
    _serve(monkeypatch, {"services": SERVICES})
    rp.fetch_and_cache(PID)
    _serve(monkeypatch, {"services": []})
    assert rp.fetch_and_cache(PID) == 0
    from PacsClient.utils import ai_get_reception_services
    assert ai_get_reception_services(PID) == SERVICES


def test_a_null_response_stores_nothing(monkeypatch):
    _serve(monkeypatch, None)
    assert rp.fetch_and_cache(PID) == 0


def test_a_junk_response_stores_nothing(monkeypatch):
    for junk in ("a string", [1, 2], 42):
        _serve(monkeypatch, junk)
        assert rp.fetch_and_cache(PID) == 0


# ── resolution ───────────────────────────────────────────────────────────────

def test_unresolvable_input_is_silent():
    assert rp.prefetch() is False
    assert rp.prefetch(study_uid="9.9.9.not.a.study") is False
    assert rp.resolve_patient_id(None) is None
    assert rp.resolve_patient_id("") is None
    assert rp.fetch_and_cache("") == 0


def test_cache_age_of_an_unknown_patient_is_none():
    assert rp.cache_age_seconds("__test_never_seen__") is None
    assert rp.is_fresh("__test_never_seen__") is False


# ── one endpoint definition ──────────────────────────────────────────────────

def test_the_endpoint_is_defined_once():
    """The reception tab's QThread builds this path too. A silent divergence would
    leave one caller quietly fetching a 404 while the other worked."""
    import io
    worker = io.open(os.path.join(
        _ROOT, "modules", "ai_imaging", "ai_module_ui", "service_tab",
        "reception_data_service.py"), encoding="utf-8-sig").read()
    assert "/api/pacs/patients/" in rc.PATIENT_ENDPOINT_TEMPLATE
    assert "/api/pacs/patients/" in worker, (
        "the reception tab's URL changed; update PATIENT_ENDPOINT_TEMPLATE with it"
    )


def test_an_unconfigured_reception_endpoint_is_not_an_error(monkeypatch):
    """There is deliberately no hard-coded host, so an unconfigured install must
    resolve to nothing rather than to somebody else's server."""
    monkeypatch.setattr(rc, "get_reception_api_base_url", lambda *a, **k: "")
    assert rc.build_patient_url("53516") == ""
    monkeypatch.undo()


def test_no_patient_id_means_no_url():
    assert rc.build_patient_url("") == ""
    assert rc.build_patient_url(None) == ""


# ── the wiring ───────────────────────────────────────────────────────────────

def _read(*parts):
    import io
    with io.open(os.path.join(_ROOT, *parts), encoding="utf-8-sig") as fh:
        return fh.read()


def test_the_composer_announces_that_recording_started():
    src = _read("modules", "EchoMind", "viewer_chat", "ai_chat_widgets.py")
    assert "recordingStarted = Signal()" in src
    i = src.index("def _start_record")
    emit = src.index("self.recordingStarted.emit()")
    assert emit > i, "the signal is not emitted from _start_record"
    assert emit < src.index("sd.InputStream"), (
        "emitted after the audio stream is opened — the idle window starts earlier"
    )
    seg = src[emit - 120:emit + 120]
    assert "try:" in seg and "except Exception" in seg, (
        "an unguarded emit means a listener's exception aborts the recording"
    )


def test_the_page_listens_and_transcription_warms_it_too():
    src = _read("modules", "EchoMind", "viewer_chat", "ai_chat_pages.py")
    assert "self.composer.recordingStarted.connect(self._prefetch_reception)" in src
    assert "self._prefetch_reception()" in src, (
        "an audio file dropped into the composer never passes through _start_record"
    )


def test_the_page_hook_is_swallowed():
    import ast
    src = _read("modules", "EchoMind", "viewer_chat", "ai_chat_pages.py")
    lines = src.split("\n")
    fn = next(n for n in ast.walk(ast.parse(src))
              if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
              and n.name == "_prefetch_reception")
    body = "\n".join(lines[fn.lineno - 1:fn.end_lineno])
    assert "try:" in body and "except Exception" in body
    assert "blocking" not in body, "production must never block the UI thread on this"


def test_the_card_is_refreshed_once_the_transcript_lands():
    """The only moment the physician sees Service fill itself in without switching
    chats: the prefetch finished during the dictation, so re-seed from the warm cache."""
    import ast
    src = _read("modules", "EchoMind", "viewer_chat", "ai_chat_pages.py")
    lines = src.split("\n")
    fn = next(n for n in ast.walk(ast.parse(src))
              if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
              and n.name == "_persist_transcribe")
    body = "\n".join(lines[fn.lineno - 1:fn.end_lineno])
    assert "_seed_session_metadata" in body and "_sync_metadata_card" in body
    assert "try:" in body and "except Exception" in body, (
        "a metadata refresh must not be able to lose a transcript"
    )
