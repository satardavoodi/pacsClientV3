"""Guard test for the 2D patient-tab open optimization (warmup dispatch).

On patient open the pipeline POST_DOWNLOAD callback scheduled the ZetaBoost warmup via
`QMetaObject.invokeMethod(self.parent_widget, <python lambda>, QueuedConnection)`. invokeMethod
with a Python callable triggers PySide6's `shibokensupport` signature introspection, which scans
sys.path with `is_dir`/`os.stat` — a hundreds-of-ms main-thread stall on patient open (seen in the
stall traces: `_vc_load` -> shibokensupport -> is_dir -> os.stat). Since that callback runs on the
qasync GUI loop, the cross-thread marshalling is redundant; when already on the UI thread we schedule
the warmup directly (no shibokensupport). Flag `AIPACS_WARMUP_DISPATCH_FAST` (default on); `=0`
restores the original invokeMethod path.

Source-pin guard (no PySide6/QApplication needed).
"""

from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
VC_LOAD = REPO / "PacsClient" / "pacs" / "patient_tab" / "ui" / "patient_ui" / "_vc_load.py"


def _src() -> str:
    return VC_LOAD.read_text(encoding="utf-8", errors="ignore")


def test_flag_default_on():
    s = _src()
    assert 'os.getenv("AIPACS_WARMUP_DISPATCH_FAST", "1")' in s


def test_fast_path_reuses_ui_thread_helper_and_avoids_invokemethod():
    s = _src()
    # the fast path is gated on the EXISTING _is_on_ui_thread() helper (no duplicated
    # thread check) and schedules the warmup directly (no invokeMethod on the hot path)
    i = s.index('os.getenv("AIPACS_WARMUP_DISPATCH_FAST"')
    region = s[i:i + 700]
    assert "self._is_on_ui_thread()" in region
    assert "QTimer.singleShot(500, self._start_open_tab_warmup)" in region
    # the direct schedule appears before the else/invokeMethod branch
    assert region.index("QTimer.singleShot(500, self._start_open_tab_warmup)") < region.index("else:")


def test_kill_switch_preserves_invokemethod_path():
    s = _src()
    i = s.index('os.getenv("AIPACS_WARMUP_DISPATCH_FAST"')
    region = s[i:i + 900]
    # flag off / not-on-ui-thread -> original invokeMethod + except fallback retained
    assert "QMetaObject.invokeMethod(" in region
    assert "Qt.ConnectionType.QueuedConnection" in region
    assert "except Exception:" in region


def test_helper_exists():
    s = _src()
    assert "def _is_on_ui_thread(self)" in s
