"""Guards: the Series-Thumbnails / Previous-Exam header is TWO rows, not one.

UI refinement (2026-06-21): the single-row header (Series Thumbnails + count +
Previous Exam button + count on one line) overlapped / truncated when counts grew,
width was limited, or DPI / localized labels were larger. It is now two rows:
  Row 1: [ Series Thumbnails ]            [ N series ]
  Row 2: [ Previous Exam ]                [ N exams  ]
Each row right-aligns its count via a stretch; the previous-exam count moved out of
the button text into its own pill.

These are source-pin guards (the header builder needs full Qt, so it isn't imported
here) — they fail if the layout regresses to a single row or the count pill is
removed. Pure string checks; run anywhere.
"""
from __future__ import annotations

from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
_CORE = _REPO_ROOT / "PacsClient/pacs/patient_tab/ui/patient_ui/patient_widget_core"
_PANELS = (_CORE / "_pw_panels.py").read_text(encoding="utf-8")
_PREV = (_CORE / "_pw_previous_exams.py").read_text(encoding="utf-8")


# ---- bordered two-row card structure ------------------------------------

def test_header_is_bordered_two_row_card():
    # The two sections live inside ONE rounded QFrame "card".
    assert "header_widget = QFrame()" in _PANELS
    assert 'setObjectName("thumbHeaderCard")' in _PANELS
    assert "header_v = QVBoxLayout(header_widget)" in _PANELS
    assert "row1 = QHBoxLayout()" in _PANELS
    assert "row2 = QHBoxLayout()" in _PANELS


def test_header_width_aligned_with_cards():
    # (Point 1) header fixed to the 190px card width, left-offset 8 (== thumb_grid
    # left margin) and left-aligned, with a frameless scroll -> header and cards
    # share the same left edge + width.
    assert "header_widget.setFixedWidth(190)" in _PANELS
    assert "header_align.setContentsMargins(8, 0, 0, 0)" in _PANELS
    assert "header_align.addWidget(header_widget)" in _PANELS
    assert "thumb_scroll.setFrameShape(QFrame.NoFrame)" in _PANELS


def test_no_header_icons():
    # (Point 2) icons before Series Thumbnails / Previous Exam were removed.
    assert "fa5s.images" not in _PANELS
    assert "fa5s.history" not in _PANELS


def test_header_has_divider_between_sections():
    # (Point 3) a horizontal divider separates the two sections.
    assert "_divider.setFrameShape(QFrame.HLine)" in _PANELS


def test_sections_are_clickable():
    # (Point 4) both sections read as clickable: a button + pointer cursor; the
    # Series Thumbnails section returns to the series grid.
    assert "self.series_thumb_btn = QPushButton(" in _PANELS
    assert "self.series_thumb_btn.setCursor(Qt.PointingHandCursor)" in _PANELS
    assert "self.series_thumb_btn.clicked.connect(self._show_series_thumbnails_view)" in _PANELS
    assert "self.prev_exam_btn.setCursor(Qt.PointingHandCursor)" in _PANELS


def test_each_row_right_aligns_its_count():
    # Count right-aligned: label/button -> stretch -> count.
    for tag, label, count in (
        ("row1", "row1.addWidget(self.series_thumb_btn)", "row1.addWidget(self.thumb_count_label)"),
        ("row2", "row2.addWidget(self.prev_exam_btn)", "row2.addWidget(self.prev_exam_count_label)"),
    ):
        a = _PANELS.index(label)
        s = _PANELS.index(f"{tag}.addStretch()")
        c = _PANELS.index(count)
        assert a < s < c, f"{tag}: expected label < stretch < count (count right-aligned)"


def test_previous_exam_count_pill_exists():
    assert 'self.prev_exam_count_label = QLabel("0 exams")' in _PANELS


# ---- count moved out of the button text into its pill -------------------

def test_count_style_helper_present():
    assert "def _previous_exam_count_style(self, *, active: bool)" in _PREV


def test_button_text_no_longer_embeds_count():
    # the old single-row layout put the count inside the button label
    assert 'f"Previous Exam ({count})"' not in _PREV
    # button text is the plain section title now
    assert 'btn.setText("Previous Exam")' in _PREV


def test_count_label_pluralizes():
    # "0 exams" / "1 exam" / "N exams"
    assert "f\"{count} exam{'' if count == 1 else 's'}\"" in _PREV
    assert 'count_lbl.setText("0 exams")' in _PREV


def test_count_label_styled_active_and_inactive():
    assert "self._previous_exam_count_style(active=True)" in _PREV
    assert "self._previous_exam_count_style(active=False)" in _PREV


def test_previous_exam_text_red_active_gray_inactive():
    # (Point 5) the Previous Exam label is RED when prior exams exist, GRAY when
    # none — driven by _previous_exam_button_style(active).
    style = _PREV[_PREV.index("def _previous_exam_button_style"):
                 _PREV.index("def _series_thumbnails_button_style")]
    assert "#ef4444" in style, "active state must be red"
    assert "#6b7280" in style, "inactive state must be gray"


def test_series_thumbnails_clickable_helpers_present():
    # (Point 4) the Series Thumbnails section has a flat clickable style + a handler
    # that returns to the series grid (stack page 0).
    assert "def _series_thumbnails_button_style(self)" in _PREV
    assert "def _show_series_thumbnails_view(self)" in _PREV
    assert "setCurrentIndex(0)" in _PREV


# ---- series CARD header row (thumbnail_manager, redesigned 2026-06-21) ---

_TM = (_REPO_ROOT / "PacsClient/pacs/patient_tab/utils/thumbnail_manager.py").read_text(
    encoding="utf-8"
)


def test_card_header_is_a_row_with_count_on_right():
    # The card's "Series N" title and its image count share a top ROW (count
    # right-aligned), instead of a centered title with a separate bottom count.
    assert "header_row_layout = QHBoxLayout(header_row)" in _TM
    assert "header_row_layout.addWidget(header_label)" in _TM
    assert "header_row_layout.addStretch()" in _TM
    assert "header_row_layout.addWidget(count_label)" in _TM


def test_card_count_label_always_created_and_updated_in_place():
    # count_label is created in the header row and stored on the widget, so the
    # count updaters set its text in place rather than re-adding a centered count.
    assert "widget.count_label = count_label" in _TM
    assert 'widget.count_label.setText(f"{image_count} images")' in _TM


def test_card_has_cached_icon_helper():
    assert "def _series_card_icon_pixmap(self)" in _TM
