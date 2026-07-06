"""Guard test for OPT-01 (startup) — two launch-time main-thread freezes.

From the 2026-07-03 probe run the biggest remaining stalls were one-time startup work:
  * ~2.3 s  mainwindow_ui.apply_modern_styling  (a top-level window setStyleSheet that
            cascades a full-tree restyle, re-run with the same theme from setup + apply_theme)
  * ~1.7 s  app_handler._update_license_info     (LOCAL LicenseManager.check_license on the
            GUI thread, only to fill a cosmetic "N days left" label)

Fixes: (1) idempotent dedup of apply_modern_styling (skip identical-theme re-apply);
(2) defer _update_license_info to the idle event loop so the login window appears
immediately. Both live-verified 2026-07-04 and PROMOTED TO DEFAULT 2026-07-05 — the flags
(AIPACS_THEME_APPLY_DEDUP / AIPACS_DEFER_LICENSE_INFO) were retired, so the dedup/defer are
now unconditional.

House style: source-pins guard the real edits (no PySide6/QApplication) + mirror-behavioral
tests reproduce the skip / defer decisions.
"""

from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
MW = REPO / "PacsClient" / "pacs" / "workstation_ui" / "mainwindow_ui.py"
AH = REPO / "PacsClient" / "app_handler.py"
AU = REPO / "PacsClient" / "pacs" / "workstation_ui" / "AIPacs_ui.py"


# --- source-pins: mainwindow apply_modern_styling dedup ------------------------------

def test_modern_styling_dedup_wired():
    s = MW.read_text(encoding="utf-8", errors="ignore")
    assert 'os.getenv("AIPACS_THEME_APPLY_DEDUP"' not in s, "flag retired — dedup is unconditional now"
    assert 'getattr(self, "_applied_modern_sig", None) == theme' in s, "skip guard"
    assert "self._applied_modern_sig = theme" in s, "signature stored after a full apply"
    # guard sits inside apply_modern_styling, before the top-level setStyleSheet
    a = s.index("def apply_modern_styling")
    style = s.index("self.setStyleSheet(", a)
    assert s.index('getattr(self, "_applied_modern_sig"', a) < style


# --- source-pins: AIPacs_ui control-panel apply_theme dedup --------------------------

def test_aipacs_ui_theme_dedup_wired():
    s = AU.read_text(encoding="utf-8", errors="ignore")
    assert 'os.getenv("AIPACS_THEME_APPLY_DEDUP"' not in s, "flag retired — dedup is unconditional now"
    assert 'getattr(self, "_applied_theme_sig", None) == t' in s, "skip guard"
    assert "self._applied_theme_sig = t" in s, "signature stored after a full apply + child cascade"
    # guard sits inside apply_theme, before the first (MainWindow) setStyleSheet
    a = s.index("def apply_theme(self, theme=None):")
    style = s.index("self.MainWindow.setStyleSheet(", a)
    assert s.index('getattr(self, "_applied_theme_sig"', a) < style


# --- source-pins: license-info defer -------------------------------------------------

def test_license_defer_wired():
    s = AH.read_text(encoding="utf-8", errors="ignore")
    assert 'os.getenv("AIPACS_DEFER_LICENSE_INFO"' not in s, "flag retired — defer is unconditional now"
    assert "QTimer.singleShot(0, self._update_license_info)" in s, "deferred to idle loop"


# --- mirror: apply_modern_styling dedup ----------------------------------------------

class _Styler:
    def __init__(self, enabled=True):
        self._enabled = enabled
        self.restyles = 0
        self._active_theme = None

    def apply_modern_styling(self, theme):
        self._active_theme = theme
        if self._enabled:
            try:
                if theme is not None and getattr(self, "_applied_modern_sig", None) == theme:
                    return
            except Exception:
                pass
        self.restyles += 1                 # the full-tree setStyleSheet
        self._applied_modern_sig = theme


def test_modern_styling_skips_identical_theme():
    m = _Styler(enabled=True)
    t = {"window_bg": "#000"}
    m.apply_modern_styling(t)              # setup
    m.apply_modern_styling(t)              # apply_theme (same theme)
    m.apply_modern_styling(t)              # themeChanged re-emit (same)
    assert m.restyles == 1                 # 2 redundant full-tree restyles skipped


def test_modern_styling_reapplies_on_change():
    m = _Styler(enabled=True)
    m.apply_modern_styling({"window_bg": "#000"})
    m.apply_modern_styling({"window_bg": "#fff"})   # real theme change
    assert m.restyles == 2


# --- mirror: license defer decision --------------------------------------------------

class _Login:
    def __init__(self, defer=True):
        self._defer = defer
        self.queued = []          # QTimer.singleShot(0, fn) targets
        self.ran_sync = 0

    def _update_license_info(self):
        pass

    def _startup(self):
        if self._defer:
            self.queued.append(self._update_license_info)   # QTimer.singleShot(0, ...)
        else:
            self.ran_sync += 1                               # synchronous legacy call

    def _drain_idle(self):
        while self.queued:
            self.queued.pop(0)()


def test_license_deferred_to_idle_loop():
    lg = _Login(defer=True)
    lg._startup()
    assert lg.ran_sync == 0 and len(lg.queued) == 1   # not run during startup
    lg._drain_idle()                                   # runs when the loop goes idle
    assert not lg.queued
