"""Project-standard responsive-layout helpers for AI-PACS.

This module bundles the recurring Qt/PySide6 idioms that the codebase relies on
to keep its UI usable across monitor sizes. It is NOT a new framework — every
function is a thin wrapper around Qt primitives that already exist. The
purpose is **consistency**: 30 contributors should not each invent a slightly
different way to wrap a strip in a scroll area or to elide a long label.

Background, the seven archetypes, and the decision tree are in
``docs/conventions/RESPONSIVE_UI_CONVENTION.md`` and
``docs/plans/RESPONSIVE_UI_STRUCTURAL_PATTERN_2026-05-26.md``.

Public surface
==============
- ``wrap_in_horizontal_scroll(widget, *, max_height=None)``  -- Archetype 1
- ``make_wrapping_label(text, *, max_lines=None)``           -- Archetype 2
- ``ElidedLabel(text, parent=None, elide=Qt.ElideRight)``    -- Archetype 3
- ``horizontal_splitter(*widgets, stretch_factors=None, collapsible=False)`` -- Archetype 4
- ``set_form_field_size(field, *, min_height=28, min_width=None, expanding=False)`` -- Archetype 5
- ``set_table_column_policy(table, *, stretch_column=None, resize_to_contents=True)`` -- Archetype 6
- Archetype 7 (empty-state centre panes) is design-specific — no one-size helper.

Design notes
============
- Every helper is identity-safe at the default values it was given. Callers can
  drop a helper into existing code with no other change and the result should
  look the same on a default-width window. The added value appears when the
  parent narrows.
- No helper introduces a new event loop, signal, or background thread. They are
  pure layout-construction utilities — safe to call from ``__init__``.
- No helper imports VTK, qtawesome, or any heavy module. Import cost stays
  trivial so widgets that include it during startup don't slow the app down.
"""
from __future__ import annotations

from typing import Iterable, Optional

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFontMetrics, QResizeEvent
from PySide6.QtWidgets import (
    QFrame,
    QHeaderView,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QTableView,
    QWidget,
)


__all__ = [
    "wrap_in_horizontal_scroll",
    "make_wrapping_label",
    "ElidedLabel",
    "PatientNameLabel",
    "horizontal_splitter",
    "set_form_field_size",
    "set_table_column_policy",
]


# ---------------------------------------------------------------------------
# Archetype 1 — horizontal strip of pinned widgets
# ---------------------------------------------------------------------------
def wrap_in_horizontal_scroll(
    widget: QWidget,
    *,
    max_height: Optional[int] = None,
    frame: bool = False,
) -> QScrollArea:
    """Wrap ``widget`` in a horizontally-scrolling ``QScrollArea``.

    Children retain their fixed sizes; the *strip* gains horizontal overflow
    via a scrollbar that appears only when needed. At default monitor widths
    the result is visually identical to the un-wrapped layout (no scrollbar
    shown).

    Use for: patient chip strip, viewer toolbars, button rows that may exceed
    the parent's width on narrower monitors.

    Parameters
    ----------
    widget:
        The strip's container widget (already has its children added).
    max_height:
        Optional cap on the QScrollArea's height so the scroll area never
        grows taller than the strip's intended height (e.g., 70 for the chip
        strip). When omitted, height tracks the widget's natural size hint.
    frame:
        When False (default) the scroll area renders without its own border —
        the strip looks identical to before. Set True only if you want the
        Qt default sunken frame.

    Returns
    -------
    QScrollArea
        Caller adds *this* to the parent layout instead of ``widget``.
    """
    sa = QScrollArea()
    sa.setWidgetResizable(True)
    sa.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
    sa.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    if not frame:
        sa.setFrameShape(QFrame.NoFrame)
    # Smooth horizontal scroll for the chip strip / toolbar row.
    #
    # NOTE - 2026-05-28 Stage 9 fix: this line used to read
    # `sa.setHorizontalScrollMode(QAbstractScrollArea.ScrollPerPixel)`
    # which is silently wrong: setHorizontalScrollMode lives on
    # QAbstractItemView (used by QTableView etc.), NOT on
    # QAbstractScrollArea or QScrollArea. PySide6 raised AttributeError
    # at runtime, the caller in custom_tab_manager.py:119 caught it via
    # try/except and fell back to a non-scrolling container - silently
    # disabling the chip-strip horizontal scroll on narrow monitors
    # (the original defect this wrap was meant to fix).
    # The correct way to tune QScrollArea scrolling smoothness is the
    # scrollbar's single-step value.
    sa.horizontalScrollBar().setSingleStep(8)
    if max_height is not None:
        sa.setMaximumHeight(int(max_height))
        sa.setMinimumHeight(int(max_height))
    # Transparent background so the strip's parent colour shows through.
    sa.setStyleSheet("QScrollArea { background: transparent; }")
    sa.viewport().setStyleSheet("background: transparent;")
    sa.setWidget(widget)
    return sa


# ---------------------------------------------------------------------------
# Archetype 2 — multi-line description label
# ---------------------------------------------------------------------------
def make_wrapping_label(
    text: str,
    *,
    parent: Optional[QWidget] = None,
    max_lines: Optional[int] = None,
) -> QLabel:
    """Return a ``QLabel`` configured to wrap to multiple lines.

    Use for: description / hint text blocks that currently get clipped mid-word
    when the container narrows.

    Parameters
    ----------
    text:
        Initial text. Use ``label.setText(...)`` later to update.
    parent:
        Optional parent.
    max_lines:
        Optional cap on the rendered line count. Computed via QFontMetrics
        line spacing — Qt has no native max-lines property, so the cap is
        approximate (font changes after construction will not re-compute).
    """
    lbl = QLabel(text, parent)
    lbl.setWordWrap(True)
    lbl.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
    if max_lines is not None and max_lines > 0:
        fm = QFontMetrics(lbl.font())
        lbl.setMaximumHeight(fm.lineSpacing() * int(max_lines) + 4)
    return lbl


# ---------------------------------------------------------------------------
# Archetype 3 — single-line label with elision + tooltip
# ---------------------------------------------------------------------------
class ElidedLabel(QLabel):
    """Single-line label that ellipsises when the container narrows.

    The full text is preserved internally and exposed via a ``QToolTip`` so the
    user can still read it. Width tracking is automatic via ``resizeEvent``.

    Use for: patient names in chips, file paths in narrow cells, badge text,
    button labels that must always be readable but mustn't push the layout.

    Parameters
    ----------
    text:
        Initial full text.
    parent:
        Optional parent widget.
    elide:
        Qt elision mode — ``ElideRight`` (default) puts the ellipsis on the
        right; ``ElideMiddle`` is useful for paths.
    """

    def __init__(
        self,
        text: str = "",
        parent: Optional[QWidget] = None,
        elide: Qt.TextElideMode = Qt.ElideRight,
    ) -> None:
        super().__init__(parent)
        self._full_text: str = ""
        self._elide_mode: Qt.TextElideMode = elide
        # Guard so a width-0 elision attempt doesn't queue an unbounded chain of
        # QTimer.singleShot callbacks while waiting for layout.
        self._deferred_elision_pending: bool = False
        # Preferred horizontal, fixed vertical — common case for inline labels.
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        # Allow the label to shrink to 0 width if its parent forces it — without
        # this, QLabel.minimumSizeHint() tracks the FULL text width and prevents
        # the parent layout from squeezing us into the available space (e.g.
        # the 252px patient chip), which is the very condition our elision is
        # designed to handle.
        self.setMinimumWidth(0)
        self.setText(text)

    # NOTE: shadowing QLabel.setText is the intended public API here.
    def setText(self, text: str) -> None:  # type: ignore[override]
        self._full_text = "" if text is None else str(text)
        # Tooltip surfaces the full text when elided. Empty tooltip when blank.
        self.setToolTip(self._full_text if self._full_text else "")
        self._apply_elision()

    def fullText(self) -> str:
        """Return the unelided text the label was given."""
        return self._full_text

    def setElideMode(self, mode: Qt.TextElideMode) -> None:
        """Change the elision side. Triggers a re-render."""
        self._elide_mode = mode
        self._apply_elision()

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: D401
        super().resizeEvent(event)
        self._apply_elision()

    def _apply_elision(self) -> None:
        # Compute available width — subtract a small fudge for padding.
        avail = max(0, self.width() - 2)
        # When the label has no layout-assigned width yet (constructor / pre-show
        # / inside a still-being-built parent), avail is 0 and any elision
        # collapses the text to "...". That shrinks the label's sizeHint so
        # subsequent layout passes give it the wrong (tiny) width and elision
        # stays broken. Instead, render the FULL text so sizeHint is correct,
        # then re-attempt elision once the layout has actually sized us. We
        # only queue ONE deferred retry; resizeEvent will trigger us again if
        # layout completes later.
        if avail <= 4 and self._full_text:
            super().setText(self._full_text)
            if not self._deferred_elision_pending:
                self._deferred_elision_pending = True
                QTimer.singleShot(0, self._run_deferred_elision)
            return
        self._deferred_elision_pending = False
        fm = QFontMetrics(self.font())
        elided = fm.elidedText(self._full_text, self._elide_mode, avail)
        super().setText(elided)

    def _run_deferred_elision(self) -> None:
        """Single-shot trampoline that clears the pending guard before retrying."""
        self._deferred_elision_pending = False
        self._apply_elision()


# ---------------------------------------------------------------------------
# Archetype 3 (variant) — DICOM patient-name aware elision
# ---------------------------------------------------------------------------
class PatientNameLabel(ElidedLabel):
    """Single-line label that elides DICOM-style patient names cleanly.

    DICOM Person Names use the format ``FAMILY^GIVEN^MIDDLE^PREFIX^SUFFIX``
    (PN VR). When the label is narrower than the full name, this class
    prefers to truncate **whole name components** rather than chopping the
    family name mid-character. Strategy:

      1. Full string fits           → render full string.
      2. Family name + given fits    → render "FAMILY GIVEN".
      3. Just family name fits       → render "FAMILY".
      4. Even family name overflows  → render ``ElideRight("FAMILY")``.

    Step 2 collapses the ``^`` separator into a space so the display reads
    naturally (e.g. "ABDOLHOSEIN MOHAMMAD" instead of "ABDOLHOSEIN^MOHAMMAD").
    The tooltip always carries the original unmodified text so the full
    name is one hover away.

    Use for: patient chip name labels, patient-table cells where a generic
    ``ElidedLabel`` would chop the family name in half (e.g.
    ``ABDOLHOSEIN^MOHAMM…`` instead of the cleaner ``ABDOLHOSEIN``).
    """

    def __init__(
        self,
        text: str = "",
        parent: Optional[QWidget] = None,
    ) -> None:
        # ElideRight is the natural fallback when even the family name
        # overflows — we don't expose elide-mode as a constructor argument
        # because the DICOM strategy is opinionated about cut order.
        super().__init__(text, parent, elide=Qt.ElideRight)

    @staticmethod
    def _split_dicom_name(text: str) -> tuple[str, str]:
        """Return ``(family, rest_joined_by_space)`` from a DICOM PN string.

        - Splits on ``^`` (the DICOM PN component separator).
        - Trims whitespace from each component, drops empty trailing
          components (so ``"ABDOLHOSEIN^^^"`` parses cleanly).
        - If the string contains no ``^``, the entire string is treated as
          the family name with no given/middle/etc.
        """
        components = [c.strip() for c in text.split("^")]
        components = [c for c in components if c]  # drop empties
        if not components:
            return ("", "")
        family = components[0]
        rest = " ".join(components[1:])
        return (family, rest)

    def _apply_elision(self) -> None:
        if not self._full_text:
            super().setText("")
            return
        avail = max(0, self.width() - 2)
        # Defer elision until the label has been laid out — same reasoning as
        # ElidedLabel._apply_elision: when avail is 0 the elided result is
        # "...", which shrinks our sizeHint and locks the chip into giving us a
        # tiny width on the next layout pass. Show the full text so sizeHint is
        # honest, then re-elide once we have a real width assigned. Queue only
        # one pending retry to keep things bounded.
        if avail <= 4:
            QLabel.setText(self, self._full_text)
            if not self._deferred_elision_pending:
                self._deferred_elision_pending = True
                QTimer.singleShot(0, self._run_deferred_elision)
            return
        self._deferred_elision_pending = False
        fm = QFontMetrics(self.font())

        # Candidate 1: full original text (collapse ^ to space for display
        # but try the original first in case the caller actually wants the ^).
        if fm.horizontalAdvance(self._full_text) <= avail:
            QLabel.setText(self, self._full_text)
            return

        family, rest = self._split_dicom_name(self._full_text)

        # No ^ in the string → no DICOM structure to be smart about, fall
        # back to the standard ElidedLabel ElideRight behavior.
        if not family or "^" not in self._full_text:
            elided = fm.elidedText(self._full_text, self._elide_mode, avail)
            QLabel.setText(self, elided)
            return

        # Candidate 2: "FAMILY GIVEN…" — collapse ^ to space, no ellipsis.
        if rest:
            family_plus_rest = f"{family} {rest}"
            if fm.horizontalAdvance(family_plus_rest) <= avail:
                QLabel.setText(self, family_plus_rest)
                return

        # Candidate 3: just FAMILY (no ellipsis — the family name is the
        # most meaningful single component).
        if fm.horizontalAdvance(family) <= avail:
            QLabel.setText(self, family)
            return

        # Candidate 4: even FAMILY overflows — ElideRight on FAMILY so the
        # user sees as much of the family name as the row allows.
        elided = fm.elidedText(family, Qt.ElideRight, avail)
        QLabel.setText(self, elided)


# ---------------------------------------------------------------------------
# Archetype 4 — user-resizable multi-pane splitter
# ---------------------------------------------------------------------------
def horizontal_splitter(
    *widgets: QWidget,
    stretch_factors: Optional[Iterable[int]] = None,
    collapsible: bool = False,
    handle_width: int = 4,
) -> QSplitter:
    """Build a horizontal ``QSplitter`` with project-standard defaults.

    Use for: tri-pane home layout, viewer + sidebar arrangements, two-column
    settings pages — anywhere the user might benefit from dragging a divider
    to redistribute pixels between sibling panels.

    Persistence: caller is responsible for ``splitter.saveState()`` /
    ``restoreState()`` via QSettings or the project's config layer. The
    splitter does not auto-persist.

    Parameters
    ----------
    *widgets:
        Panels in left-to-right order.
    stretch_factors:
        Optional per-panel stretch factor; index aligns with ``widgets``.
        Defaults to equal stretch.
    collapsible:
        Whether the user can drag a panel down to 0 width. Default False so
        panels cannot accidentally disappear.
    handle_width:
        Visual width of the splitter handle in pixels.
    """
    sp = QSplitter(Qt.Horizontal)
    sp.setHandleWidth(int(handle_width))
    sp.setChildrenCollapsible(bool(collapsible))
    for w in widgets:
        sp.addWidget(w)
    if stretch_factors is not None:
        for i, s in enumerate(stretch_factors):
            sp.setStretchFactor(i, int(s))
    return sp


# ---------------------------------------------------------------------------
# Archetype 5 — form fields with min-size + size policy
# ---------------------------------------------------------------------------
def set_form_field_size(
    field: QWidget,
    *,
    min_height: int = 28,
    min_width: Optional[int] = None,
    expanding: bool = False,
) -> None:
    """Apply project-standard sizing to a form field.

    Replacement for ``field.setFixedHeight(N)`` patterns. The field keeps its
    visual floor (so existing layouts look unchanged on default widths) but
    can grow when the font, DPI, or content demands it.

    Use for: ``QLineEdit``, ``QComboBox``, ``QPushButton``, ``QSpinBox`` inside
    forms.

    Parameters
    ----------
    field:
        The widget to size.
    min_height:
        Floor height in pixels. Default 28 matches existing AI-PACS form
        field heights.
    min_width:
        Optional floor width — useful for fields that must stay legible (e.g.
        a path field with ``setMinimumWidth(200)``).
    expanding:
        When True, horizontal size policy is ``Expanding`` so the field
        claims remaining row space (ideal for the last field in a row).
        When False, ``Preferred`` is used.
    """
    field.setMinimumHeight(int(min_height))
    if min_width is not None:
        field.setMinimumWidth(int(min_width))
    h_policy = QSizePolicy.Expanding if expanding else QSizePolicy.Preferred
    field.setSizePolicy(h_policy, QSizePolicy.Fixed)


# ---------------------------------------------------------------------------
# Archetype 6 — QTableView column policy
# ---------------------------------------------------------------------------
def set_table_column_policy(
    table: QTableView,
    *,
    stretch_column: Optional[int] = None,
    resize_to_contents: bool = True,
    per_pixel_scroll: bool = True,
) -> None:
    """Configure a ``QTableView`` so column widths adapt to content + viewport.

    Use for: patient table, server-list tables, anywhere a table currently has
    columns hidden or clipped on narrower monitors.

    Parameters
    ----------
    table:
        The QTableView.
    stretch_column:
        Index of a column to stretch (absorb extra horizontal space). Pass
        ``None`` if no single column should stretch — Qt then sizes every
        column to its contents and scrolls horizontally for overflow.
    resize_to_contents:
        When True, non-stretch columns size themselves to their data.
    per_pixel_scroll:
        Smooth horizontal scrolling rather than column-by-column.
    """
    h = table.horizontalHeader()
    if resize_to_contents:
        h.setSectionResizeMode(QHeaderView.ResizeToContents)
    if stretch_column is not None:
        h.setSectionResizeMode(int(stretch_column), QHeaderView.Stretch)
    if per_pixel_scroll:
        table.setHorizontalScrollMode(QTableView.ScrollPerPixel)
