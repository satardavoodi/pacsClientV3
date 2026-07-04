"""Guard test for OPT-01 (startup) — idempotent dedup of PatientSearchWidget.apply_theme.

`apply_theme` re-runs ~15 `setStyleSheet` calls (incl. `_apply_field_styling` over 11 fields,
each a large QSS block). It is invoked several times during construction (setup_ui line 89,
__init__ line 29, `_hp_layout.apply_theme`, `home_panel`) with the SAME theme — a measured
~2.3 s startup freeze (stall trace: apply_theme -> _apply_field_styling). Every stylesheet is a
pure function of the theme dict, so re-applying an unchanged theme is redundant work with a
byte-identical result. The fix skips when the theme is unchanged since the last application;
a real theme change (a different dict) never matches and always re-applies. Kill switch:
AIPACS_THEME_APPLY_DEDUP=0.

House style (mirrors test_status_refresh_dicom_only.py): source-pins guard the real edit (no
PySide6/QApplication needed) + a mirror-behavioral test reproduces the exact skip algorithm.
"""

from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
PSW = REPO / "PacsClient" / "pacs" / "workstation_ui" / "home_ui" / "patient_search_widget.py"


def _src() -> str:
    return PSW.read_text(encoding="utf-8", errors="ignore")


# --- source-pins ---------------------------------------------------------------------

def test_flag_default_on_and_os_imported():
    s = _src()
    assert "\nimport os\n" in s, "os must be imported for the flag read"
    assert 'os.getenv("AIPACS_THEME_APPLY_DEDUP", "1")' in s, "dedup flag must default ON"


def test_guard_and_signature_wired():
    s = _src()
    # the skip guard compares the incoming theme to the last applied one
    assert 'getattr(self, "_applied_theme_sig", None) == t' in s
    # …and the signature is stored only after a full apply (so first apply always runs)
    assert "self._applied_theme_sig = t" in s
    # guard sits inside apply_theme, before the first setStyleSheet
    ap = s.index("def apply_theme(self, theme=None):")
    first_style = s.index('self.setStyleSheet(f"background: {t[', ap)
    assert s.index("AIPACS_THEME_APPLY_DEDUP", ap) < first_style


# --- mirror-behavioral: exact skip algorithm -----------------------------------------

class _Mirror:
    """Standalone re-implementation of the apply_theme dedup (a real widget needs a
    QApplication). ``applies`` counts the ~15-setStyleSheet block that actually runs."""

    def __init__(self, enabled: bool = True):
        self._enabled = enabled
        self.applies = 0
        self._active_theme = None

    def apply_theme(self, theme):
        t = theme
        self._active_theme = t
        if self._enabled:
            try:
                if t is not None and getattr(self, "_applied_theme_sig", None) == t:
                    return
            except Exception:
                pass
        self.applies += 1                 # the expensive restyle
        self._applied_theme_sig = t


def test_identical_theme_is_skipped():
    m = _Mirror(enabled=True)
    theme = {"panel_bg": "#000", "accent": "#0af"}
    m.apply_theme(theme)
    m.apply_theme(theme)
    m.apply_theme(theme)
    assert m.applies == 1                 # only the first ran; 2 redundant re-styles skipped


def test_equal_content_new_dict_is_skipped():
    m = _Mirror(enabled=True)
    m.apply_theme({"panel_bg": "#000"})
    m.apply_theme({"panel_bg": "#000"})   # a fresh dict with equal content
    assert m.applies == 1                 # == compares by value -> still a no-op


def test_theme_change_reapplies():
    m = _Mirror(enabled=True)
    m.apply_theme({"panel_bg": "#000"})   # theme A
    m.apply_theme({"panel_bg": "#fff"})   # theme B (real change)
    m.apply_theme({"panel_bg": "#fff"})   # B again -> skipped
    assert m.applies == 2                 # A then B; the repeat of B is skipped


def test_first_apply_always_runs():
    m = _Mirror(enabled=True)
    assert not hasattr(m, "_applied_theme_sig")
    m.apply_theme({"panel_bg": "#000"})
    assert m.applies == 1                 # getattr default None != theme -> applied


def test_kill_switch_always_applies():
    m = _Mirror(enabled=False)
    theme = {"panel_bg": "#000"}
    m.apply_theme(theme)
    m.apply_theme(theme)
    m.apply_theme(theme)
    assert m.applies == 3                 # flag off -> byte-identical always-apply legacy
