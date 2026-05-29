"""Bus fixture for scenario tests under tests/gui/echomind_driven/.

The fixture builds a CommandBus backed by a FAKE home adapter so tests
run in CI without a real AI-PACS window. When the source build IS
detected, a marker selects the live-bus fixture instead, exercising the
same test code against the real adapter.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

# Make sure project root is importable
_PROJECT_ROOT = str(Path(__file__).resolve().parents[3])
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

try:
    import pytest
except ImportError:
    pytest = None  # type: ignore

from modules.EchoMind.secretary import (
    AdapterRegistry, CommandBus, CommandPlan, CommandResult,
)


# ───────────────────────────────────────────────────────────────────
# Fake home adapter — mimics socket latency for KPI tests
# ───────────────────────────────────────────────────────────────────

class FakeHomeAdapter:
    """In-memory stand-in for the real HomeWidgetAdapter.

    Each method sleeps for a tunable delay so KPI tests can simulate
    socket latency without a real server. Defaults match the post-fix
    target (~150 ms per right_panel_socket round-trip).
    """

    def __init__(self, *, per_open_ms: float = 150.0,
                 per_search_ms: float = 200.0):
        self.per_open_ms = per_open_ms
        self.per_search_ms = per_search_ms
        self.queue: list[str] = []
        self.opened: list[str] = []
        self.searched_count = 0

    def list_patients(self, plan: CommandPlan, state: dict) -> CommandResult:
        time.sleep(self.per_search_ms / 1000.0)
        self.searched_count += 1
        # Synthesize 20 fake rows so bulk-download has something to chew on.
        rows = [
            {"patient_id": f"4365{i:02d}", "patient_name": f"FAKE{i}",
             "modality": (plan.entities or {}).get("modality", "MR")}
            for i in range(20)
        ]
        return CommandResult(
            ok=True, action="list_patients",
            message=f"Listed {len(rows)} patients (fake)",
            data={"rows": rows, "count": len(rows)},
        )

    def open_patient(self, plan: CommandPlan, state: dict) -> CommandResult:
        time.sleep(self.per_open_ms / 1000.0)
        pid = (plan.entities or {}).get("patient_id", "")
        self.opened.append(str(pid))
        return CommandResult(
            ok=True, action="open_patient",
            message=f"Opened patient {pid} (fake)",
            data={"patient_id": pid, "series_count": 7},
        )

    def download_patient(self, plan: CommandPlan, state: dict) -> CommandResult:
        ent = plan.entities or {}
        ids = ent.get("patient_ids") or [ent.get("patient_id")]
        ids = [str(x) for x in ids if x]
        # Parallel prefetch fix: this branch simulates the *post*-fix
        # behavior (a flat ~150 ms per study, regardless of count, because
        # the ThreadPoolExecutor masks the per-fetch latency under the
        # max(N) bound).
        time.sleep(0.15)
        self.queue.extend(ids)
        return CommandResult(
            ok=True, action="download_patient",
            message=f"Enqueued {len(ids)} downloads (fake)",
            data={"patient_ids": ids, "count": len(ids),
                  "queue_size": len(self.queue)},
        )


# ───────────────────────────────────────────────────────────────────
# Bus fixture
# ───────────────────────────────────────────────────────────────────

def make_fake_bus(*, per_open_ms: float = 150.0,
                  per_search_ms: float = 200.0) -> CommandBus:
    """Build a CommandBus wired to a FakeHomeAdapter — CI-friendly."""
    fake = FakeHomeAdapter(per_open_ms=per_open_ms, per_search_ms=per_search_ms)
    registry = AdapterRegistry()
    registry.register(
        "home",
        fake,
        actions={
            "list_patients": "list_patients",
            "open_patient": "open_patient",
            "download_patient": "download_patient",
        },
    )
    bus = CommandBus(registry=registry, orchestrator=None)
    # Expose the fake adapter for assertions in tests.
    bus._fake = fake  # type: ignore[attr-defined]
    return bus


if pytest is not None:
    @pytest.fixture
    def bus():
        """The default fixture — fake home adapter, CI-runnable."""
        return make_fake_bus()


    @pytest.fixture
    def fake_home(bus):
        """Direct handle to the fake home adapter (for assertions)."""
        return bus._fake



    @pytest.fixture
    def live_bus():
        """Live-build bus fixture — yields the running app's CommandBus
        when the source build is detected, else SKIPs the test.

        Lets the same scenario test exercise either the FakeHomeAdapter
        (``bus`` fixture, CI-safe) or the live home_widget (``live_bus``
        fixture, source-build only). Migrate a scenario test to live by
        changing the fixture name in the test signature.
        """
        # 1. Source-build pre-flight (same gate the pywinauto tests use).
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "live_walkthroughs"))
        try:
            from _verify_source_build import (  # type: ignore
                require_source_build, WrongBuildError,
            )
        except Exception as exc:
            pytest.skip(f"verify_source_build helper not importable: {exc}")
        try:
            require_source_build(recent_seconds=300, require_python_exe=False)
        except WrongBuildError as exc:
            pytest.skip(f"source build not detected: {exc}")

        # 2. The secretary bridge exposes the live home widget.
        try:
            from modules.EchoMind.secretary_bridge import get_runtime_home_widget
        except Exception as exc:
            pytest.skip(f"secretary_bridge not importable: {exc}")
        home = get_runtime_home_widget()
        if home is None:
            pytest.skip("home widget not constructed yet — wait for startup")

        bus = getattr(home, "command_bus", None)
        if bus is None:
            pytest.skip("home_widget.command_bus is None — wire-up failed at startup")

        return bus
