"""Thumbnail-panel UI fixes (2026-07-29):
  1. Intermittent overlap-on-load: the multi-study grouped + show_exist render
     paths must ACTIVATE the grid synchronously (not just updateGeometry, which
     posts a deferred LayoutRequest) so cards are positioned before the repaint.
  2. Download progress bar rendered ABOVE the frosted-glass overlay.
  3. Active (currently-viewed) series gets a thicker / higher-contrast border.

Source-pin tests (Qt paint/z-order behaviour is not unit-renderable headless).
"""
from pathlib import Path


def _repo_root() -> Path:
    p = Path(__file__).resolve()
    for anc in p.parents:
        if (anc / "PacsClient").is_dir() and (anc / "modules").is_dir():
            return anc
    raise RuntimeError("repo root not found")


def _pw_thumbnails_src() -> str:
    return (_repo_root() / "PacsClient" / "pacs" / "patient_tab" / "ui" / "patient_ui"
            / "patient_widget_core" / "_pw_thumbnails.py").read_text(encoding="utf-8")


def _thumbnail_manager_src() -> str:
    return (_repo_root() / "PacsClient" / "pacs" / "patient_tab" / "utils"
            / "thumbnail_manager.py").read_text(encoding="utf-8")


# ── 1. overlap-on-load: activate() in the two deferred-layout paths ──────────

def test_multistudy_and_show_exist_activate_grid_synchronously():
    src = _pw_thumbnails_src()
    # both render paths now call the immediate activate() (gated), not just the
    # deferred updateGeometry()
    assert 'AIPACS_SIDEBAR_ACTIVATE_ON_RENDER' in src
    assert src.count("self.thumb_grid.activate()") >= 2

    # multistudy: activate() appears inside _render_multistudy_grouped, before
    # setUpdatesEnabled(True)
    ms = src[src.find("def _render_multistudy_grouped"):]
    ms = ms[:ms.find("def _render_thumbnails_from_files")]
    i_act = ms.find("self.thumb_grid.activate()")
    i_enable = ms.find("thumb_container.setUpdatesEnabled(True)")
    assert -1 < i_act < i_enable, "multistudy must activate before re-enabling paint"

    # show_exist_thumbnails likewise
    se = src[src.find("def show_exist_thumbnails"):]
    se = se[:se.find("\n    def ", 10)]
    j_act = se.find("self.thumb_grid.activate()")
    j_enable = se.find("thumb_container.setUpdatesEnabled(True)")
    assert -1 < j_act < j_enable, "show_exist must activate before re-enabling paint"


def test_chunked_path_activate_still_present():
    """The single-study chunked path's original per-chunk activate() must remain."""
    src = _pw_thumbnails_src()
    cf = src[src.find("def _render_files_chunked"):]
    cf = cf[:cf.find("\n    def ", 10)]
    assert "self.thumb_grid.activate()" in cf
    assert "setUpdatesEnabled(False)" in cf and "setUpdatesEnabled(True)" in cf


# ── 2. progress bar above the glass ─────────────────────────────────────────

def test_progress_bar_is_child_of_card_and_raised_above_glass():
    src = _thumbnail_manager_src()
    assert 'AIPACS_THUMB_BAR_ABOVE_GLASS' in src
    # created as a child of the card widget (same parent as glass_overlay) when above
    assert "QProgressBar(widget if _bar_above else None)" in src
    # absolute bottom-strip geometry + click-through
    assert "dl_bar.setGeometry(8, 215 - 11, 190 - 16, 4)" in src
    assert "dl_bar.setAttribute(Qt.WA_TransparentForMouseEvents, True)" in src
    # raised above the glass at creation AND re-raised whenever the glass shows
    assert "_bar.raise_()" in src
    assert "def _raise_dl_bar_above_glass" in src
    # the % text stays a child of glass_overlay (already on top) — unchanged
    assert "progress_overlay = QLabel(glass_overlay)" in src


# ── 3. stronger active-series border ────────────────────────────────────────

def test_active_series_border_is_thicker_and_higher_contrast():
    src = _thumbnail_manager_src()
    assert 'AIPACS_ACTIVE_THUMB_STRONG' in src
    # thicker stroke for the selected card
    assert "bw = 3.5" in src
    # the border_rect + pen use the computed bw (so a thicker border is not clipped)
    assert "rect.width() - bw" in src
    assert "pen = QPen(border_color, bw, Qt.SolidLine)" in src
    # stronger fill for the selected state (was alpha 30)
    assert "bg_color.setAlpha(64 if _os.getenv(\"AIPACS_ACTIVE_THUMB_STRONG\", \"1\") != \"0\" else 30)" in src


def test_active_border_uses_theme_accent_token_light_and_dark():
    """Active colour is the accent THEME token, so it works in light + dark."""
    src = _thumbnail_manager_src()
    sel = src[src.find("elif self._is_selected:"):]
    sel = sel[:sel.find("elif self._viewed")]
    assert "self._theme.get('accent'" in sel   # token, not a hard-coded literal
