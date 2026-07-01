"""Guard test for P1.3 — progressive (chunked) build of the viewer thumbnail sidebar.

`_render_thumbnails_from_files` built every series' thumbnail widget (QPixmap + card) in
one synchronous loop, which can freeze patient open. P1.3 optionally appends the thumbnails
a few per event-loop tick, in the SAME order (no clear/rebuild). It is **DEFAULT OFF**
because it changes clinical render *timing* and must be visually verified (flicker / order /
download borders, single AND multi-study) before the default is flipped. The multi-study
grouped render path is intentionally untouched.

Source-pins guard the real edit (no PySide6/QApplication needed). A mirror-behavioral test
reproduces the exact chunk driver and proves order + thumb_index continuity + token-cancel.
"""

from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
PW_THUMBS = (REPO / "PacsClient" / "pacs" / "patient_tab" / "ui" / "patient_ui"
             / "patient_widget_core" / "_pw_thumbnails.py")


def _src() -> str:
    return PW_THUMBS.read_text(encoding="utf-8", errors="ignore")


def test_flag_default_on_after_visual_verify():
    s = _src()
    # Validated on the source build (order + no flicker + borders) -> default ON,
    # with AIPACS_SIDEBAR_BUILD_CHUNKED=0 kept as the kill switch.
    assert 'os.getenv("AIPACS_SIDEBAR_BUILD_CHUNKED", "1")' in s
    assert 'os.getenv("AIPACS_SIDEBAR_BUILD_CHUNK", "3")' in s


def test_chunk_driver_and_token_guard():
    s = _src()
    assert "def _render_files_chunked(self, thumbs, index, thumb_index, sp_downloaded, token):" in s
    assert "if token != getattr(self, '_sidebar_build_token', 0):" in s
    assert "QTimer.singleShot(0, lambda: self._render_files_chunked(thumbs, end, thumb_index, sp_downloaded, token))" in s


def test_shared_per_series_helper_used_by_both_paths():
    s = _src()
    assert "def _render_one_thumbnail_file(self, thumbnail_file, thumb_index, sp_downloaded):" in s
    # both the sync loop and the chunk driver route through the shared helper (no fork)
    assert s.count("self._render_one_thumbnail_file(") >= 2


def test_multistudy_grouped_render_untouched():
    s = _src()
    # the chunk flag must not appear anywhere near the multi-study grouped path
    assert "_render_multistudy_grouped" not in _region_around(s, "AIPACS_SIDEBAR_BUILD_CHUNKED", 1500)


def _region_around(s: str, anchor: str, radius: int) -> str:
    i = s.index(anchor)
    return s[max(0, i - radius): i + radius]


# --- mirror-behavioral: exact algorithm of _render_files_chunked ---------------------

class _Mirror:
    def __init__(self):
        self._sidebar_build_token = 0
        self.appended = []          # (thumbnail_file, thumb_index_before)
        self._timers = []

    def _render_one_thumbnail_file(self, thumbnail_file, thumb_index, sp):
        self.appended.append((thumbnail_file, thumb_index))
        return thumb_index + 1

    def _render_files_chunked(self, thumbs, index, thumb_index, sp, token, chunk=3):
        if token != self._sidebar_build_token:
            return
        end = min(index + chunk, len(thumbs))
        for i in range(index, end):
            thumb_index = self._render_one_thumbnail_file(thumbs[i], thumb_index, sp)
        if end < len(thumbs):
            self._timers.append(
                lambda: self._render_files_chunked(thumbs, end, thumb_index, sp, token, chunk))

    def _drain(self):
        while self._timers:
            self._timers.pop(0)()


def test_mirror_order_and_index_continuity():
    m = _Mirror()
    thumbs = [f"s{i}.png" for i in range(10)]
    m._sidebar_build_token = 1
    m._render_files_chunked(thumbs, 0, 0, None, 1, chunk=3)
    m._drain()
    # every file rendered once, in order, with a strictly increasing thumb_index 0..9
    assert [f for f, _ in m.appended] == thumbs
    assert [idx for _, idx in m.appended] == list(range(10))


def test_mirror_token_supersede_cancels():
    m = _Mirror()
    thumbs = [f"s{i}.png" for i in range(10)]
    m._sidebar_build_token = 1
    m._render_files_chunked(thumbs, 0, 0, None, 1, chunk=3)  # renders s0..s2, schedules next
    m._sidebar_build_token = 2                                # a newer render starts
    m._drain()
    assert [f for f, _ in m.appended] == ["s0.png", "s1.png", "s2.png"]
