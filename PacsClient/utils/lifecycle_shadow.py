"""Stage-1 SHADOW observer for the canonical patient-load lifecycle.

Wires the pure ``patient_load_lifecycle.PatientLoadModel`` into the live
home-panel thumbnail path WITHOUT changing any behavior, so the model's
correctness can be proven on the source build BEFORE the behavior cutover
(the "shadow, then cutover" step in
``docs/reports/PATIENT_LOADING_PIPELINE_RELIABILITY_REVIEW_2026-07-02.md`` §11).

CONTRACT — this module is telemetry only:
  * Default **OFF**. Enabled only when ``AIPACS_LIFECYCLE_THUMBS`` is one of
    ``shadow`` / ``observe`` / ``on`` / ``1``. When OFF every method is a
    no-op and the legacy path is byte-identical.
  * It NEVER renders, cancels, discards, downloads, or mutates any widget /
    viewer / download state. It only updates an in-memory model and writes log
    lines (``[LIFECYCLE]`` transitions and ``[LIFECYCLE-SHADOW]`` observations).
  * Every public method swallows ALL exceptions — instrumentation must never be
    able to break the clinical path.

The value: with the flag on, the log shows for every patient click whether the
model reached ``THUMBS_READY``, and — crucially — that when the legacy path
DISCARDS a fetch (stale token / inactive / cancel), the model still holds the
study's series set PARKED (the Problem #1 fix), i.e. nothing was actually lost.
No import of Qt / VTK — pure stdlib + the pure lifecycle authority.
"""
from __future__ import annotations

import logging
import os
import time
from typing import Any, Iterable, Optional

_logger = logging.getLogger("aipacs.lifecycle_shadow")

_ENABLED_VALUES = {"shadow", "observe", "on", "1", "true", "yes"}

# Per-key log throttle interval (seconds). The MODEL is updated on every event;
# only the verbose per-progress log lines are rate-limited so multi-tab sessions
# don't flood app.log (e.g. 9,346 benign cross-tab grow_lane_drop lines / session).
try:
    _LOG_INTERVAL_S = max(0.0, float(os.getenv("AIPACS_LIFECYCLE_LOG_INTERVAL_S", "1.0")))
except Exception:
    _LOG_INTERVAL_S = 1.0
_LOG_TS_CAP = 4000  # bound the throttle map for a long default-ON session


def _mode() -> str:
    # DEFAULT ON (2026-07-02): the observer is telemetry only (exception-safe,
    # bounded model) and is enabled by default so a new build carries the
    # diagnostics for the other-PC test. Kill switch: AIPACS_LIFECYCLE_THUMBS=0.
    return str(os.getenv("AIPACS_LIFECYCLE_THUMBS", "on") or "on").strip().lower()


def is_enabled() -> bool:
    """True when the shadow observer should run (DEFAULT ON; kill switch =0)."""
    return _mode() in _ENABLED_VALUES


class LifecycleShadow:
    """Owns one :class:`PatientLoadModel` and feeds it from the live path."""

    def __init__(self) -> None:
        self._model = None  # lazily built so a disabled build imports nothing heavy
        self._active = is_enabled()
        self._watchdog_counts: dict = {}
        self._log_ts: dict = {}  # per-key last-log time (verbose-line throttle)

    def _should_log(self, key, interval: float = _LOG_INTERVAL_S) -> bool:
        """Rate-limit a verbose log line per key (the model still updates every
        event; only the log is throttled). Bounded for long sessions."""
        try:
            now = time.monotonic()
            last = self._log_ts.get(key, 0.0)
            if now - last < interval:
                return False
            if len(self._log_ts) > _LOG_TS_CAP:
                self._log_ts.clear()
            self._log_ts[key] = now
            return True
        except Exception:
            return True

    # -- internal ----------------------------------------------------------
    def _ensure_model(self):
        if self._model is None:
            # Imported lazily and defensively; a failure here just disables shadow.
            from PacsClient.utils.patient_load_lifecycle import (
                PatientLoadModel,
                format_transition,
            )

            def _log_transition(t):
                try:
                    _logger.info(format_transition(t))
                except Exception:
                    pass

            self._model = PatientLoadModel(on_transition=_log_transition)
        return self._model

    @staticmethod
    def _series_ids(study_uid: str, series_items: Iterable[Any]):
        from PacsClient.utils.patient_load_lifecycle import CanonicalSeriesId

        out = []
        expected = {}
        for s in series_items or []:
            if isinstance(s, dict):
                num = s.get("series_number") or s.get("SeriesNumber") or ""
                uid = (
                    s.get("series_uid")
                    or s.get("series_instance_uid")
                    or s.get("SeriesInstanceUID")
                    or ""
                )
                img = s.get("image_count") or s.get("ImageCount") or 0
            else:
                num = getattr(s, "series_number", "") or ""
                uid = getattr(s, "series_uid", "") or ""
                img = getattr(s, "image_count", 0) or 0
            cid = CanonicalSeriesId(str(study_uid or ""), str(num), str(uid))
            out.append(cid)
            try:
                if int(img or 0) > 0:
                    expected[cid.key()] = int(img)
            except Exception:
                pass
        return out, expected

    # -- public observation points (all no-op when disabled / on error) ----
    def note_selection(self, patient_id: Any, study_uid: Any, *, open_intent: bool = False) -> None:
        if not self._active:
            return
        try:
            from PacsClient.utils.patient_study_set import Intent

            intent = Intent.OPEN_VIEWER if open_intent else Intent.PREVIEW_ONLY
            self._ensure_model().on_selection(str(patient_id or ""), str(study_uid or ""), intent)
        except Exception:
            pass

    def note_series_set(self, study_uid: Any, series_items: Iterable[Any]) -> None:
        if not self._active:
            return
        try:
            model = self._ensure_model()
            if model.study(str(study_uid or "")) is None:
                # A render can arrive before a selection was observed; register it.
                model.on_selection("", str(study_uid or ""), _preview_intent())
            ids, expected = self._series_ids(str(study_uid or ""), series_items)
            model.on_series_set(str(study_uid or ""), ids, expected=expected)
        except Exception:
            pass

    def note_thumbs_rendered(self, study_uid: Any) -> None:
        if not self._active:
            return
        try:
            self._ensure_model().mark_thumbs_rendered(str(study_uid or ""))
        except Exception:
            pass

    def note_discard(self, study_uid: Any, reason: Any) -> None:
        """The legacy path just DISCARDED a fetch result. Log that the model still
        holds the study parked — i.e. the data was not actually lost."""
        if not self._active:
            return
        try:
            model = self._ensure_model()
            study = model.study(str(study_uid or ""))
            stage = study.stage.value if study is not None else "unknown"
            n = len(study.series) if study is not None else 0
            _logger.info(
                "[LIFECYCLE-SHADOW] legacy_discard reason=%s study=%s "
                "model_stage=%s parked_series=%d (data retained in model)",
                str(reason), str(study_uid or "")[-16:], stage, n,
            )
        except Exception:
            pass

    # -- Seam B (previous-exam grow): DM download progress/completion ---------
    def note_download_progress(self, primary_study_uid: Any, uid: Any, series_uid: Any,
                               current: Any, total: Any, *, dropped: bool = False) -> None:
        """Feed one DM progress event into the model, keyed by the series' OWN
        study_uid (`uid`) — so a previous-exam / secondary-study series is
        first-class. When the legacy grow lane DROPPED it (``sn is None``), log
        that the model still received the progress and would grow the viewport.
        Telemetry only."""
        if not self._active:
            return
        try:
            from PacsClient.utils.patient_load_lifecycle import CanonicalSeriesId

            model = self._ensure_model()
            su = str(uid or "")
            if model.study(su) is None:
                model.on_selection("", su, _open_intent())
            cid = CanonicalSeriesId(su, "", str(series_uid or ""))
            exp = int(total or 0)
            model.on_series_set(su, [cid], expected={cid.key(): exp} if exp > 0 else None)
            action = model.on_disk_change(su, cid, int(current or 0),
                                          expected=exp if exp > 0 else None)
            # Throttle the verbose per-progress log (the model already updated
            # above). Benign multi-tab cross-study drops otherwise flood app.log.
            if dropped and self._should_log(("grow_lane_drop", su, str(series_uid or ""))):
                rec = model.study(su).series.get(cid.key())
                _logger.info(
                    "[LIFECYCLE-SHADOW] grow_lane_drop primary=%s series_study=%s "
                    "series=%s on_disk=%d/%d model_action=%s disk_complete=%s "
                    "(legacy dropped: sn is None; throttled)",
                    str(primary_study_uid or "")[-16:], su[-16:],
                    str(series_uid or "")[-12:], int(current or 0), exp,
                    getattr(action, "value", action),
                    rec.disk_complete if rec is not None else "?",
                )
        except Exception:
            pass

    def note_download_complete(self, primary_study_uid: Any, uid: Any, series_uid: Any,
                               *, dropped: bool = False) -> None:
        """Mark a series disk-complete in the model on DM completion (keyed by the
        series' own study_uid). Logs when the legacy grow lane dropped it."""
        if not self._active:
            return
        try:
            from PacsClient.utils.patient_load_lifecycle import CanonicalSeriesId

            model = self._ensure_model()
            su = str(uid or "")
            if model.study(su) is None:
                model.on_selection("", su, _open_intent())
            cid = CanonicalSeriesId(su, "", str(series_uid or ""))
            model.on_series_set(su, [cid])
            rec = model.study(su).series.get(cid.key())
            on = max(rec.on_disk if rec else 0, rec.expected if rec else 0, 1)
            # feed twice with no .part so the expected-unknown case settles complete
            model.on_disk_change(su, cid, on, has_part=False,
                                 expected=(rec.expected if rec and rec.expected else None))
            action = model.on_disk_change(su, cid, on, has_part=False)
            if dropped:
                _logger.info(
                    "[LIFECYCLE-SHADOW] grow_lane_drop_complete primary=%s series_study=%s "
                    "series=%s on_disk=%d model_action=%s (legacy dropped: sn is None)",
                    str(primary_study_uid or "")[-16:], su[-16:],
                    str(series_uid or "")[-12:], on, getattr(action, "value", action),
                )
        except Exception:
            pass

    def note_download_failed(self, uid: Any, series_uid: Any = None,
                             cause: str = "retry_exhausted") -> None:
        """Record an authoritative download failure (e.g. retry exhausted on a poor
        link) as a FAILED terminal in the model — the state the legacy path lacks.
        ``series_uid=None`` fails every known series of the study."""
        if not self._active:
            return
        try:
            from PacsClient.utils.patient_load_lifecycle import CanonicalSeriesId

            model = self._ensure_model()
            su = str(uid or "")
            if model.study(su) is None:
                model.on_selection("", su, _open_intent())
            if series_uid:
                cid = CanonicalSeriesId(su, "", str(series_uid))
                model.on_series_set(su, [cid])
                model.on_failure(su, cid, cause)
            else:
                study = model.study(su)
                cids = [r.canonical for r in study.series.values()] if study else []
                if not cids:
                    cid = CanonicalSeriesId(su, "0", "")
                    model.on_series_set(su, [cid])
                    cids = [cid]
                for c in cids:
                    model.on_failure(su, c, cause)
            _logger.info(
                "[LIFECYCLE-SHADOW] download_failed study=%s series=%s cause=%s "
                "(model -> FAILED, legacy has no failure terminal)",
                su[-16:], str(series_uid or "all")[-12:], cause,
            )
        except Exception:
            pass

    # -- Seam C (convergence): observe the GUI-thread polling backstop ---------
    def note_watchdog_activity(self, kind: Any, series_key: Any = None) -> None:
        """Record one firing of the GUI-thread ``_dl_watchdog_tick`` backstop —
        a disk-readiness ``resume`` or a displayed-to-disk ``grow``. This is the
        exact work the deterministic, off-GUI-thread convergence sweep
        (``PatientLoadModel.non_terminal_series`` + ``reconcile_series``) would
        own instead. Counting it live quantifies the Seam-C win. Telemetry only."""
        if not self._active:
            return
        try:
            k = str(kind or "?")
            self._watchdog_counts[k] = self._watchdog_counts.get(k, 0) + 1
            _logger.info(
                "[LIFECYCLE-SHADOW] watchdog_%s series=%s total_%s=%d "
                "(GUI-thread backstop; convergence sweep would own this)",
                k, str(series_key or "")[-12:], k, self._watchdog_counts[k],
            )
        except Exception:
            pass


def _open_intent() -> str:
    try:
        from PacsClient.utils.patient_study_set import Intent
        return Intent.OPEN_VIEWER
    except Exception:
        return "open_viewer"


def _preview_intent() -> str:
    try:
        from PacsClient.utils.patient_study_set import Intent
        return Intent.PREVIEW_ONLY
    except Exception:
        return "preview_only"


_SINGLETON: Optional[LifecycleShadow] = None


def get_lifecycle_shadow() -> LifecycleShadow:
    """Process-wide shadow observer (cheap no-op object when the flag is off)."""
    global _SINGLETON
    if _SINGLETON is None:
        _SINGLETON = LifecycleShadow()
    return _SINGLETON
