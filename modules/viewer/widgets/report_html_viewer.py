"""
ReportHtmlViewer — Qt-native HTML report viewer with full RTL/Persian support.

Uses QTextEdit for rendering so it inherits Qt's mature HTML engine, Unicode
BiDi shaping, and mixed Persian-English text handling without any external
dependencies beyond the existing PySide6 stack.
"""

import logging

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QTextEdit, QVBoxLayout, QWidget

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Persian-capable font stack (first available on Windows is used by Qt)
# ---------------------------------------------------------------------------
_PERSIAN_FONT_FAMILY = (
    '"Vazirmatn", "IRANYekan", "Tahoma", "Arial", "Segoe UI", sans-serif'
)


class ReportHtmlViewer(QWidget):
    """
    Read-only HTML viewer with first-class RTL/Persian text support.

    Wraps QTextEdit and applies an RTL-aware CSS template to every HTML
    fragment set via :meth:`set_report_html`.  The outer QWidget shell
    makes it a drop-in replacement for QTextBrowser in any layout.

    Public interface (mirrors the parts of QTextBrowser used by
    ReceptionReportsViewer):
      * set_report_html(html)   — set content with RTL wrapping
      * clear()                 — clear the display
      * setOpenExternalLinks()  — forward to underlying editor (no-op; kept
                                  for API compatibility; links stay disabled
                                  by default to avoid security issues)
    """

    # --------------------------------------------------------------------- #
    # Construction                                                            #
    # --------------------------------------------------------------------- #

    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_editor()
        self._setup_layout()

    def _setup_editor(self):
        self.editor = QTextEdit(self)

        # Read-only, rich text, RTL
        self.editor.setReadOnly(True)
        self.editor.setAcceptRichText(True)
        self.editor.setLayoutDirection(Qt.RightToLeft)
        self.editor.setLineWrapMode(QTextEdit.WidgetWidth)

        # Persian-capable font
        font = QFont()
        font.setFamily("Tahoma")          # first widely-available Persian font
        font.setPointSize(11)
        self.editor.setFont(font)

        # Disable external links by default (security)
        self.editor.setOpenLinks(False)

    def _setup_layout(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.editor)

    # --------------------------------------------------------------------- #
    # Public API                                                              #
    # --------------------------------------------------------------------- #

    def set_report_html(self, html: str) -> None:
        """
        Render *html* inside a safe RTL wrapper and display it.

        If *html* is empty or None, shows an empty document.
        Any exception during rendering is caught and logged; the viewer
        falls back to plain-text display of the original content.
        """
        try:
            safe_html = self._wrap_rtl_html(html or "")
            self.editor.setHtml(safe_html)
        except Exception as exc:  # pragma: no cover
            logger.error("ReportHtmlViewer: failed to render HTML: %s", exc, exc_info=True)
            try:
                self.editor.setPlainText(html or "")
            except Exception:
                pass

    def clear(self) -> None:
        """Clear displayed content."""
        self.editor.clear()

    def setOpenExternalLinks(self, enable: bool) -> None:  # noqa: N802 — matches Qt naming
        """API-compatibility shim.  External links remain disabled for safety."""
        # We deliberately ignore *enable* — opening arbitrary external links
        # from a medical report viewer is a security risk.  Log if someone
        # tries to enable it so it can be revisited deliberately.
        if enable:
            logger.debug(
                "ReportHtmlViewer: setOpenExternalLinks(True) ignored "
                "(external links disabled for security)"
            )

    # --------------------------------------------------------------------- #
    # Internal helpers                                                        #
    # --------------------------------------------------------------------- #

    def _wrap_rtl_html(self, html: str) -> str:
        """
        Wrap *html* in a complete RTL-aware HTML document.

        The wrapping:
        * Declares UTF-8 encoding.
        * Sets ``direction: rtl`` on <body> so Persian text flows right-to-left
          and is shaped correctly by Qt's text engine.
        * Uses ``unicode-bidi: plaintext`` so mixed Persian-English paragraphs
          each follow their own natural base direction automatically.
        * Keeps Latin / code / ``<pre>`` blocks LTR via ``.ltr`` helper class.
        * Uses a Persian-capable font stack.
        """
        return (
            "<!DOCTYPE html>\n"
            "<html>\n"
            "<head>\n"
            '<meta charset="utf-8">\n'
            "<style>\n"
            "body {\n"
            "    direction: rtl;\n"
            "    unicode-bidi: plaintext;\n"
            "    text-align: right;\n"
            f"    font-family: {_PERSIAN_FONT_FAMILY};\n"
            "    font-size: 14px;\n"
            "    line-height: 1.7;\n"
            "    margin: 0;\n"
            "    padding: 16px;\n"
            "}\n"
            "table {\n"
            "    direction: rtl;\n"
            "    text-align: right;\n"
            "    border-collapse: collapse;\n"
            "    width: 100%;\n"
            "    margin: 10px 0;\n"
            "}\n"
            "td, th {\n"
            "    text-align: right;\n"
            "    vertical-align: top;\n"
            "    border: 1px solid #3a3a3a;\n"
            "    padding: 8px;\n"
            "}\n"
            "th {\n"
            "    background-color: #1e1e1e;\n"
            "    font-weight: bold;\n"
            "}\n"
            ".ltr, code, pre {\n"
            "    direction: ltr;\n"
            "    unicode-bidi: embed;\n"
            "    text-align: left;\n"
            "}\n"
            "a { color: #4fc3f7; }\n"
            "</style>\n"
            "</head>\n"
            "<body>\n"
            f"{html}\n"
            "</body>\n"
            "</html>"
        )
