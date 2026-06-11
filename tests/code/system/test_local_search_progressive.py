"""Guards for progressive / lazy Local-Search loading (2026-06-09).

Local Search rendered ALL studies up front (per-row disk I/O + cell widgets on
the UI thread) → froze and didn't scale. Now the patient table renders the
first batch and lazy-loads the next batch on scroll-near-end, non-blocking,
keeping the total count visible. These guards exercise the batching/scroll
mechanics (exec'd from source against stubs — no heavy Qt widget) plus source
wiring of the search service.
"""
import sys
import textwrap
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

_TABLE = (_ROOT / "PacsClient" / "pacs" / "workstation_ui" / "home_ui"
          / "patient_table_widget.py")
_SVC = (_ROOT / "PacsClient" / "pacs" / "workstation_ui" / "home_ui"
        / "home_search_service.py")


def _no_comments(text):
    return "\n".join(line.split("#", 1)[0] for line in text.splitlines())


def _load_progressive_class():
    src = _TABLE.read_text(encoding="utf-8", errors="ignore")
    start = src.index("    _PROGRESSIVE_BATCH = 100")
    end = src.index("    def _on_report_status_clicked", start)
    block = textwrap.dedent(src[start:end]).rstrip() + "\n"

    class _StubScrollBar:
        def __init__(self):
            self._cb = None
            self._max = 1000

        class _Sig:
            def __init__(self, outer):
                self._outer = outer

            def connect(self, fn):
                self._outer._cb = fn

        @property
        def valueChanged(self):
            return _StubScrollBar._Sig(self)

        def maximum(self):
            return self._max

    class _StubTable:
        def __init__(self):
            self._rows = 0
            self._sb = _StubScrollBar()

        def verticalScrollBar(self):
            return self._sb

        def rowCount(self):
            return self._rows

    class _StubLabel:
        def __init__(self):
            self.text = ""

        def setPixmap(self, *_a):
            pass

        def setText(self, t):
            self.text = t

        def setStyleSheet(self, *_a):
            pass

    class _StubQtaIcon:
        def pixmap(self, *_a):
            return None

    class _StubQta:
        def icon(self, *_a, **_k):
            return _StubQtaIcon()

    ns = {"qta": _StubQta()}
    exec("class _H:\n" + textwrap.indent(block, "    "), ns)  # noqa: S102
    H = ns["_H"]

    # bind the collaborators the methods touch
    H._StubTable = _StubTable
    H._StubLabel = _StubLabel
    return H, _StubTable, _StubLabel


def _make_inst():
    H, StubTable, StubLabel = _load_progressive_class()
    inst = H()
    inst.results_table = StubTable()
    inst.results_count_label = StubLabel()
    inst._normal_summary_calls = 0

    def _begin():
        pass

    def _end():
        pass

    def _update_results_count():
        inst._normal_summary_calls += 1

    inst.begin_bulk_insert = _begin
    inst.end_bulk_insert = _end
    inst._update_results_count = _update_results_count
    return inst


def test_first_batch_then_scroll_loads_rest():
    inst = _make_inst()
    rendered = []

    def render_one(item):
        rendered.append(item)
        inst.results_table._rows += 1   # one row added
        return True

    items = [f"p{i}" for i in range(250)]
    inst.load_progressive(items, render_one, batch_size=100)

    # first batch rendered immediately, rest buffered
    assert len(rendered) == 100
    assert inst._prog_cursor == 100
    assert inst._prog_total == 250
    assert "Showing 100 of 250" in inst.results_count_label.text

    # scroll near the bottom → next batch
    sb = inst.results_table._sb
    sb._cb(sb.maximum())              # valueChanged(max)
    assert len(rendered) == 200
    assert "Showing 200 of 250" in inst.results_count_label.text

    # scroll again → final partial batch → done → normal summary
    sb._cb(sb.maximum())
    assert len(rendered) == 250
    assert inst._prog_cursor == 250
    assert inst._normal_summary_calls >= 1   # fell back to modality summary

    # further scrolls are no-ops (everything loaded)
    sb._cb(sb.maximum())
    assert len(rendered) == 250


def test_scroll_not_near_bottom_does_not_load():
    inst = _make_inst()
    rendered = []

    def render_one(item):
        rendered.append(item)
        inst.results_table._rows += 1
        return True

    inst.load_progressive([f"p{i}" for i in range(300)], render_one, batch_size=100)
    assert len(rendered) == 100
    sb = inst.results_table._sb
    sb._cb(10)   # nowhere near maximum(1000)
    assert len(rendered) == 100   # no extra load


def test_small_result_renders_in_one_batch():
    inst = _make_inst()
    rendered = []

    def render_one(item):
        rendered.append(item)
        inst.results_table._rows += 1
        return True

    inst.load_progressive([f"p{i}" for i in range(40)], render_one, batch_size=100)
    assert len(rendered) == 40
    assert inst._prog_cursor == 40
    # already complete → normal summary, no "Showing X of Y"
    assert inst._normal_summary_calls >= 1


# ───────────────────────── source-wiring guards ──────────────────────────

def test_table_has_progressive_api_and_clear_resets():
    body = _no_comments(_TABLE.read_text(encoding="utf-8", errors="ignore"))
    assert "def load_progressive" in body
    assert "def _progressive_render_next" in body
    assert "def _on_progressive_scroll" in body
    # clear_table resets the buffer so a stale scroll can't render old rows
    ct = body[body.index("def clear_table"):body.index("def clear_table") + 700]
    assert "_prog_items = []" in ct and "_prog_total = 0" in ct


def test_search_service_uses_progressive_in_display_order():
    body = _no_comments(_SVC.read_text(encoding="utf-8", errors="ignore"))
    assert "def _progressive_local_enabled" in body
    assert "load_progressive(" in body
    # buffer reversed to date-descending (newest-first) display order
    assert "list(reversed(patients))" in body
    # gated by total > batch
    assert "_progressive_local_enabled() and total > _LOCAL_SEARCH_BATCH" in body
