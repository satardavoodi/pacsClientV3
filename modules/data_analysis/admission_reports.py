# -*- coding: utf-8 -*-
"""Admission Reports dashboard tab (گزارش پذیرش) for the Data Analysis module.

Retrieves, displays and refreshes admission/reporting data from the web
admission software's Reports API and renders it as a Persian/RTL dashboard:
summary cards, modality bar chart, modality & insurance donuts, a daily
admission trend line, and a recent-admissions table.

Non-blocking contract
---------------------
Opening or refreshing this tab must NEVER freeze the workstation. Every network
call + JSON parse + snapshot build runs on a background daemon thread
(:class:`~modules.data_analysis.admission_api.AdmissionReportsWorker`); only the
final ``set_*`` calls touch widgets, on the GUI thread. A refresh requested
while one is in flight is coalesced (last-wins), so rapid clicks can't pile up.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .admission_api import (
    DATE_PRESETS,
    AdmissionReportsClient,
    AdmissionReportsWorker,
    resolve_date_range,
)
from .admission_charts import (
    PersianBarChart,
    PersianDonutChart,
    PersianLineChart,
    SummaryCard,
    format_int,
    format_rial,
    to_persian_digits,
)

logger = logging.getLogger(__name__)


class AdmissionReportsTab(QWidget):
    """Self-contained admission-reports dashboard (opens inside Data Analysis)."""

    def __init__(self, parent: Optional[QWidget] = None, auth_user: Optional[Dict[str, Any]] = None):
        super().__init__(parent)
        self._auth_user = auth_user or {}
        self._client = AdmissionReportsClient()
        self._worker: Optional[AdmissionReportsWorker] = None
        self._refresh_in_flight = False
        self._pending_refresh = False
        self._loaded_once = False

        self.setLayoutDirection(Qt.RightToLeft)
        self._build_ui()
        self.apply_theme()

    # ------------------------------------------------------------------ UI
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)

        # --- Header / controls ------------------------------------------
        header = QFrame(self)
        header.setObjectName("adm_header")
        h = QHBoxLayout(header)
        h.setContentsMargins(12, 10, 12, 10)

        title = QLabel("داشبورد گزارش پذیرش")
        title.setObjectName("adm_title")
        tf = title.font()
        tf.setPointSize(tf.pointSize() + 3)
        tf.setBold(True)
        title.setFont(tf)

        self.range_combo = QComboBox()
        for key, label in DATE_PRESETS:
            self.range_combo.addItem(label, key)
        self.range_combo.setCurrentIndex(0)
        self.range_combo.setMinimumWidth(110)
        self.range_combo.setToolTip("بازهٔ زمانی گزارش")
        self.range_combo.currentIndexChanged.connect(lambda _=0: self.refresh())

        self.refresh_btn = QPushButton("بروزرسانی")
        self.refresh_btn.setToolTip("دریافت مجدد داده‌ها از سرور پذیرش")
        self.refresh_btn.clicked.connect(self.refresh)

        self.updated_label = QLabel("آخرین بروزرسانی: —")
        self.updated_label.setObjectName("adm_updated")

        # Title may elide on very narrow windows; the controls stay intact.
        title.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        range_lbl = QLabel("بازهٔ زمانی:")
        h.addWidget(title, 1)
        h.addStretch(0)
        h.addWidget(range_lbl)
        h.addWidget(self.range_combo)
        h.addWidget(self.refresh_btn)
        h.addWidget(self.updated_label)
        root.addWidget(header)

        # --- Loading bar (indeterminate) --------------------------------
        self.loading_bar = QProgressBar()
        self.loading_bar.setRange(0, 0)  # indeterminate
        self.loading_bar.setTextVisible(False)
        self.loading_bar.setFixedHeight(4)
        self.loading_bar.setVisible(False)
        root.addWidget(self.loading_bar)

        # --- Error banner (hidden until an error) -----------------------
        self.error_banner = QFrame(self)
        self.error_banner.setObjectName("adm_error")
        eb = QHBoxLayout(self.error_banner)
        eb.setContentsMargins(12, 8, 12, 8)
        self.error_label = QLabel("")
        self.error_label.setWordWrap(True)
        self.retry_btn = QPushButton("تلاش مجدد")
        self.retry_btn.clicked.connect(self.refresh)
        eb.addWidget(self.error_label, 1)
        eb.addWidget(self.retry_btn)
        self.error_banner.setVisible(False)
        root.addWidget(self.error_banner)

        # --- Scroll area holding the whole dashboard body ---------------
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        body = QWidget()
        body_lay = QVBoxLayout(body)
        body_lay.setContentsMargins(2, 2, 2, 2)
        body_lay.setSpacing(10)

        # KPI cards grid
        kpi_frame = QFrame(body)
        kpi_frame.setObjectName("adm_kpi_frame")
        self.kpi_grid = QGridLayout(kpi_frame)
        self.kpi_grid.setContentsMargins(6, 6, 6, 6)
        self.kpi_grid.setHorizontalSpacing(10)
        self.kpi_grid.setVerticalSpacing(10)

        self.card_patients = SummaryCard("تعداد کل بیماران پذیرش‌شده", "#59a14f")
        self.card_receptions = SummaryCard("تعداد پذیرش‌ها", "#4e79a7")
        self.card_services = SummaryCard("تعداد کل خدمات", "#edc948")
        self.card_revenue = SummaryCard("درآمد کل", "#e15759")
        self.card_mri = SummaryCard("ام‌آر‌آی (MRI)", "#b07aa1")
        self.card_ct = SummaryCard("سی‌تی‌اسکن (CT)", "#f28e2b")
        self.card_us = SummaryCard("سونوگرافی (US)", "#76b7b2")
        self.card_xray = SummaryCard("رادیولوژی (X-Ray)", "#ff9da7")

        cards = [
            self.card_patients, self.card_receptions, self.card_services, self.card_revenue,
            self.card_mri, self.card_ct, self.card_us, self.card_xray,
        ]
        for i, card in enumerate(cards):
            self.kpi_grid.addWidget(card, i // 4, i % 4)
        for _c in range(4):
            self.kpi_grid.setColumnStretch(_c, 1)  # cards share width evenly
        body_lay.addWidget(kpi_frame)

        # --- Financial summary section (خلاصه مالی) ---------------------
        # Shows the financial breakdown separately, ending in the final
        # net revenue:
        #   درآمد نهایی = سهم بیمار + سهم بیمه − برداشت دستی − تخفیف صندوق
        fin_frame = QFrame(body)
        fin_frame.setObjectName("adm_section")
        fin_outer = QVBoxLayout(fin_frame)
        fin_outer.setContentsMargins(10, 10, 10, 10)
        fin_outer.setSpacing(8)
        fin_title = QLabel("خلاصه مالی")
        fin_title.setObjectName("adm_section_title")
        fin_outer.addWidget(fin_title)

        fin_grid = QGridLayout()
        fin_grid.setHorizontalSpacing(10)
        fin_grid.setVerticalSpacing(10)
        self.fin_patient_share = SummaryCard("سهم بیمار (پرداخت بیمار)", "#59a14f")
        self.fin_insurance_share = SummaryCard("سهم بیمه", "#4e79a7")
        self.fin_total_discount = SummaryCard("مجموع تخفیف‌ها", "#edc948")
        self.fin_manual_withdrawal = SummaryCard("برداشت دستی", "#b07aa1")
        self.fin_cashier_discount = SummaryCard("تخفیف صندوق", "#f28e2b")
        self.fin_total_revenue = SummaryCard("درآمد نهایی (خالص دریافتی)", "#e15759")
        fin_cards = [
            self.fin_patient_share, self.fin_insurance_share, self.fin_total_discount,
            self.fin_manual_withdrawal, self.fin_cashier_discount, self.fin_total_revenue,
        ]
        for i, c in enumerate(fin_cards):
            fin_grid.addWidget(c, i // 3, i % 3)
        for _c in range(3):
            fin_grid.setColumnStretch(_c, 1)  # financial cards share width evenly
        fin_outer.addLayout(fin_grid)
        body_lay.addWidget(fin_frame)

        # Charts row 1: modality bar + modality donut
        row1 = QSplitter(Qt.Horizontal)
        self.modality_bar = PersianBarChart()
        self.modality_donut = PersianDonutChart()
        row1.addWidget(self._section("تعداد بیماران بر اساس مودالیتی", self.modality_bar))
        row1.addWidget(self._section("توزیع مودالیتی", self.modality_donut))
        row1.setStretchFactor(0, 3)
        row1.setStretchFactor(1, 2)
        body_lay.addWidget(row1)

        # Charts row 2: daily trend line + insurance donut
        row2 = QSplitter(Qt.Horizontal)
        self.trend_line = PersianLineChart()
        self.insurance_donut = PersianDonutChart()
        row2.addWidget(self._section("روند پذیرش روزانه", self.trend_line))
        row2.addWidget(self._section("توزیع بیمه", self.insurance_donut))
        row2.setStretchFactor(0, 3)
        row2.setStretchFactor(1, 2)
        body_lay.addWidget(row2)

        # Tables SIDE BY SIDE — modality breakdown (left) + latest admissions
        # (right). Each is a compact, tall vertical-style table: reduced width
        # (they share the row via a horizontal splitter) and increased height so
        # more rows are visible without stretching across the whole dashboard.
        tables_row = QSplitter(Qt.Horizontal)
        self.modality_table = self._make_table(["مودالیتی", "تعداد", "سهم (٪)", "مبلغ (ریال)"])
        self.modality_table.setMinimumHeight(380)
        self.recent_table = self._make_table(
            ["شمارهٔ پذیرش", "تاریخ", "ساعت", "بیمار", "مودالیتی", "بیمه", "مبلغ (ریال)"]
        )
        self.recent_table.setMinimumHeight(380)
        # Patient name is the variable-length column → let it absorb slack so
        # names stay readable; the fixed-width columns size to content.
        _rh = self.recent_table.horizontalHeader()
        _rh.setStretchLastSection(False)
        _rh.setSectionResizeMode(3, QHeaderView.Stretch)
        tables_row.addWidget(self._section("جدول تفکیک مودالیتی", self.modality_table))
        tables_row.addWidget(self._section("آخرین پذیرش‌ها", self.recent_table))
        # Modality table has fewer columns → give it less width than the wider
        # latest-admissions table.
        tables_row.setStretchFactor(0, 2)
        tables_row.setStretchFactor(1, 3)
        body_lay.addWidget(tables_row, 1)

        scroll.setWidget(body)
        root.addWidget(scroll, 1)

    def _section(self, title: str, body: QWidget) -> QWidget:
        frame = QFrame(self)
        frame.setObjectName("adm_section")
        lay = QVBoxLayout(frame)
        lay.setContentsMargins(10, 10, 10, 10)
        lay.setSpacing(8)
        lbl = QLabel(title)
        lbl.setObjectName("adm_section_title")
        lay.addWidget(lbl)
        lay.addWidget(body)
        return frame

    def _make_table(self, headers: list) -> QTableWidget:
        table = QTableWidget(0, len(headers), self)
        table.setHorizontalHeaderLabels(headers)
        table.setAlternatingRowColors(True)
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        table.setSelectionBehavior(QTableWidget.SelectRows)
        table.verticalHeader().setVisible(False)
        table.setSortingEnabled(False)
        table.setLayoutDirection(Qt.RightToLeft)
        table.setWordWrap(False)
        table.setTextElideMode(Qt.ElideRight)
        table.setHorizontalScrollMode(QTableWidget.ScrollPerPixel)
        # Columns size to their content but the last one absorbs slack, so a
        # narrow (side-by-side) table stays readable and the widest column
        # fills the remaining space instead of leaving empty width.
        hdr = table.horizontalHeader()
        hdr.setSectionResizeMode(QHeaderView.ResizeToContents)
        hdr.setStretchLastSection(True)
        hdr.setMinimumSectionSize(48)
        return table

    # -------------------------------------------------------------- refresh
    def refresh(self) -> None:
        """Request a non-blocking refresh (coalesced while one is in flight)."""
        if self._refresh_in_flight:
            self._pending_refresh = True
            return
        self._refresh_in_flight = True
        self._pending_refresh = False
        self._set_loading(True)
        self._hide_error()

        preset = self.range_combo.currentData() or "today"
        start, end = resolve_date_range(str(preset))

        worker = AdmissionReportsWorker(self)
        worker.finished.connect(self._on_finished)
        worker.failed.connect(self._on_failed)
        self._worker = worker  # keep a ref while in flight
        worker.start(self._client, start, end)

    def _on_finished(self, snapshot: object) -> None:
        self._refresh_in_flight = False
        self._teardown_worker()
        self._set_loading(False)
        if isinstance(snapshot, dict):
            try:
                self._populate(snapshot)
            except Exception:  # pragma: no cover - defensive; never crash the UI
                logger.exception("[admission] populate failed")
        self._drain_pending()

    def _on_failed(self, message: str, kind: str) -> None:
        self._refresh_in_flight = False
        self._teardown_worker()
        self._set_loading(False)
        self._show_error(message, kind)
        self._drain_pending()

    def _drain_pending(self) -> None:
        if self._pending_refresh:
            self._pending_refresh = False
            QTimer.singleShot(0, self.refresh)

    def _teardown_worker(self) -> None:
        w = self._worker
        if w is not None:
            self._worker = None
            try:
                w.deleteLater()
            except Exception:
                pass

    # -------------------------------------------------------------- populate
    def _populate(self, snap: Dict[str, Any]) -> None:
        cards = snap.get("cards", {})
        self.card_patients.set_value(format_int(cards.get("total_patients", 0)))
        self.card_receptions.set_value(format_int(cards.get("total_receptions", 0)))
        self.card_services.set_value(format_int(cards.get("total_services", 0)))
        self.card_revenue.set_value(format_rial(cards.get("total_amount", 0)))

        hi = {c["code"]: c for c in snap.get("highlight_cards", [])}
        self._set_modality_card(self.card_mri, hi.get("2"))
        self._set_modality_card(self.card_ct, hi.get("1"))
        self._set_modality_card(self.card_us, hi.get("3"))
        self._set_modality_card(self.card_xray, hi.get("4"))

        # Financial summary cards
        fin = snap.get("financial", {})
        self.fin_patient_share.set_value(format_rial(fin.get("patient_share", 0)))
        self.fin_insurance_share.set_value(format_rial(fin.get("insurance_share", 0)))
        self.fin_total_discount.set_value(format_rial(fin.get("total_discount", 0)))
        self.fin_manual_withdrawal.set_value(format_rial(fin.get("manual_withdrawal", 0)))
        self.fin_cashier_discount.set_value(format_rial(fin.get("cashier_discount", 0)))
        self.fin_total_revenue.set_value(
            format_rial(fin.get("total_revenue", 0)),
            "سهم بیمار + سهم بیمه − برداشت دستی − تخفیف صندوق",
        )

        modality_rows = snap.get("modality_rows", [])
        insurance_rows = snap.get("insurance_rows", [])
        self.modality_bar.set_rows(modality_rows)
        self.modality_donut.set_rows(modality_rows)
        self.insurance_donut.set_rows(insurance_rows)
        self.trend_line.set_rows(snap.get("daily_rows", []))

        self._fill_modality_table(modality_rows)
        self._fill_recent_table(snap.get("table_rows", []))

        import datetime as _dt
        self.updated_label.setText(
            "آخرین بروزرسانی: " + to_persian_digits(_dt.datetime.now().strftime("%H:%M:%S"))
        )

    def _set_modality_card(self, card: SummaryCard, entry: Optional[Dict[str, Any]]) -> None:
        if not entry:
            card.set_value("۰", "")
            return
        card.set_value(
            format_int(entry.get("count", 0)),
            f"{to_persian_digits(str(entry.get('patients', 0)))} بیمار",
        )

    def _fill_modality_table(self, rows: list) -> None:
        self.modality_table.setRowCount(0)
        for row in rows:
            r = self.modality_table.rowCount()
            self.modality_table.insertRow(r)
            self._set_cell(self.modality_table, r, 0, str(row.get("label", "")))
            self._set_cell(self.modality_table, r, 1, to_persian_digits(str(int(row.get("count", 0)))))
            self._set_cell(self.modality_table, r, 2, to_persian_digits(f"{float(row.get('percent', 0.0)):.1f}"))
            self._set_cell(self.modality_table, r, 3, format_int(row.get("amount", 0)))

    def _fill_recent_table(self, rows: list) -> None:
        self.recent_table.setRowCount(0)
        for row in rows:
            r = self.recent_table.rowCount()
            self.recent_table.insertRow(r)
            self._set_cell(self.recent_table, r, 0, to_persian_digits(str(row.get("receptionId", "") or "")))
            self._set_cell(self.recent_table, r, 1, to_persian_digits(str(row.get("date", "") or "")))
            self._set_cell(self.recent_table, r, 2, to_persian_digits(str(row.get("time", "") or "")))
            self._set_cell(self.recent_table, r, 3, str(row.get("patient", "") or ""))
            self._set_cell(self.recent_table, r, 4, str(row.get("modality", "") or ""))
            self._set_cell(self.recent_table, r, 5, str(row.get("insurance", "") or ""))
            self._set_cell(self.recent_table, r, 6, format_int(row.get("amount", 0)))

    def _set_cell(self, table: QTableWidget, r: int, c: int, text: str) -> None:
        item = QTableWidgetItem(text)
        item.setTextAlignment(Qt.AlignCenter)
        # Full text on hover so an elided (narrow-column) cell stays readable.
        if text:
            item.setToolTip(text)
        table.setItem(r, c, item)

    # -------------------------------------------------------------- states
    def _set_loading(self, loading: bool) -> None:
        try:
            self.loading_bar.setVisible(loading)
            self.refresh_btn.setEnabled(not loading)
            if loading:
                self.updated_label.setText("در حال بارگذاری…")
        except Exception:  # pragma: no cover
            pass

    def _show_error(self, message: str, kind: str) -> None:
        try:
            self.error_label.setText(message)
            self.error_banner.setVisible(True)
        except Exception:  # pragma: no cover
            pass

    def _hide_error(self) -> None:
        try:
            self.error_banner.setVisible(False)
        except Exception:  # pragma: no cover
            pass

    # -------------------------------------------------------------- lifecycle
    def showEvent(self, event) -> None:  # noqa: N802
        # Lazy first load: fetch only when the tab is first shown, so simply
        # constructing it (or opening the Data Analysis page on another tab)
        # does no network I/O.
        super().showEvent(event)
        if not self._loaded_once:
            self._loaded_once = True
            QTimer.singleShot(0, self.refresh)

    # -------------------------------------------------------------- theming
    def apply_theme(self, theme: Optional[Dict[str, str]] = None) -> None:
        self.setStyleSheet(
            """
            QFrame#adm_header, QFrame#adm_kpi_frame, QFrame#adm_section {
                background: #0f1624;
                border: 1px solid #22304a;
                border-radius: 10px;
            }
            QLabel#adm_title { color: #ffffff; }
            QLabel#adm_updated { color: #9cb6d6; }
            QLabel#adm_section_title { color: #cfe0f5; font-weight: bold; }
            QFrame#adm_error {
                background: #3a1720;
                border: 1px solid #e15759;
                border-radius: 8px;
            }
            QFrame#adm_error QLabel { color: #ffd7db; }
            QPushButton {
                background: #1f2c44; color: #eaf2ff;
                border: 1px solid #2f4166; border-radius: 6px;
                padding: 5px 14px;
            }
            QPushButton:hover { background: #2a3a58; }
            QPushButton:disabled { color: #6f88ab; }
            QComboBox {
                background: #1f2c44; color: #eaf2ff;
                border: 1px solid #2f4166; border-radius: 6px; padding: 4px 8px;
            }
            QTableWidget {
                background: #0c131f; color: #eaf2ff;
                gridline-color: #22304a; border: none;
                alternate-background-color: #111a2a;
            }
            QHeaderView::section {
                background: #17233a; color: #cfe0f5;
                border: none; padding: 6px; font-weight: bold;
            }
            """
        )
        # Repaint charts with themed backgrounds (kept dark for chart contrast).
        for chart in (
            getattr(self, "modality_bar", None),
            getattr(self, "modality_donut", None),
            getattr(self, "insurance_donut", None),
            getattr(self, "trend_line", None),
        ):
            if chart is not None:
                chart.set_palette("#0f1624", "#23314a", "#eaf2ff", "#9cb6d6")
