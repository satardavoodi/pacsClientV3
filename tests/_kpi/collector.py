"""KPI collector — context manager + pytest fixture + bus hook.

Test code:

    from tests._kpi import kpi

    def test_open_patient_kpi(bus, kpi):
        with kpi.measure("patient_open"):
            result = bus.execute(plan)
        kpi.record("patient_open.elapsed_ms", result.elapsed_ms)

The collector:
- Records every emitted value to a JSONL sink under
  ``user_data/test_kpis/<run_id>.jsonl``.
- Checks each value against the threshold registered in
  ``tests/_kpi/schema.py``. ``hard`` violations raise
  ``KpiHardThresholdError`` (the test fails). ``warn`` violations are
  logged and surface in the reporter without failing the test.
- Can auto-record from CommandBus results when ``hook_bus(bus)`` is
  called — useful in scenario fixtures.

See ``docs/plans/architecture/TESTING_ARCHITECTURE_2026-05-28.md`` §9.
"""
from __future__ import annotations

import contextlib
import json
import logging
import os
import socket
import time
import uuid
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from .schema import KpiSpec, KPI_REGISTRY, get_spec, UnknownKpiError

logger = logging.getLogger(__name__)


class KpiHardThresholdError(AssertionError):
    """Raised when a KPI value exceeds the registered ``hard`` threshold."""


@dataclass
class KpiVerdict:
    key: str
    value: float
    spec: KpiSpec
    verdict: str   # "PASS" | "WARN" | "FAIL"


# ---------------------------------------------------------------------------

def _hostname() -> str:
    try:
        return socket.gethostname()
    except Exception:
        return "unknown"


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _default_sink_dir() -> Path:
    return _project_root() / "user_data" / "test_kpis"


def _new_run_id(slug: Optional[str] = None) -> str:
    ts = datetime.now().strftime("%Y-%m-%d-%H-%M")
    tag = slug or "run"
    return f"{ts}-{tag}-{uuid.uuid4().hex[:6]}"


# ---------------------------------------------------------------------------

class KpiCollector:
    """The collector. One per pytest session by default."""

    def __init__(
        self,
        sink_dir: Optional[Path] = None,
        run_id: Optional[str] = None,
        git_sha: str = "",
        build_kind: str = "source",
    ):
        self.sink_dir = sink_dir or _default_sink_dir()
        self.run_id = run_id or _new_run_id()
        self.git_sha = git_sha or os.environ.get("AIPACS_GIT_SHA", "")
        self.build_kind = build_kind
        self.host = _hostname()
        self.verdicts: list[KpiVerdict] = []
        self._sink_dir_created = False

    # ── measurement context manager ──────────────────────────────────
    @contextlib.contextmanager
    def measure(self, workflow: str, *, labels: Optional[dict[str, Any]] = None):
        """Time a block and stash the elapsed_ms for the next ``record`` call.

        Usage::
            with kpi.measure("patient_open"):
                result = bus.execute(plan)
            kpi.record("patient_open.elapsed_ms", result.elapsed_ms or last_elapsed)

        The block doesn't auto-record — the test does, with whichever
        canonical value it chose (bus.elapsed_ms, wall-clock, server
        round-trip, etc.). This keeps test intent explicit.
        """
        t0 = time.monotonic()
        try:
            yield
        finally:
            self._last_elapsed_ms = (time.monotonic() - t0) * 1000.0
            self._last_workflow = workflow
            self._last_labels = labels or {}

    # ── recording ────────────────────────────────────────────────────
    def record(
        self,
        key: str,
        value: float,
        *,
        labels: Optional[dict[str, Any]] = None,
        test_id: Optional[str] = None,
    ) -> KpiVerdict:
        spec = get_spec(key)  # raises UnknownKpiError if not registered

        verdict = self._evaluate(spec, value)
        v = KpiVerdict(key=key, value=float(value), spec=spec, verdict=verdict)
        self.verdicts.append(v)

        record = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "run_id": self.run_id,
            "test_id": test_id or os.environ.get("PYTEST_CURRENT_TEST", ""),
            "key": key,
            "value": float(value),
            "unit": spec.unit,
            "workflow": spec.workflow,
            "threshold_hard": spec.hard,
            "threshold_warn": spec.warn,
            "higher_better": spec.higher_better,
            "verdict": verdict,
            "host": self.host,
            "git_sha": self.git_sha,
            "build_kind": self.build_kind,
            "labels": labels or {},
        }
        self._append_record(record)

        if verdict == "FAIL":
            raise KpiHardThresholdError(
                f"KPI {key} = {value:.2f} {spec.unit} violates hard threshold "
                f"({spec.hard} {spec.unit}, higher_better={spec.higher_better})"
            )
        if verdict == "WARN":
            logger.warning(
                "KPI %s = %.2f %s exceeds warning threshold (%s)",
                key, value, spec.unit, spec.warn,
            )
        return v

    # ── verdict logic ────────────────────────────────────────────────
    @staticmethod
    def _evaluate(spec: KpiSpec, value: float) -> str:
        if spec.higher_better:
            if spec.hard is not None and value < spec.hard:
                return "FAIL"
            if spec.warn is not None and value < spec.warn:
                return "WARN"
            return "PASS"
        if spec.hard is not None and value > spec.hard:
            return "FAIL"
        if spec.warn is not None and value > spec.warn:
            return "WARN"
        return "PASS"

    # ── sink ─────────────────────────────────────────────────────────
    def _append_record(self, record: dict) -> None:
        if not self._sink_dir_created:
            try:
                self.sink_dir.mkdir(parents=True, exist_ok=True)
                self._sink_dir_created = True
            except Exception as exc:
                logger.warning("KPI sink dir create failed: %s — skipping", exc)
                return
        path = self.sink_dir / f"{self.run_id}.jsonl"
        try:
            with path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        except Exception as exc:
            logger.warning("KPI sink write failed (%s): %s", path, exc)

    # ── bus hook (auto-record from CommandResult) ───────────────────
    def hook_bus(self, bus: Any) -> None:
        """Auto-record bus.execute() results as ``<action>.elapsed_ms``.

        Only KPIs whose key is in the registry are recorded; unknown
        action names are silently skipped (the bus already wraps all
        unknowns as UNKNOWN_ACTION envelopes).
        """
        if getattr(bus, "_kpi_hooked", False):
            return
        original = bus.execute

        def _hooked_execute(plan, state=None):
            result = original(plan, state)
            try:
                action = getattr(result, "action", None)
                elapsed = getattr(result, "elapsed_ms", None)
                if action and elapsed is not None:
                    key = f"{action}.elapsed_ms"
                    if key in KPI_REGISTRY:
                        # Don't crash a test on threshold violation for
                        # auto-recorded values — let the test's own
                        # explicit record() be the gate.
                        try:
                            self.record(key, elapsed)
                        except KpiHardThresholdError:
                            logger.warning("hooked KPI threshold violation "
                                           "suppressed for %s", key)
            except Exception:
                logger.debug("KPI bus hook record failed", exc_info=True)
            return result

        bus.execute = _hooked_execute  # type: ignore[assignment]
        bus._kpi_hooked = True
        bus._kpi_original_execute = original

    # ── reporting ────────────────────────────────────────────────────
    def summary(self) -> dict[str, int]:
        out = {"PASS": 0, "WARN": 0, "FAIL": 0}
        for v in self.verdicts:
            out[v.verdict] = out.get(v.verdict, 0) + 1
        return out


# ---------------------------------------------------------------------------
# pytest fixture wrapper
# ---------------------------------------------------------------------------

try:
    import pytest  # type: ignore
except ImportError:  # pragma: no cover
    pytest = None  # type: ignore


if pytest is not None:
    @pytest.fixture(scope="session")
    def kpi_session():
        """Session-scoped collector shared by every test."""
        collector = KpiCollector()
        yield collector
        # End-of-session summary in the captured log.
        s = collector.summary()
        logger.info("KPI summary for run_id=%s: PASS=%d WARN=%d FAIL=%d",
                    collector.run_id, s.get("PASS", 0),
                    s.get("WARN", 0), s.get("FAIL", 0))

    @pytest.fixture
    def kpi(kpi_session):
        """Per-test handle to the session collector."""
        return kpi_session
else:
    kpi = None  # type: ignore


__all__ = [
    "KpiCollector", "KpiVerdict", "KpiHardThresholdError",
    "kpi", "UnknownKpiError",
]
