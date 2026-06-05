"""OS printer handler using Qt printing (placeholder)."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QPainter
from PySide6.QtPrintSupport import QPrinter, QPrinterInfo, QPrintDialog


class OSPrinterHandler:
    def list_printers(self) -> list[str]:
        try:
            return [printer.printerName() for printer in QPrinterInfo.availablePrinters()]
        except Exception:
            return []

    def print_film(self, film_pixmap: Any, printer_name: str | None = None) -> bool:
        if film_pixmap is None:
            return False

        printer = QPrinter(QPrinter.HighResolution)
        if printer_name:
            printer.setPrinterName(printer_name)

        dialog = QPrintDialog(printer)
        if dialog.exec() != QPrintDialog.Accepted:
            return False

        painter = QPainter(printer)
        if not painter.isActive():
            # Painter never started → nothing to end. Returning False signals
            # an actionable failure to the UI without raising.
            return False

        try:
            rect = painter.viewport()
            pixmap = film_pixmap
            # Use positional args + KeepAspectRatio + SmoothTransformation so
            # the printed image is anti-aliased and not pixelated at the
            # printer's native (usually 300 DPI) resolution. The previous
            # ``aspectMode=`` kwarg was a name typo that worked only by
            # coincidence on some PySide6 builds.
            scaled = pixmap.scaled(
                rect.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation
            )
            # Centre on the page so KeepAspectRatio gutters are symmetric.
            x = max(0, (rect.width() - scaled.width()) // 2)
            y = max(0, (rect.height() - scaled.height()) // 2)
            painter.drawPixmap(x, y, scaled)
            return True
        finally:
            painter.end()
