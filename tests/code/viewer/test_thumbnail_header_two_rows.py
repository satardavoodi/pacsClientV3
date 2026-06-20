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


# ---- two-row structure --------------------------------------------------

def test_header_uses_vertical_two_row_container():
    assert "header_v = QVBoxLayout(header_widget)" in _PANELS
    assert "row1 = QHBoxLayout()" in _PANELS
    assert "row2 = QHBoxLayout()" in _PANELS


def test_each_row_groups_label_then_count_then_stretch():
    # The count sits NEXT TO its label (not pushed to the far right): it is added
    # BEFORE the row's stretch, so label+count group on the left and the stretch
    # fills the remaining width. Guards the 2026-06-21 "count too far" refinement.
    for tag, label, count in (
        ("row1", "row1.addWidget(title_label)", "row1.addWidget(self.thumb_count_label)"),
        ("row2", "row2.addWidget(self.prev_exam_btn)", "row2.addWidget(self.prev_exam_count_label)"),
    ):
        a = _PANELS.index(label)
        b = _PANELS.index(count)
        c = _PANELS.index(f"{tag}.addStretch()")
        assert a < b < c, f"{tag}: expected label < count < stretch (count beside label)"


def test_count_added_beside_label_with_small_gap():
    assert "row1.addSpacing(8)" in _PANELS
    assert "row2.addSpacing(8)" in _PANELS


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
