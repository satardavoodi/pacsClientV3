"""HomeInfoPanel — the Home Page "Information" section (redesign 2026-06-06).

Replaces the old static two-box panel (title label + one paragraph inside
nested bordered frames) with a clean, data-driven dashboard section:

* SOFTWARE block — running version (read live from
  ``QApplication.applicationVersion()``), build/release dates, stability
  status chip, recent changes, affected modules.
* COMPANY block — what AI-PACS develops, the services it provides, and the
  global operation statement.

Visual language: flat — NO nested frames, NO divider lines. Quiet uppercase
section captions (the V2 dropdown-header style), whitespace for separation,
theme tokens throughout (graceful fallbacks when the theme manager is
unavailable). The only "chip" is the stability badge.

Future extensibility: everything renders through ``add_section(...)`` /
``add_lines(...)``, so release notes, maintenance notifications, company
news, regulatory updates, or AI-module announcements are one call each —
no redesign needed:

    panel.add_section("MAINTENANCE", ["Server window: Friday 22:00-23:00"])
"""
from __future__ import annotations

from typing import Iterable, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication, QHBoxLayout, QLabel, QScrollArea, QVBoxLayout, QWidget,
)

# ── Release information (single place to edit per release) ──────────────────
# ``version`` is a FALLBACK only — the live value comes from
# QApplication.applicationVersion() (set in main.py), so the panel can never
# disagree with the running build.
RELEASE_INFO = {
    "app_name": "AI-PACS Viewer",
    "version": "3.3.6",
    "build_date": "2026-06-21",
    "release_date": "2026-06-21",
    "status": "Stable",          # Stable | Beta | Internal Testing
    "changes": [
        "MPR stays active when switching series or loading into another viewport",
        "Fixed duplicate voice notes after reopening a synced patient",
        "More accurate study grouping (correct series-to-study assignment)",
        "More reliable downloads: oversize fast-fail and first-image alignment",
        "Performance, stability, and testing-tooling improvements",
    ],
    "modules": ["Viewer", "Download Manager", "MPR", "EchoMind", "EagleEye"],
}

COMPANY_INFO = {
    "registered": (
        "AI-PACS is registered in the European Union and has been active "
        "in medical imaging for more than ten years."
    ),
    "develops": [
        "DICOM Workstations",
        "PACS Solutions",
        "Radiology AI Modules",
        "Clinical Imaging Software",
    ],
    "services": [
        "Online Radiology Reporting",
        "Second Opinion Services",
        "International Imaging Consultation",
    ],
    "global": (
        "Supporting radiologists, imaging centers, and healthcare "
        "providers worldwide."
    ),
}

# ── Persian-market customized edition notice ────────────────────────────────
# Shown prominently near the top of the Information panel so Persian-speaking
# users can immediately see that this build is the localized edition produced
# with our business partner, Iran Nobat. English first, then the same notice
# in Farsi (rendered right-to-left).
PERSIAN_EDITION = {
    "title": "Persian Customized Edition",
    "en": [
        "AI-PACS Version 3.3.6",
        "This edition has been customized and localized for Persian-speaking "
        "users at the request of our business partner, Iran Nobat, in Iran.",
        "This customized version includes workflow, language, and usability "
        "adaptations designed specifically for radiology centers, clinics, and "
        "healthcare providers operating in the Persian-speaking market.",
        "Developed by AI-PACS in collaboration with Iran Nobat.",
    ],
    "fa": [
        "AI-PACS نسخهٔ ۳.۳.۴",
        "این نسخه بنا به درخواست شریک تجاری ما، «ایران نوبت»، به‌طور اختصاصی "
        "برای کاربران فارسی‌زبان در ایران سفارشی‌سازی و بومی‌سازی شده است.",
        "این نسخهٔ سفارشی شامل تطبیق‌های گردش‌کار، زبان و کاربری است که به‌طور "
        "ویژه برای مراکز رادیولوژی، کلینیک‌ها و مراکز درمانی فعال در بازار "
        "فارسی‌زبان طراحی شده است.",
        "توسعه‌یافته توسط AI-PACS با همکاری «ایران نوبت».",
    ],
}

_STATUS_TOKEN = {"stable": "success", "beta": "warning",
                 "internal testing": "info"}


def _theme() -> dict:
    try:
        from PacsClient.utils.theme_manager import get_theme_manager
        return get_theme_manager().current_theme() or {}
    except Exception:
        return {}


class HomeInfoPanel(QWidget):
    """Flat, scrollable, extensible Information panel."""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._build()

    # ── construction ─────────────────────────────────────────────────────
    def _build(self) -> None:
        t = _theme()
        self._text = t.get("text_secondary", "#dbe7f3")
        self._bright = t.get("text_primary", "#f8fafc")
        self._muted = t.get("text_muted", "#93a4b7")
        self._accent = t.get("accent", "#3182ce")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setStyleSheet(
            "QScrollArea { background: transparent; border: none; }"
        )
        body = QWidget()
        body.setStyleSheet("QWidget { background: transparent; border: none; }")
        self._body_layout = QVBoxLayout(body)
        self._body_layout.setContentsMargins(14, 12, 14, 14)
        self._body_layout.setSpacing(4)
        scroll.setWidget(body)
        outer.addWidget(scroll)

        # ── SOFTWARE block ────────────────────────────────────────────────
        self._add_app_header()
        self._add_meta_line()
        self._add_persian_edition()
        self.add_section("RECENT CHANGES",
                         [f"•  {c}" for c in RELEASE_INFO["changes"]])
        self.add_section("AFFECTED MODULES",
                         ["  ·  ".join(RELEASE_INFO["modules"])])

        self._add_gap(18)

        # ── COMPANY block ─────────────────────────────────────────────────
        self.add_section("ABOUT AI-PACS", [COMPANY_INFO["registered"]])
        self.add_section("WE DEVELOP",
                         [f"•  {d}" for d in COMPANY_INFO["develops"]])
        self.add_section("SERVICES",
                         [f"•  {s}" for s in COMPANY_INFO["services"]])
        self.add_section("GLOBAL", [COMPANY_INFO["global"]])

        self._body_layout.addStretch(1)

    # ── software header pieces ────────────────────────────────────────────
    @staticmethod
    def running_version() -> str:
        """The version of the RUNNING app (never disagrees with the build)."""
        try:
            app = QApplication.instance()
            v = str(app.applicationVersion()).strip() if app else ""
            return v or RELEASE_INFO["version"]
        except Exception:
            return RELEASE_INFO["version"]

    def _add_app_header(self) -> None:
        row = QHBoxLayout()
        row.setSpacing(8)
        title = QLabel(RELEASE_INFO["app_name"])
        title.setStyleSheet(
            f"color: {self._bright}; font-size: 15px; font-weight: 700;"
            " font-family: 'Roboto', sans-serif; background: transparent;"
            " border: none;"
        )
        status = str(RELEASE_INFO.get("status") or "Stable")
        token = _STATUS_TOKEN.get(status.lower(), "success")
        chip_color = _theme().get(token, "#10b981")
        self.status_chip = QLabel(status)
        self.status_chip.setStyleSheet(
            f"color: {chip_color}; border: 1px solid {chip_color};"
            " border-radius: 8px; padding: 1px 8px; font-size: 10px;"
            " font-weight: 700; background: transparent;"
        )
        row.addWidget(title)
        row.addWidget(self.status_chip)
        row.addStretch(1)
        self._body_layout.addLayout(row)

        self.version_label = QLabel(f"Version {self.running_version()}")
        self.version_label.setStyleSheet(
            f"color: {self._accent}; font-size: 13px; font-weight: 600;"
            " background: transparent; border: none;"
        )
        self._body_layout.addWidget(self.version_label)

    def _add_meta_line(self) -> None:
        meta = QLabel(
            f"Build {RELEASE_INFO['build_date']}   ·   "
            f"Released {RELEASE_INFO['release_date']}"
        )
        meta.setStyleSheet(
            f"color: {self._muted}; font-size: 10px; background: transparent;"
            " border: none;"
        )
        self._body_layout.addWidget(meta)

    def _add_persian_edition(self) -> None:
        """Prominent Persian-market edition notice — English then Farsi (RTL).

        Placed right after the version/build meta so Persian-speaking users see
        immediately that this is the localized edition. Uses the same flat
        section styling (no frames/borders) as every other block.
        """
        self.add_section(PERSIAN_EDITION["title"], PERSIAN_EDITION["en"])
        self.add_lines(PERSIAN_EDITION["fa"], rtl=True)

    # ── extensible section API ────────────────────────────────────────────
    def add_section(self, title: str, lines: Iterable[str],
                    rtl: bool = False) -> None:
        """Append a flat section: quiet uppercase caption + body lines.

        The single entry point for ALL current and FUTURE content (release
        notes, maintenance notices, company news, regulatory updates…) —
        callers never deal with styling or frames. Pass ``rtl=True`` for
        right-to-left scripts (e.g. Farsi) so the body lines align correctly.
        """
        self._add_gap(12)
        caption = QLabel(str(title).upper())
        caption.setStyleSheet(
            f"color: {self._muted}; font-size: 9px; font-weight: 700;"
            " letter-spacing: 1px; background: transparent; border: none;"
        )
        self._body_layout.addWidget(caption)
        self.add_lines(lines, rtl=rtl)

    def add_lines(self, lines: Iterable[str], rtl: bool = False) -> None:
        for line in lines or []:
            lbl = QLabel(str(line))
            lbl.setWordWrap(True)
            lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
            if rtl:
                lbl.setLayoutDirection(Qt.RightToLeft)
                lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            lbl.setStyleSheet(
                f"color: {self._text}; font-size: 11px; line-height: 1.45;"
                " background: transparent; border: none; padding: 1px 0;"
            )
            self._body_layout.addWidget(lbl)

    def _add_gap(self, px: int) -> None:
        gap = QWidget()
        gap.setFixedHeight(max(0, int(px)))
        gap.setStyleSheet("background: transparent; border: none;")
        self._body_layout.addWidget(gap)


__all__ = ["HomeInfoPanel", "RELEASE_INFO", "COMPANY_INFO", "PERSIAN_EDITION"]
