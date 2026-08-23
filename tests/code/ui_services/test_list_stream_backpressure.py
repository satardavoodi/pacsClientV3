"""Guards for the 2026-08-21 import-freeze fix (Local list streamer).

MEASURED (user_data/logs/app.log, 2026-08-21 13:50:03–13:50:16): a single
background batch of the patient-table streamer blocked the GUI thread for
13.0 s. 104 of the 137 main-thread stall samples in that window were innermost
in pathlib ``stat``/``iterdir``, reached through
``render_one -> _resolve_renderable_study_path``.

OPT-50 had already moved that path resolution to a worker thread, but kept an
inline fallback for "rows the worker has not reached yet". During an import the
worker cannot outrun the 40-rows-per-50 ms streamer (same disk, contended by the
import writer and by AV scanning of the new files), so the streamer overtook it
and every overtaken row paid its blocking disk I/O on the GUI thread.

These guards pin the two corrections:
  * back-pressure — a row the worker has not resolved ENDS the batch instead of
    being resolved inline;
  * a per-batch wall-clock budget — a batch stops rather than outlasting a frame.
plus the forward-progress escape hatch, the kill switches, and the positive-only
path memo.
"""
import sys
import textwrap
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

_TABLE = (_ROOT / "PacsClient" / "pacs" / "workstation_ui" / "home_ui"
          / "patient_table_widget.py")
_SVC = (_ROOT / "PacsClient" / "pacs" / "workstation_ui" / "home_ui"
        / "home_search_service.py")


# ─────────────────── exec-the-source harness (no Qt needed) ───────────────

def _build_stub_class():
    src = _TABLE.read_text(encoding="utf-8", errors="ignore")
    start = src.index("    _PROGRESSIVE_BATCH = 100")
    end = src.index("    def _on_report_status_clicked", start)
    block = textwrap.dedent(src[start:end]).rstrip() + "\n"

    class _Sig:
        def __init__(self, outer):
            self._outer = outer

        def connect(self, fn):
            self._outer._cb = fn

    class _ScrollBar:
        def __init__(self):
            self._cb = None

        @property
        def valueChanged(self):
            return _Sig(self)

        def maximum(self):
            return 1000

    class _Table:
        def __init__(self):
            self._rows = 0
            self._sb = _ScrollBar()

        def verticalScrollBar(self):
            return self._sb

        def rowCount(self):
            return self._rows

    class _Label:
        def __init__(self):
            self.text = ""
            self.set_text_calls = 0

        def setPixmap(self, *_a):
            pass

        def setText(self, t):
            self.text = t
            self.set_text_calls += 1

        def setStyleSheet(self, *_a):
            pass

    class _Qta:
        class _Icon:
            def pixmap(self, *_a):
                return None

        def icon(self, *_a, **_k):
            return _Qta._Icon()

    ns = {"qta": _Qta()}
    exec("class _H:\n" + textwrap.indent(block, "    "), ns)   # noqa: S102
    return ns["_H"], _Table, _Label


def _inst():
    H, Table, Label = _build_stub_class()
    obj = H()
    obj.results_table = Table()
    obj.results_count_label = Label()
    obj.normal_summary_calls = 0
    obj.begin_bulk_insert = lambda: None
    obj.end_bulk_insert = lambda: None
    obj._update_results_count = lambda: setattr(
        obj, "normal_summary_calls", obj.normal_summary_calls + 1)
    return obj


def _recorder(inst):
    rendered = []

    def render_one(item):
        rendered.append(item)
        inst.results_table._rows += 1
        return True

    return rendered, render_one


# ───────────────────────────── back-pressure ──────────────────────────────

def test_unresolved_rows_are_not_rendered_on_the_gui_thread():
    """The core fix: a row the worker has not reached must NOT be rendered."""
    inst = _inst()
    rendered, render_one = _recorder(inst)
    items = [{"i": i} for i in range(50)]

    inst.load_progressive(items, render_one, initial_batch=40,
                          ready=lambda item: False)

    assert rendered == []
    assert inst._prog_cursor == 0


def test_stream_renders_exactly_the_resolved_prefix():
    inst = _inst()
    rendered, render_one = _recorder(inst)
    items = [{"i": i} for i in range(50)]
    for item in items[:12]:
        item["_ready"] = True

    inst.load_progressive(items, render_one, initial_batch=40,
                          ready=lambda item: item.get("_ready", False))

    assert [r["i"] for r in rendered] == list(range(12))
    assert inst._prog_cursor == 12


def test_stream_resumes_where_it_stopped_when_the_worker_catches_up():
    inst = _inst()
    rendered, render_one = _recorder(inst)
    items = [{"i": i} for i in range(50)]
    for item in items[:5]:
        item["_ready"] = True

    inst.load_progressive(items, render_one, initial_batch=40,
                          ready=lambda item: item.get("_ready", False))
    assert len(rendered) == 5

    for item in items:
        item["_ready"] = True
    inst._progressive_render_next(40)

    assert [r["i"] for r in rendered] == list(range(45))   # nothing lost, in order
    assert inst._prog_cursor == 45


def test_no_ready_predicate_keeps_the_legacy_behaviour():
    inst = _inst()
    rendered, render_one = _recorder(inst)
    inst.load_progressive([{"i": i} for i in range(30)], render_one,
                          initial_batch=30)
    assert len(rendered) == 30


def test_backpressure_kill_switch_restores_inline_rendering(monkeypatch):
    monkeypatch.setenv("AIPACS_LIST_STREAM_BACKPRESSURE", "0")
    inst = _inst()
    rendered, render_one = _recorder(inst)
    inst.load_progressive([{"i": i} for i in range(30)], render_one,
                          initial_batch=30, ready=lambda item: False)
    assert len(rendered) == 30
    assert inst._prog_ready is None


def test_a_broken_ready_predicate_never_stalls_the_stream():
    def boom(_item):
        raise RuntimeError("predicate exploded")

    inst = _inst()
    rendered, render_one = _recorder(inst)
    inst.load_progressive([{"i": i} for i in range(10)], render_one,
                          initial_batch=10, ready=boom)
    assert len(rendered) == 10


def test_idle_wait_does_not_rebuild_the_count_label():
    """A zero-render batch must not repaint the label at the timer's 20 Hz."""
    inst = _inst()
    _rendered, render_one = _recorder(inst)
    inst.load_progressive([{"i": i} for i in range(50)], render_one,
                          initial_batch=40, ready=lambda item: False)
    before = inst.results_count_label.set_text_calls
    inst._progressive_render_next(40)
    assert inst.results_count_label.set_text_calls == before


# ────────────────────── forward-progress escape hatch ─────────────────────

def test_a_permanently_unresolved_stream_still_makes_progress():
    """If the resolver future dies, force ONE row per batch rather than hang."""
    inst = _inst()
    rendered, render_one = _recorder(inst)
    inst._PROGRESSIVE_DEFER_FORCE_MS = 0          # "already waited long enough"
    inst.load_progressive([{"i": i} for i in range(50)], render_one,
                          initial_batch=40, ready=lambda item: False)
    assert len(rendered) == 1
    assert inst._prog_cursor == 1
    assert inst._prog_defer_forced == 1

    inst._progressive_render_next(40)
    assert len(rendered) == 2                      # one per batch, never zero


# ───────────────────────── per-batch time budget ──────────────────────────

def test_a_slow_batch_is_cut_at_the_wall_clock_budget(monkeypatch):
    monkeypatch.setenv("AIPACS_LIST_STREAM_BUDGET_MS", "20")
    import time as _t
    inst = _inst()
    rendered = []

    def slow_render(item):
        _t.sleep(0.012)                            # ~12 ms per row
        rendered.append(item)
        inst.results_table._rows += 1
        return True

    inst.load_progressive([{"i": i} for i in range(40)], slow_render,
                          initial_batch=40)

    assert 1 <= len(rendered) < 40, "the batch must stop at the budget"
    assert inst._prog_cursor == len(rendered)
    first_batch = len(rendered)

    inst._progressive_render_next(40)
    assert len(rendered) > first_batch, "the next tick must continue the stream"
    assert inst._prog_cursor == len(rendered)


def test_budget_zero_disables_the_cut(monkeypatch):
    monkeypatch.setenv("AIPACS_LIST_STREAM_BUDGET_MS", "0")
    import time as _t
    inst = _inst()
    rendered = []

    def slow_render(item):
        _t.sleep(0.002)
        rendered.append(item)
        inst.results_table._rows += 1
        return True

    inst.load_progressive([{"i": i} for i in range(30)], slow_render,
                          initial_batch=30)
    assert len(rendered) == 30


def test_budget_env_override_is_honoured(monkeypatch):
    H, _T, _L = _build_stub_class()
    monkeypatch.setenv("AIPACS_LIST_STREAM_BUDGET_MS", "7.5")
    assert H._progressive_budget_ms() == 7.5
    monkeypatch.setenv("AIPACS_LIST_STREAM_BUDGET_MS", "nonsense")
    assert H._progressive_budget_ms() == float(H._PROGRESSIVE_BUDGET_MS)


# ──────────────────── the readiness predicate + path memo ─────────────────

svc = pytest.importorskip(
    "PacsClient.pacs.workstation_ui.home_ui.home_search_service")


def test_row_paths_ready_tracks_the_worker_verdict():
    assert svc._row_paths_ready({"study_uid": "x"}) is False
    assert svc._row_paths_ready({"_aipacs_renderable": True}) is True
    assert svc._row_paths_ready({"_aipacs_renderable": False}) is True


def test_resolved_paths_are_memoised_instead_of_re_scanning(tmp_path):
    svc.clear_path_memo()
    study = tmp_path / "study"
    (study / "0").mkdir(parents=True)

    patient = {"study_uid": None, "study_path": str(study)}
    assert svc._resolve_renderable_study_path(patient) == str(study)

    # Remove the folder: a second resolve that still answers can ONLY have come
    # from the memo — i.e. the disk was not re-scanned.
    (study / "0").rmdir()
    study.rmdir()
    again = {"study_uid": None, "study_path": str(study)}
    assert svc._resolve_renderable_study_path(again) == str(study)
    svc.clear_path_memo()


def test_missing_studies_are_never_memoised(tmp_path):
    """A study that appears later must show up on the very next search."""
    svc.clear_path_memo()
    study = tmp_path / "later"
    patient = {"study_uid": None, "study_path": str(study)}
    assert svc._resolve_renderable_study_path(patient) is None

    (study / "0").mkdir(parents=True)
    assert svc._resolve_renderable_study_path(
        {"study_uid": None, "study_path": str(study)}) == str(study)
    svc.clear_path_memo()


def test_path_memo_kill_switch(tmp_path, monkeypatch):
    monkeypatch.setenv("AIPACS_LIST_PATH_MEMO", "0")
    svc.clear_path_memo()
    study = tmp_path / "nomemo"
    (study / "0").mkdir(parents=True)
    assert svc._resolve_renderable_study_path(
        {"study_uid": None, "study_path": str(study)}) == str(study)
    (study / "0").rmdir()
    study.rmdir()
    assert svc._resolve_renderable_study_path(
        {"study_uid": None, "study_path": str(study)}) is None


# ───────────────────────── source-wiring guards ───────────────────────────

def test_search_service_hands_the_table_a_readiness_predicate():
    body = _SVC.read_text(encoding="utf-8", errors="ignore")
    assert "def _row_paths_ready" in body
    assert "ready=_ready" in body, "load_progressive must receive the predicate"


def test_table_exposes_the_backpressure_api():
    body = _TABLE.read_text(encoding="utf-8", errors="ignore")
    assert "def _progressive_backpressure_enabled" in body
    assert "def _progressive_budget_ms" in body
    assert "_PROGRESSIVE_DEFER_FORCE_MS" in body
    assert "ready=None" in body, "load_progressive must accept a ready predicate"
