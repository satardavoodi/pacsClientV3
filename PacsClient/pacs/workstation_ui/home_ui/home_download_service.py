"""
Download orchestration service for the Home panel.

Encapsulates the wiring between the Zeta Download Manager, series info
fetching, and the patient viewer widget.  This removes ~500 lines of
interleaved download + UI logic from HomePanelWidget.

Pattern: Service Layer
  HomePanelWidget (UI)  →  HomeDownloadService (orchestration)
                        →  DownloadManagerWidget (engine)
"""

from __future__ import annotations

import asyncio
import logging
import os
import time as _time
from pathlib import Path
from typing import Optional

from PySide6.QtWidgets import QTabWidget

from PacsClient.utils.config import SOURCE_PATH
from PacsClient.utils.series_identity import resolve_series_identifier as _resolve_series_identifier
from modules.download_manager.ui.main_widget import DownloadManagerWidget

# UNIFIED multi-study DM→viewer routing (S3b cutover, 2026-06-27). The DM→widget bridge is bound
# to ONE primary study_uid; a multi-study patient's SECONDARY-study series (a non-opened study or
# a Previous Exam under a different Study UID) reports DM events under that other uid + the bare
# resolved number, while the viewport awaits/shows it under a DISPLAY/offset key. The former THREE
# flag-gated re-keying patches (AIPACS_PROGRESSIVE_UID_BIND / AIPACS_THUMB_SIBLING_STUDY_STATUS /
# AIPACS_GROW_SIBLING_STUDY — all default-ON) are now ONE unconditional rule: every DM event
# resolves its display key from the globally-unique series_uid via `_grow_lane_display_key` (grow
# lane) / `_belongs_to_open_thumbnails` (thumbnail lane), both built SOLELY from this patient's own
# server_series_info → cross-patient isolation preserved. PRIMARY / single-study stays
# byte-identical (display key == resolved number). Collapsing the flags deletes the unused legacy
# `=0` branches only — the default production behavior is unchanged.

try:
    from modules.viewer.fast.slot_timing import time_slot as _g6_time_slot
except Exception:  # pragma: no cover
    from contextlib import contextmanager

    @contextmanager
    def _g6_time_slot(*_a, **_k):  # type: ignore[no-redef]
        yield

try:
    from modules.viewer.fast.ui_throttle import (
        progress_update_interval_ms as _progress_update_interval_ms,
        should_admit as _ui_should_admit,
    )
except Exception:  # pragma: no cover - defensive for stripped test envs
    def _progress_update_interval_ms() -> float:
        return 200.0

    def _ui_should_admit(task_type, context=None) -> bool:
        return True

_logger = logging.getLogger(__name__)


class _ConnectionRecord:
    """Bookkeeping for one DM↔widget signal wiring session."""

    __slots__ = (
        "dm",
        "widget_ref",
        "handlers",
        "flush_timer",
        "progress_timer",
        "key",
    )

    def __init__(self, dm, widget_ref, handlers: dict, flush_timer, progress_timer, key: str):
        self.dm = dm
        self.widget_ref = widget_ref
        self.handlers = handlers  # signal_name → handler callable
        self.flush_timer = flush_timer
        self.progress_timer = progress_timer
        self.key = key


class _SeriesProgressNormalizer:
    """Normalize raw DM per-series progress into one terminal authority.

    This helper keeps the completion signal as the single authoritative
    terminal pulse for a series cycle. Raw terminal progress updates
    (`current >= total`) are treated as provisional and are dropped so they
    do not race against the definitive completion path and re-fan out into
    thumbnails/progressive consumers.

    The state also lets a verified new partial cycle for the same series clear
    the completed guard and begin emitting progress again.
    """

    __slots__ = ("_completed_series",)

    def __init__(self) -> None:
        self._completed_series: set[str] = set()

    def mark_started(self, series_number: str) -> None:
        self._completed_series.discard(str(series_number))

    def mark_completed(self, series_number: str) -> bool:
        sn = str(series_number)
        if sn in self._completed_series:
            return False
        self._completed_series.add(sn)
        return True

    def should_emit_progress(self, series_number: str, current: int, total: int) -> tuple[bool, str]:
        sn = str(series_number)
        current = int(current)
        total = int(total)

        if total > 0 and current >= total:
            return False, "terminal_progress_reserved_for_completion"

        if sn in self._completed_series:
            if total > 0 and current < total:
                self._completed_series.discard(sn)
                return True, "new_partial_cycle"
            return False, "stale_after_completion"

        return True, "admit"


class HomeDownloadService:
    """Orchestrates download-manager lifecycle and study download flow.

    Parameters
    ----------
    tab_widget : QTabWidget
        The main application tab bar (for DM tab creation).
    custom_tab_manager : object | None
        Optional custom tab manager for title-bar integration.
    """

    def __init__(self, tab_widget: QTabWidget, custom_tab_manager=None):
        self.tab_widget = tab_widget
        self.custom_tab_manager = custom_tab_manager
        # Connection key → _ConnectionRecord (lifecycle-tracked)
        self._dm_widget_connections: dict[str, _ConnectionRecord] = {}
        self._cleaned_up = False

    # ------------------------------------------------------------------
    # Download Manager tab lifecycle
    # ------------------------------------------------------------------

    def get_or_create_dm_tab(self, *, activate: bool = False) -> Optional[DownloadManagerWidget]:
        """Return the existing DM widget or create a new tab.

        This is the single authoritative factory for the Download Manager
        tab – all code paths must go through here.
        """
        try:
            from modules.network.zeta_adapter import get_zeta_download_manager_widget

            # 1. Existing tab
            for i in range(self.tab_widget.count()):
                w = self.tab_widget.widget(i)
                if isinstance(w, DownloadManagerWidget):
                    if activate:
                        self._activate_tab(i)
                    return w

            # 2. Create
            dm = get_zeta_download_manager_widget(base_output_dir=Path(SOURCE_PATH))

            if self.custom_tab_manager:
                self.custom_tab_manager.add_download_manager_tab(
                    widget=dm, activate=activate)
            else:
                self.tab_widget.addTab(dm, "Download Manager")
                if activate:
                    self.tab_widget.setCurrentWidget(dm)
            return dm

        except Exception as exc:
            _logger.exception("[DM] Error creating download manager tab: %s", exc)
            return None

    # ------------------------------------------------------------------
    # Signal wiring: DM ↔ patient widget
    # ------------------------------------------------------------------

    def connect_dm_to_widget(self, dm: DownloadManagerWidget, widget,
                             study_uid: str) -> None:
        """Wire Download Manager progress signals to a patient widget.

        Idempotent – duplicate calls for the same (study, widget) pair are
        no-ops.
        """
        connection_key = f"{study_uid}_{id(widget)}"
        if connection_key in self._dm_widget_connections:
            return
        try:
            import weakref

            widget_ref = weakref.ref(widget)
            _pending_completed: list[str] = []
            _pending_progress: dict[str, tuple[int, int]] = {}
            _last_progress_sent: dict[str, tuple[int, int]] = {}
            # Per-card download-progress-bar throttle: last integer percent pushed to
            # each open series card. Dedups so the thin bar repaints at most ~once per
            # 1% (bounded, smooth, no lag) regardless of how chatty the DM is.
            _last_thumb_bar_pct: dict[str, int] = {}
            _thumbnail_completed_series: set[str] = set()
            _progress_normalizer = _SeriesProgressNormalizer()
            from PySide6.QtCore import QTimer
            _flush_timer = QTimer()
            _flush_timer.setSingleShot(True)
            _flush_timer.setInterval(100)
            _progress_timer = QTimer()
            _progress_timer.setSingleShot(True)
            _progress_timer.setInterval(int(max(100.0, _progress_update_interval_ms())))
            _first_emitted = {"done": False}

            def _resolve_sn(series_uid_or_number):
                sn = str(series_uid_or_number)
                w = widget_ref()
                if w and hasattr(w, "thumbnail_manager"):
                    tm = w.thumbnail_manager
                    if tm:
                        resolved = _resolve_series_identifier(
                            sn,
                            known_series_numbers=getattr(tm, 'series_widgets', {}).keys(),
                            uid_to_number_map=getattr(tm, '_series_uid_to_number', {}) or {},
                        )
                        if resolved and resolved != sn:
                            return resolved
                        if resolved and sn in getattr(tm, 'series_widgets', {}):
                            return resolved
                if w:
                    try:
                        resolved = _resolve_series_identifier(
                            sn,
                            uid_to_number_map=getattr(w, '_series_uid_to_number', {}) or {},
                            series_info_map=getattr(w, '_server_series_info', {}) or {},
                        )
                        if resolved and resolved != sn:
                            return resolved
                        if resolved:
                            sn = resolved
                    except Exception:
                        pass
                # 3. Fallback: resolve via DM task series list (SeriesInfo dataclass)
                try:
                    task = dm._tasks.get(study_uid)
                    if task:
                        for s in getattr(task, 'series_list', []) or []:
                            if str(getattr(s, 'series_uid', '')) == sn:
                                s_num = str(getattr(s, 'series_number', ''))
                                if s_num:
                                    return s_num
                except Exception:
                    pass
                return sn

            def _resolve_series_total(sn_str):
                """Look up DICOM image_count for a series from the DM task."""
                try:
                    task = dm._tasks.get(study_uid)
                    if task:
                        for s in getattr(task, 'series_list', []) or []:
                            if str(getattr(s, 'series_number', '')) == sn_str:
                                return int(getattr(s, 'image_count', 0))
                except Exception:
                    pass
                return 0

            def _emit_final_progress(w, sn_str):
                """Emit series_images_progress(sn, total, total) — completion pulse."""
                if not hasattr(w, "series_images_progress"):
                    return
                total = _resolve_series_total(sn_str)
                if total > 0:
                    try:
                        w.series_images_progress.emit(sn_str, total, total)
                    except Exception:
                        pass

            def _complete_thumbnail_now(w, sn_str) -> bool:
                """Project completion to the thumbnail lane immediately when possible."""
                if not w or not hasattr(w, "thumbnail_manager"):
                    return False
                try:
                    total_images = _resolve_series_total(sn_str)
                    w.thumbnail_manager.complete_series_download(
                        sn_str,
                        total_images=total_images if total_images > 0 else None,
                    )
                    return True
                except Exception:
                    return False

            def _sibling_total(uid, series_uid) -> int:
                """DICOM image_count for a sibling-study series, looked up from that
                study's OWN DM task (the primary-scoped _resolve_series_total cannot see
                a secondary study)."""
                try:
                    task = dm._tasks.get(uid)
                    if task:
                        s_uid = str(series_uid)
                        for s in getattr(task, 'series_list', []) or []:
                            if str(getattr(s, 'series_uid', '')) == s_uid:
                                return int(getattr(s, 'image_count', 0))
                except Exception:
                    pass
                return 0

            def _belongs_to_open_thumbnails(series_uid) -> bool:
                """Cross-patient-safe admission test for sibling-study (uid != the
                bridge's primary study_uid) status updates: True only when series_uid
                is in THIS multi-study patient's uid→number map — which is built solely
                from this patient's server_series_info. A foreign patient's UID can
                never resolve here, so the clinical cross-patient isolation invariant is
                preserved. Single-study patients never reach here (uid == study_uid)."""
                if not series_uid:
                    return False
                w = widget_ref()
                if not w:
                    return False
                try:
                    is_multi = (len(getattr(w, '_studies_series', {}) or {}) > 1
                                or bool(getattr(w, '_is_multistudy_hint', False)))
                except Exception:
                    is_multi = False
                if not is_multi:
                    return False
                s = str(series_uid)
                tm = getattr(w, 'thumbnail_manager', None)
                for m in (getattr(tm, '_series_uid_to_number', {}) if tm is not None else {},
                          getattr(w, '_series_uid_to_number', {}) or {}):
                    try:
                        if m and (s in m or series_uid in m):
                            return True
                    except Exception:
                        continue
                return False

            def _project_sibling_thumbnail(uid, series_uid, completed: bool) -> None:
                """Project a sibling-study series' download state onto its OWN thumbnail
                (resolved to the offset/display key via _resolve_sn). Touches ONLY the
                thumbnail-border lane — never series_downloaded, viewport progress, or a
                load trigger (those stay primary-study-only by design)."""
                w = widget_ref()
                if not w or not hasattr(w, "thumbnail_manager"):
                    return
                sn = _resolve_sn(series_uid)
                total = _sibling_total(uid, series_uid)
                try:
                    if completed:
                        w.thumbnail_manager.complete_series_download(
                            sn, total_images=total if total > 0 else None)
                    else:
                        w.thumbnail_manager.start_series_download(
                            sn, total_images=total if total > 0 else None)
                    _logger.info(
                        "[FAST-THUMB-SIBLING] %s study=%s series_uid=%s key=%s",
                        "complete" if completed else "start", uid, series_uid, sn,
                    )
                except Exception:
                    pass

            def _feed_thumb_bar(uid, series_uid, current, total):
                """Fill the matching series CARD's thin download bar (downloaded/total).

                Independent of whether any viewport shows the series — every open card
                for THIS patient (primary OR a multi-study sibling) fills as it
                downloads. Cross-patient safe: a series is admitted only when it is the
                primary study (uid == study_uid) or it resolves inside THIS patient's
                own uid->number map (_belongs_to_open_thumbnails); a foreign patient's
                background download is skipped. Throttled to ~1% steps; the bar repaint
                is a single cheap setValue() on one widget — no rebuild, no I/O.
                """
                try:
                    if uid != study_uid and not _belongs_to_open_thumbnails(series_uid):
                        return
                    total_i = int(total or 0)
                    cur_i = int(current or 0)
                    if total_i <= 0:
                        return
                    key = _resolve_sn(series_uid)
                    pct = int(cur_i * 100 / total_i)
                    if _last_thumb_bar_pct.get(key) == pct and cur_i < total_i:
                        return
                    _last_thumb_bar_pct[key] = pct
                    w = widget_ref()
                    tm = getattr(w, "thumbnail_manager", None) if w else None
                    if tm is None:
                        return
                    tm.update_series_download_progress(key, cur_i, total_i)
                except Exception:
                    pass

            def _flush():
                batch = list(_pending_completed)
                _pending_completed.clear()
                w = widget_ref()
                if not w:
                    return
                try:
                    _ = w.isVisible()
                except (RuntimeError, AttributeError):
                    return
                for sn in batch:
                    try:
                        if sn not in _thumbnail_completed_series and _complete_thumbnail_now(w, sn):
                            _thumbnail_completed_series.add(sn)
                        _emit_final_progress(w, sn)
                        if hasattr(w, "series_downloaded"):
                            w.series_downloaded.emit(sn)
                    except (RuntimeError, AttributeError):
                        break
                    except Exception:
                        pass

            def _flush_progress():
                batch = dict(_pending_progress)
                _pending_progress.clear()
                w = widget_ref()
                if not w:
                    return
                try:
                    _ = w.isVisible()
                except (RuntimeError, AttributeError):
                    return
                for sn, progress in batch.items():
                    current, total = progress
                    if _last_progress_sent.get(sn) == progress:
                        continue
                    if not _ui_should_admit(
                        "progress_update",
                        {
                            "key": f"viewer-progress:{connection_key}:{sn}",
                            "series_key": sn,
                        },
                    ):
                        _pending_progress[sn] = progress
                        interval_ms = int(max(100.0, _progress_update_interval_ms()))
                        if _progress_timer.interval() != interval_ms:
                            _progress_timer.setInterval(interval_ms)
                        if not _progress_timer.isActive():
                            _progress_timer.start()
                        continue
                    _last_progress_sent[sn] = progress
                    if hasattr(w, "series_images_progress"):
                        try:
                            w.series_images_progress.emit(sn, int(current), int(total))
                            if _logger.isEnabledFor(logging.DEBUG):
                                _pip_st = getattr(getattr(w, 'pipeline', None), 'state', '?')
                                _logger.debug(
                                    "[H7-P8-RECV] series=%s downloaded=%d total=%d pipeline_state=%s",
                                    sn, int(current), int(total),
                                    _pip_st.name if hasattr(_pip_st, 'name') else _pip_st,
                                )
                        except Exception:
                            pass
            _flush_timer.timeout.connect(_flush)
            _progress_timer.timeout.connect(_flush_progress)

            def on_study_progress(uid, current, total, percent):
                if uid != study_uid:
                    return
                w = widget_ref()
                if w and hasattr(w, "on_study_images_progress"):
                    try:
                        w.on_study_images_progress(current, total)
                    except Exception:
                        pass

            def on_series_started(uid, series_uid, series_desc):
                if uid != study_uid:
                    # Sibling-study real-time "downloading" THUMBNAIL border (thumbnail lane only).
                    if _belongs_to_open_thumbnails(series_uid):
                        _project_sibling_thumbnail(uid, series_uid, completed=False)
                    return
                sn = _resolve_sn(series_uid)
                _progress_normalizer.mark_started(sn)
                _thumbnail_completed_series.discard(sn)
                total_images = _resolve_series_total(sn)
                _t_dl_start = _time.perf_counter()
                _logger.info(
                    "[FAST-SERIES-DOWNLOAD-START] study=%s series=%s desc=%s",
                    uid, sn, series_desc,
                )
                _logger.info(
                    "FAST:download_start study=%s series=%s series_uid=%s t_abs=%.6f"
                    " note=delta_from_series_selected_not_available_here",
                    uid, sn, series_uid, _t_dl_start,
                )
                w = widget_ref()
                if w and hasattr(w, "thumbnail_manager"):
                    try:
                        w.thumbnail_manager.start_series_download(
                            sn,
                            total_images=total_images if total_images > 0 else None,
                        )
                    except Exception:
                        pass

            def _active_display_key_for_uid(series_uid):
                """Display key of a viewport in THIS patient's tab awaiting/progressively-displaying
                series_uid, else None. The cross-patient-safe admission gate for sibling-study grow
                events — the map comes solely from this patient's own server_series_info."""
                try:
                    w = widget_ref()
                    vc = getattr(w, "viewer_controller", None) if w else None
                    if vc is not None and hasattr(vc, "display_key_for_active_series_uid"):
                        return vc.display_key_for_active_series_uid(series_uid)
                except Exception:
                    pass
                return None

            def _grow_lane_display_key(uid, series_uid):
                """THE one display-key resolution for every DM grow-lane event (replaces the former
                flag-gated sibling-grow + uid-bind + per-branch re-keying — a single rule).

                Returns the display/offset key a viewport in THIS patient's tab is awaiting or
                progressively displaying for the globally-unique series_uid (cross-patient safe:
                resolved solely from this patient's own server_series_info); else, for the PRIMARY
                study, the canonical _resolve_sn number; else None for a background SECONDARY-study
                series no viewport here shows (it must not grow a viewport). PRIMARY / single-study
                stays byte-identical (display key == resolved number)."""
                dk = _active_display_key_for_uid(series_uid) if series_uid else None
                resolved = str(dk) if dk else (_resolve_sn(series_uid) if uid == study_uid else None)
                # VISIBLE diagnostic via the VIEWER logger (home_download's own `_logger` does NOT
                # reach the log files — console only). For a previous-exam / secondary-study event
                # whose resolved key is NOT one a viewport here awaits/shows, log the DM event's uid +
                # series_uid, what it resolved to, and each awaiting/progressive viewport key + the
                # series_uid stored for it in `_server_series_info`. One repro then shows whether the
                # offset key the viewport awaits (e.g. 1000001) maps to the SAME series_uid the DM
                # reports — pinpointing the previous-exam grow mismatch. (Diagnostic only; the return
                # value below is unchanged: dk if matched, else _resolve_sn for the primary, else None.)
                try:
                    _w = widget_ref()
                    _vc = getattr(_w, "viewer_controller", None) if _w else None
                    _lg = getattr(_vc, "logger", None) if _vc else None
                    if _lg is not None:
                        _ssi = getattr(getattr(_vc, "parent_widget", None), "_server_series_info", {}) or {}
                        _aw = []
                        for _n in (getattr(_vc, "lst_nodes_viewer", None) or []):
                            _vw = getattr(_n, "vtk_widget", None)
                            if _vw is None:
                                continue
                            for _at in ("_awaiting_series_number", "_progressive_series_number"):
                                _k = getattr(_vw, _at, None)
                                if _k:
                                    _info = _ssi.get(str(_k)) if isinstance(_ssi, dict) else None
                                    _u = (str((_info or {}).get("series_uid")
                                              or (_info or {}).get("series_instance_uid") or ""))[-20:]
                                    _aw.append((str(_k), _u))
                        if _aw and (resolved is None or str(resolved) not in [k for k, _ in _aw]):
                            _lg.info("[GROW-LANE-TRACE] uid=%s series_uid=%s resolved=%s awaiting=%s",
                                     str(uid)[-14:], str(series_uid or "")[-20:], resolved, _aw)
                except Exception:
                    pass
                return resolved

            def on_series_progress(uid, series_uid, current, total):
                # Per-card download bar: fill the matching thumbnail card's thin bar
                # for ANY open series of this patient (viewport-independent) BEFORE the
                # grow-lane resolution, which returns early for series no viewport shows.
                _feed_thumb_bar(uid, series_uid, current, total)
                # ONE display-key resolution (was: sibling-branch + primary-branch + uid-bind).
                sn = _grow_lane_display_key(uid, series_uid)
                if sn is None:
                    return  # background secondary-study series — no viewport here shows it
                allowed, reason = _progress_normalizer.should_emit_progress(
                    sn,
                    int(current),
                    int(total),
                )
                if not allowed:
                    _logger.debug(
                        "[FAST-SERIES-DOWNLOAD-PROGRESS-DROP] study=%s series=%s current=%d total=%d reason=%s",
                        uid, sn, int(current), int(total), reason,
                    )
                    _pending_progress.pop(sn, None)
                    return
                if reason == "new_partial_cycle":
                    _thumbnail_completed_series.discard(sn)
                    w_restart = widget_ref()
                    if w_restart and hasattr(w_restart, "thumbnail_manager"):
                        try:
                            total_images = _resolve_series_total(sn)
                            fallback_total = int(total) if int(total) > 0 else None
                            w_restart.thumbnail_manager.start_series_download(
                                sn,
                                total_images=total_images if total_images > 0 else fallback_total,
                            )
                        except Exception:
                            pass
                pct = (current / total * 100) if total > 0 else 0
                _logger.debug(
                    "[FAST-SERIES-DOWNLOAD-PROGRESS] study=%s series=%s percent=%.0f images=%d/%d",
                    uid, sn, pct, current, total,
                )
                w = widget_ref()
                if not w:
                    return
                # [H10-3] Canonical DM active series — log on transition only
                _prev_dm = getattr(w, '_h10_dm_active_series', None)
                if _prev_dm != sn:
                    _logger.info(
                        "[H10-3] DM_SERIES_TRANSITION fn=on_series_progress prev=%s new=%s",
                        _prev_dm, sn,
                    )
                    w._h10_dm_active_series = sn
                progress = (int(current), int(total))
                if _last_progress_sent.get(sn) == progress and sn not in _pending_progress:
                    return
                _pending_progress[sn] = progress
                interval_ms = int(max(100.0, _progress_update_interval_ms()))
                if _progress_timer.interval() != interval_ms:
                    _progress_timer.setInterval(interval_ms)
                if not _progress_timer.isActive():
                    _progress_timer.start()

            def on_series_completed(uid, series_uid):
                if not widget_ref():
                    return
                # Sibling-study real-time "ready" THUMBNAIL border (thumbnail lane only; the PRIMARY
                # study's thumbnail completion is handled inside _on_series_completed_impl).
                if uid != study_uid and _belongs_to_open_thumbnails(series_uid):
                    _project_sibling_thumbnail(uid, series_uid, completed=True)
                # GROW finalize via the SAME one display-key resolution as progress: PRIMARY →
                # resolved number; a SECONDARY-study series a viewport here shows → its display key;
                # a background sibling → None (skip the grow — its thumbnail already updated above).
                sn = _grow_lane_display_key(uid, series_uid)
                if sn is None:
                    return
                with _g6_time_slot("home_download.on_series_completed", series=str(sn)):
                    _on_series_completed_impl(uid, sn)

            def _on_series_completed_impl(uid, sn):
                if not _progress_normalizer.mark_completed(sn):
                    _logger.debug(
                        "[FAST-SERIES-DOWNLOAD-COMPLETE-DROP] study=%s series=%s reason=duplicate_completion",
                        uid, sn,
                    )
                    return
                _logger.info(
                    "[FAST-SERIES-DOWNLOAD-COMPLETE] study=%s series=%s",
                    uid, sn,
                )
                # [H10-3] Canonical DM active series — log completion transition
                w_c = widget_ref()
                if w_c:
                    _prev_dm = getattr(w_c, '_h10_dm_active_series', None)
                    if _prev_dm != sn:
                        _logger.info(
                            "[H10-3] DM_SERIES_TRANSITION fn=on_series_completed prev=%s new=%s",
                            _prev_dm, sn,
                        )
                    w_c._h10_dm_active_series = sn
                    if sn not in _thumbnail_completed_series and _complete_thumbnail_now(w_c, sn):
                        _thumbnail_completed_series.add(sn)
                if not _first_emitted["done"]:
                    _first_emitted["done"] = True
                    _flush_timer.stop()
                    _progress_timer.stop()
                    _pending_completed.clear()
                    _pending_progress.pop(sn, None)
                    _last_progress_sent.pop(sn, None)
                    try:
                        w = widget_ref()
                        if w:
                            if sn not in _thumbnail_completed_series and _complete_thumbnail_now(w, sn):
                                _thumbnail_completed_series.add(sn)
                            _emit_final_progress(w, sn)
                            if hasattr(w, "series_downloaded"):
                                w.series_downloaded.emit(sn)
                    except Exception:
                        pass
                    return
                _pending_progress.pop(sn, None)
                _last_progress_sent.pop(sn, None)
                _pending_completed.append(sn)
                if not _flush_timer.isActive():
                    _flush_timer.start()

            dm.studyProgressUpdated.connect(on_study_progress)
            dm.seriesDownloadStarted.connect(on_series_started)
            dm.seriesProgressUpdated.connect(on_series_progress)
            dm.seriesDownloadCompleted.connect(on_series_completed)

            handlers = {
                "studyProgressUpdated": on_study_progress,
                "seriesDownloadStarted": on_series_started,
                "seriesProgressUpdated": on_series_progress,
                "seriesDownloadCompleted": on_series_completed,
            }
            record = _ConnectionRecord(
                dm=dm,
                widget_ref=widget_ref,
                handlers=handlers,
                flush_timer=_flush_timer,
                progress_timer=_progress_timer,
                key=connection_key,
            )
            self._dm_widget_connections[connection_key] = record
            # [H7-P8] DM signal wiring checkpoint
            _has_workers = bool(getattr(dm, '_active_workers', None))
            _logger.info(
                "[H7-P8] study=%s wiring_complete=True dm_has_active_workers=%s "
                "connection_key=%s",
                study_uid, _has_workers, connection_key,
            )
        except Exception as exc:
            _logger.exception(
                "[DM] Error connecting signals for study=%s: %s",
                study_uid,
                exc,
            )

    # ------------------------------------------------------------------
    # Lifecycle: disconnect / cleanup
    # ------------------------------------------------------------------

    def disconnect_widget(self, widget) -> int:
        """Disconnect all DM signals wired to *widget*.

        Call this when a patient tab is closed to prevent stale callbacks.
        Returns the number of connections removed.
        """
        widget_id = id(widget)
        to_remove = [
            k for k, rec in self._dm_widget_connections.items()
            if k.endswith(f"_{widget_id}")
        ]
        removed = 0
        for key in to_remove:
            self._disconnect_record(key)
            removed += 1
        return removed

    def _disconnect_record(self, key: str) -> None:
        """Disconnect a single connection record by key."""
        rec = self._dm_widget_connections.pop(key, None)
        if rec is None:
            return
        # Stop and discard the flush timer
        try:
            if rec.flush_timer is not None:
                rec.flush_timer.stop()
                rec.flush_timer.timeout.disconnect()
        except (RuntimeError, TypeError):
            pass
        try:
            if rec.progress_timer is not None:
                rec.progress_timer.stop()
                rec.progress_timer.timeout.disconnect()
        except (RuntimeError, TypeError):
            pass

        # Disconnect DM signals
        signal_map = {
            "studyProgressUpdated": rec.dm.studyProgressUpdated,
            "seriesDownloadStarted": rec.dm.seriesDownloadStarted,
            "seriesProgressUpdated": rec.dm.seriesProgressUpdated,
            "seriesDownloadCompleted": rec.dm.seriesDownloadCompleted,
        }
        for sig_name, handler in rec.handlers.items():
            try:
                signal_map[sig_name].disconnect(handler)
            except (RuntimeError, TypeError, KeyError):
                pass

        _logger.debug("[DM] Disconnected connection_key=%s", key)

    def cleanup(self) -> None:
        """Deterministic teardown — call on service / app shutdown.

        Safe to call multiple times (idempotent).
        """
        if self._cleaned_up:
            return
        self._cleaned_up = True
        keys = list(self._dm_widget_connections.keys())
        for key in keys:
            self._disconnect_record(key)
        self._dm_widget_connections.clear()

        try:
            for i in range(self.tab_widget.count()):
                widget = self.tab_widget.widget(i)
                if isinstance(widget, DownloadManagerWidget) and hasattr(widget, "cleanup"):
                    widget.cleanup()
        except Exception:
            _logger.exception("[DM] Failed to cleanup DownloadManagerWidget from HomeDownloadService")

        _logger.debug("[DM] HomeDownloadService cleanup complete")

    # ------------------------------------------------------------------
    # Zeta-boost global flag
    # ------------------------------------------------------------------

    @staticmethod
    def refresh_global_download_flag() -> None:
        """Set/clear global download-active flag for ZetaBoost warmup throttle."""
        try:
            from modules.download_manager.state.state_store import get_state_store
            from modules.zeta_boost.engine import set_global_download_active
            active = bool(get_state_store().get_active_downloads())
            set_global_download_active(active)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _activate_tab(self, index: int) -> None:
        if self.custom_tab_manager:
            try:
                self.custom_tab_manager.set_tab_active_simple(index)
                return
            except Exception:
                pass
        self.tab_widget.setCurrentIndex(index)
