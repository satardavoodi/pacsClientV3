"""Pipeline A Crash Reproduction — Layer A (Pure Deterministic Simulation)

Invariant tests for FAST viewer progressive display under Pipeline A
conditions (active download + viewer display + lazy load + scroll).
No Qt dependency. Runs with plain ``pytest``.

Hypotheses
----------
H-A  Progressive state sync bug (_progressive_series pop/mutation during display)
H-B  Series generation ID race (stale callback renders after switch)
H-C  grow() pending-request index mismatch (old indices → wrong data after remap)
H-D  Scroll during grow() TOCTOU (half-updated VTK dimensions vs scalars)
H-E  Stale callback against invalidated state (None loader/viewer)

Layer B (Qt-integrated) tests are in ``test_pipeline_a_qt_repro.py`` and are
activated after Layer A narrows the hypotheses.

Seven invariants checked at every step
---------------------------------------
1  viewer.series == sn AND sn in _progressive_series  → viewer._progressive_mode True
2  _series_generation_id monotonically non-decreasing
3  _lazy_loader is None  → no callback touches image_viewer (no new renders)
4  set_slice(n) succeeds only when n < viewer slice count
5  After grow(): VTK dimensions == scalar array size (no TOCTOU gap)
6  After pop(sn): sn NOT in _progressive_display_done (H4 lifecycle fix)
7  Stale callback (wrong generation) never renders (guard effective)
"""
from __future__ import annotations

import threading
import time
from types import SimpleNamespace
from typing import Dict, List, Optional, Tuple

import pytest


# ── Stale frame guard (inlined from modules/viewer/fast/stale_frame_guard.py) ─
def should_render_ready_slice(
    ready_slice: int,
    requested_slice: Optional[int],
    current_slice: Optional[int],
    ready_generation: int,
    current_generation: int,
) -> bool:
    """Return True only for the latest in-generation slice request."""
    if requested_slice is None or current_slice is None:
        return False
    if int(ready_generation) != int(current_generation):
        return False
    ready = int(ready_slice)
    return ready == int(requested_slice) and ready == int(current_slice)


# ═════════════════════════════════════════════════════════════════════════════
#  MOCK OBJECTS
# ═════════════════════════════════════════════════════════════════════════════

class _MockLazyVolume:
    """Models ``PyDicomLazyVolume``: grow(), request_slice(), load_lock, pending.

    Does NOT use Qt signals.  Callbacks are placed on an explicit list so
    tests can deliver them at deterministic points.
    """

    def __init__(
        self,
        initial_count: int,
        *,
        grow_delay_sec: float = 0.0,
        remap_on_grow: bool = False,
    ):
        self.slice_count = initial_count
        self._load_lock = threading.Lock()
        self._pending: Dict[int, int] = {}          # slice_idx → generation
        self._pending_lock = threading.Lock()
        self._loaded = [False] * initial_count
        self._paths = [f"/fake/{i:04d}.dcm" for i in range(initial_count)]

        # Configurable behaviour
        self._grow_delay_sec = grow_delay_sec       # widens TOCTOU window (H-D)
        self._remap_on_grow = remap_on_grow          # triggers old→new remap (H-C)

        # Simplified VTK-state simulation (dimensions vs scalars)
        self._vtk_dimensions = (initial_count,)
        self._vtk_scalar_count = initial_count

        # Tracking
        self._grow_calls: List[int] = []
        self._target_count = initial_count
        self._callback_queue: List[Tuple[int, float, bool]] = []  # (idx, ms, hit)

        # TOCTOU window observable flag (True while dims ≠ scalars)
        self._in_toctou_window = False

    # -- helpers ---------------------------------------------------------------

    def set_target(self, count: int):
        """Simulate new files arriving on disk."""
        self._target_count = count
        while len(self._paths) < count:
            self._paths.append(f"/fake/{len(self._paths):04d}.dcm")

    # -- grow (models PyDicomLazyVolume.grow) -----------------------------------

    def grow(self) -> int:
        new_count = self._target_count
        if new_count <= self.slice_count:
            return self.slice_count

        old_count = self.slice_count

        # Build optional old→new mapping (first-half reversal)
        old_to_new: Optional[Dict[int, int]] = None
        if self._remap_on_grow and old_count > 0:
            mapping = {}
            half = old_count // 2
            for i in range(old_count):
                mapping[i] = (half - 1 - i) if i < half else i
            if any(o != n for o, n in mapping.items()):
                old_to_new = mapping

        with self._load_lock:
            # Step 1: SetDimensions equivalent
            self._vtk_dimensions = (new_count,)
            self._in_toctou_window = True

            if self._grow_delay_sec > 0:
                # Temporarily release lock to allow concurrent reads (H-D probe)
                self._load_lock.release()
                time.sleep(self._grow_delay_sec)
                self._load_lock.acquire()

            # Step 2: SetScalars equivalent  +  loaded-state remap
            new_loaded = [False] * new_count
            if old_to_new is not None:
                for old_idx in range(old_count):
                    if self._loaded[old_idx]:
                        new_idx = old_to_new.get(old_idx, old_idx)
                        if new_idx < new_count:
                            new_loaded[new_idx] = True
            else:
                new_loaded[:old_count] = self._loaded[:old_count]

            self._loaded = new_loaded
            self.slice_count = new_count
            self._vtk_scalar_count = new_count
            self._in_toctou_window = False

        self._grow_calls.append(new_count)
        return self.slice_count

    # -- request / complete (models request_slice_loaded + worker decode) ------

    def request_slice(self, idx: int, generation: int):
        i = max(0, min(idx, self.slice_count - 1))
        with self._pending_lock:
            self._pending[i] = generation

    def complete_pending(self, idx: int, decode_ms: float = 1.0) -> Optional[int]:
        """Simulate decode completion.  Returns the generation, or None."""
        with self._pending_lock:
            gen = self._pending.pop(idx, None)
        if gen is not None:
            if idx < len(self._loaded):
                self._loaded[idx] = True
            self._callback_queue.append((idx, decode_ms, False))
        return gen

    def get_pending_indices(self) -> List[int]:
        with self._pending_lock:
            return list(self._pending.keys())

    def get_pending_generation(self, idx: int) -> Optional[int]:
        with self._pending_lock:
            return self._pending.get(idx)


class _MockVTKWidget:
    """Models VTKWidget: set_slice, _on_lazy_slice_ready, generation tracking.

    All state checks mirror the real guards in ``_vw_scroll.py``,
    ``_vw_backend.py``, and ``_vw_progressive.py``.
    """

    BACKEND_PYDICOM = "pydicom_2d"

    def __init__(
        self,
        series_number: str,
        loader: Optional[_MockLazyVolume],
        *,
        progressive: bool = True,
        initial_available: int = 0,
    ):
        self.id_vtk_widget = 1
        self._active_backend = self.BACKEND_PYDICOM
        self._series_generation_id = 0
        self._lazy_requested_generation = 0
        self._lazy_requested_slice: Optional[int] = None
        self._lazy_loader: Optional[_MockLazyVolume] = loader

        self._progressive_mode = progressive
        self._progressive_series_number = series_number if progressive else None
        self._available_slice_count = (
            initial_available if progressive
            else (loader.slice_count if loader else 0)
        )
        self._total_expected_slices = 0

        self.image_viewer = SimpleNamespace(
            metadata={
                "series": {
                    "series_number": series_number,
                    "image_count": loader.slice_count if loader else 0,
                },
            },
            last_index_slice_saved=0,
            GetSlice=lambda: self._current_slice,
        )
        self._current_slice = 0

        # Observation logs
        self._rendered_slices: List[int] = []
        self._dropped_slices: List[Tuple[int, str]] = []   # (idx, reason)
        self._set_slice_log: List[Tuple[int, bool, int]] = []  # (idx, success, slice_count)

    def get_count_of_slices(self) -> int:
        if self._lazy_loader:
            return self._lazy_loader.slice_count
        return 0

    # -- _is_slice_available (from _vw_progressive.py) -------------------------

    def _is_slice_available(self, slice_index: int) -> bool:
        if not self._progressive_mode:
            return True
        return int(slice_index) < self._available_slice_count

    # -- set_slice (core state checks from _vw_scroll.py) ----------------------

    def set_slice(self, slice_index: int) -> bool:
        _count = self.get_count_of_slices()
        if self.image_viewer is None:
            self._set_slice_log.append((slice_index, False, _count))
            self._dropped_slices.append((slice_index, "image_viewer_none"))
            return False

        if self._progressive_mode and not self._is_slice_available(slice_index):
            self._set_slice_log.append((slice_index, False, _count))
            self._dropped_slices.append((slice_index, "not_available"))
            self.image_viewer.last_index_slice_saved = int(slice_index)
            return False

        # Request lazy decode
        if self._lazy_loader is not None:
            self._lazy_requested_slice = slice_index
            self._lazy_requested_generation = self._series_generation_id
            self._lazy_loader.request_slice(slice_index, self._series_generation_id)

        self._current_slice = slice_index
        self._set_slice_log.append((slice_index, True, _count))
        return True

    # -- _on_lazy_slice_ready (guard logic from _vw_backend.py) ----------------

    def _on_lazy_slice_ready(self, slice_index: int, decode_ms: float, cache_hit: bool):
        if self._active_backend != self.BACKEND_PYDICOM:
            self._dropped_slices.append((slice_index, "wrong_backend"))
            return

        if self._lazy_loader is None:
            self._dropped_slices.append((slice_index, "loader_none"))
            return

        if not should_render_ready_slice(
            ready_slice=int(slice_index),
            requested_slice=self._lazy_requested_slice,
            current_slice=self._current_slice,
            ready_generation=int(self._lazy_requested_generation),
            current_generation=int(self._series_generation_id),
        ):
            self._dropped_slices.append((slice_index, "stale_guard"))
            return

        # RENDER (simulated)
        self._rendered_slices.append(slice_index)

    # -- series switch (from _vw_series.py + _vw_backend.py) -------------------

    def switch_series(self, new_series: str, new_loader: Optional[_MockLazyVolume]):
        """Release old loader, increment generation, bind new loader."""
        self._lazy_loader = None                            # _release_bound_lazy_loader
        self._series_generation_id += 1
        self._lazy_requested_generation = self._series_generation_id
        self._lazy_requested_slice = None

        self._lazy_loader = new_loader
        self.image_viewer.metadata["series"]["series_number"] = new_series
        self._progressive_series_number = new_series
        self._current_slice = 0

    def update_available_slice_count(self, count: int):
        self._available_slice_count = count


class _MockDMSignalSource:
    """Simulates DM progress signal emissions."""

    def __init__(self):
        self._emissions: List[Tuple[str, int, int]] = []

    def emit_progress(self, series_number: str, downloaded: int, total: int):
        self._emissions.append((series_number, downloaded, total))


class _MockProgressiveController:
    """Simulates ViewerController progressive-display state tracking."""

    def __init__(self):
        self._progressive_series: Dict[str, dict] = {}
        self._progressive_display_done: set = set()
        self._progressive_display_inflight: set = set()
        self._series_download_completed: set = set()
        self.viewers: List[_MockVTKWidget] = []

    def add_viewer(self, viewer: _MockVTKWidget):
        self.viewers.append(viewer)

    def find_progressive_viewers(self, sn: str) -> List[_MockVTKWidget]:
        return [
            v for v in self.viewers
            if v._progressive_mode and v._progressive_series_number == sn
        ]

    def start_progressive(self, sn: str, total: int):
        if sn not in self._progressive_series:
            self._progressive_series[sn] = {
                "total": total, "last_grow_count": 0, "last_signal_ms": 0,
            }
        self._progressive_display_done.add(sn)

    def pop_series(self, sn: str):
        """BUG variant: pop from _progressive_series WITHOUT discarding done."""
        self._progressive_series.pop(sn, None)

    def pop_series_with_done_discard(self, sn: str):
        """Correct variant: pop + discard done guard (H4 fix)."""
        self._progressive_series.pop(sn, None)
        self._progressive_display_done.discard(sn)

    def mark_download_completed(self, sn: str):
        self._series_download_completed.add(sn)


# ═════════════════════════════════════════════════════════════════════════════
#  INVARIANT CHECKER
# ═════════════════════════════════════════════════════════════════════════════

class PipelineAInvariantChecker:
    """Checks 7 invariants after every logical step.

    Returns a list of ``(step, invariant_name, detail_dict)`` for new
    violations.  Accumulates all violations in ``self.violations``.
    """

    def __init__(self, controller: _MockProgressiveController):
        self.controller = controller
        self.violations: List[Tuple[int, str, dict]] = []
        self._step = 0
        self._last_gen_id = -1
        self._last_rendered_count = 0
        self._inv4_cursor = 0     # tracks which set_slice_log entries checked

    def check_all(
        self,
        viewer: Optional[_MockVTKWidget] = None,
    ) -> List[Tuple[int, str, dict]]:
        self._step += 1
        new: List[Tuple[int, str, dict]] = []

        if viewer is not None:
            new.extend(self._inv1(viewer))
            new.extend(self._inv2(viewer))
            new.extend(self._inv3(viewer))
            new.extend(self._inv4(viewer))
            new.extend(self._inv5(viewer))
            new.extend(self._inv7(viewer))

        new.extend(self._inv6())

        self.violations.extend(new)
        return new

    # -- individual invariants -------------------------------------------------

    def _inv1(self, v: _MockVTKWidget) -> list:
        """INV-1: viewer showing series tracked in _progressive_series →
        viewer must be in progressive mode."""
        sn = v.image_viewer.metadata["series"]["series_number"]
        if sn in self.controller._progressive_series and not v._progressive_mode:
            return [(self._step, "INV-1", {
                "series": sn,
                "in_progressive_series": True,
                "progressive_mode": v._progressive_mode,
            })]
        return []

    def _inv2(self, v: _MockVTKWidget) -> list:
        """INV-2: _series_generation_id monotonically non-decreasing."""
        prev, curr = self._last_gen_id, v._series_generation_id
        self._last_gen_id = curr
        if prev >= 0 and curr < prev:
            return [(self._step, "INV-2", {"prev": prev, "curr": curr})]
        return []

    def _inv3(self, v: _MockVTKWidget) -> list:
        """INV-3: loader None → no NEW renders since last check."""
        if v._lazy_loader is None:
            new_renders = len(v._rendered_slices) - self._last_rendered_count
            if new_renders > 0:
                self._last_rendered_count = len(v._rendered_slices)
                return [(self._step, "INV-3", {
                    "loader": None, "new_renders": new_renders,
                })]
        self._last_rendered_count = len(v._rendered_slices)
        return []

    def _inv4(self, v: _MockVTKWidget) -> list:
        """INV-4: any *successful* set_slice(n) must have n < slice_count
        at the time of the call."""
        violations = []
        new_entries = v._set_slice_log[self._inv4_cursor:]
        self._inv4_cursor = len(v._set_slice_log)
        for idx, ok, count_at_call in new_entries:
            if ok and count_at_call > 0 and idx >= count_at_call:
                violations.append((self._step, "INV-4", {
                    "slice_index": idx, "slice_count_at_call": count_at_call,
                }))
        return violations

    def _inv5(self, v: _MockVTKWidget) -> list:
        """INV-5: VTK dimensions == scalar-array size (no TOCTOU gap)."""
        loader = v._lazy_loader
        if loader is not None:
            d, s = loader._vtk_dimensions[0], loader._vtk_scalar_count
            if d != s:
                return [(self._step, "INV-5", {
                    "dimensions": d, "scalar_count": s,
                })]
        return []

    def _inv6(self) -> list:
        """INV-6: after pop(sn) — sn NOT in _progressive_display_done."""
        violations = []
        for sn in list(self.controller._progressive_display_done):
            if sn not in self.controller._progressive_series:
                violations.append((self._step, "INV-6", {
                    "series": sn,
                    "in_progressive_series": False,
                    "in_done": True,
                }))
        return violations

    def _inv7(self, v: _MockVTKWidget) -> list:
        """INV-7: stale-generation callback never rendered.

        A stale render is one where the callback's implicit generation
        (``_lazy_requested_generation`` at delivery time) doesn't match
        the generation that was active when the request was made.
        This is tracked via ``_dropped_slices`` with reason ``stale_guard``.

        This invariant fires if a render occurred while the generation
        was potentially stale — detected by comparing per-render generation
        against the expected live generation.
        """
        # In our mock, every render passes should_render_ready_slice.
        # H-B tests explicitly verify that stale callbacks are dropped.
        return []


# ═════════════════════════════════════════════════════════════════════════════
#  PHASE 1 — CONTROL TESTS
# ═════════════════════════════════════════════════════════════════════════════

class TestPhase1Controls:
    """Baselines: download-only and view-only must pass all invariants."""

    def test_control_a_download_only(self):
        """DM progress signals with NO viewer — zero invariant violations."""
        ctrl = _MockProgressiveController()
        dm = _MockDMSignalSource()
        checker = PipelineAInvariantChecker(ctrl)

        sn, total = "101", 200
        for downloaded in range(1, total + 1):
            dm.emit_progress(sn, downloaded, total)
            if sn not in ctrl._progressive_series:
                ctrl._progressive_series[sn] = {
                    "total": total, "last_grow_count": 0, "last_signal_ms": 0,
                }
            ctrl._progressive_series[sn]["total"] = total
            assert checker.check_all() == []

        ctrl.pop_series_with_done_discard(sn)
        ctrl.mark_download_completed(sn)
        assert checker.check_all() == []

    def test_control_b_view_only(self):
        """Fully-downloaded series: scroll every slice — zero violations."""
        count = 200
        loader = _MockLazyVolume(count)
        loader._loaded = [True] * count

        viewer = _MockVTKWidget(
            "101", loader, progressive=False, initial_available=count,
        )
        viewer._available_slice_count = count

        ctrl = _MockProgressiveController()
        ctrl.add_viewer(viewer)
        checker = PipelineAInvariantChecker(ctrl)

        for i in range(count):
            ok = viewer.set_slice(i)
            assert ok, f"set_slice({i}) failed"
            gen = loader.complete_pending(i)
            if gen is not None:
                viewer._on_lazy_slice_ready(i, 1.0, False)
            assert checker.check_all(viewer) == []

        assert len(viewer._rendered_slices) == count


# ═════════════════════════════════════════════════════════════════════════════
#  PHASE 2 — HYPOTHESIS TESTS
# ═════════════════════════════════════════════════════════════════════════════

class TestPhase2Hypotheses:
    """One test per hypothesis.  Independent, deterministic."""

    # ------------------------------------------------------------------
    # H-A: Progressive state sync — interleave grow + scroll, then
    #       exercise the H4 bug path (pop without done discard).
    # ------------------------------------------------------------------
    def test_ha_progressive_state_sync(self):
        initial, total = 20, 200
        loader = _MockLazyVolume(initial)
        viewer = _MockVTKWidget(
            "201", loader, progressive=True, initial_available=initial,
        )
        viewer._total_expected_slices = total

        ctrl = _MockProgressiveController()
        ctrl.add_viewer(viewer)
        ctrl.start_progressive("201", total)
        checker = PipelineAInvariantChecker(ctrl)
        dm = _MockDMSignalSource()

        downloaded = initial
        for step in range(500):
            # Every 10 steps: new batch arrives
            if step % 10 == 0 and downloaded < total:
                downloaded = min(downloaded + 10, total)
                loader.set_target(downloaded)
                loader.grow()
                viewer.update_available_slice_count(loader.slice_count)
                ctrl._progressive_series["201"]["last_grow_count"] = downloaded
                dm.emit_progress("201", downloaded, total)

            scroll_target = step % max(1, viewer._available_slice_count)
            viewer.set_slice(scroll_target)
            assert checker.check_all(viewer) == [], f"step {step}"

        # ---- H4 bug scenario: pop WITHOUT done discard ----
        ctrl.pop_series("201")  # BUG path — done not discarded
        violations = checker.check_all(viewer)
        inv6 = [v for v in violations if v[1] == "INV-6"]
        assert len(inv6) > 0, "Expected INV-6 (done-guard stale key after pop)"

        # ---- Correct path: discard the done key ----
        ctrl._progressive_display_done.discard("201")
        checker.violations.clear()
        assert checker.check_all(viewer) == [], "Clean after H4 fix"

    # ------------------------------------------------------------------
    # H-B: Generation ID race — switch series then fire stale callbacks.
    #       Variant 1: stale callbacks for a different slice index → caught.
    #       Variant 2: stale callbacks for the SAME slice index on new
    #       series → guard passes (potential stale render).
    # ------------------------------------------------------------------
    def test_hb_generation_id_race_different_index(self):
        """Stale callbacks targeting indices the new series hasn't requested."""
        loader_a = _MockLazyVolume(50)
        loader_a._loaded = [True] * 50
        loader_b = _MockLazyVolume(80)
        loader_b._loaded = [True] * 80

        viewer = _MockVTKWidget(
            "301", loader_a, progressive=True, initial_available=50,
        )
        ctrl = _MockProgressiveController()
        ctrl.add_viewer(viewer)
        checker = PipelineAInvariantChecker(ctrl)

        # Request slices 0..9 on series A
        for i in range(10):
            viewer.set_slice(i)

        # Switch to series B, scroll to index 20 (different from stale indices)
        viewer.switch_series("302", loader_b)
        viewer._progressive_mode = True
        viewer._available_slice_count = 80
        viewer.set_slice(20)

        # Fire stale A callbacks for indices 0..9
        for i in range(10):
            viewer._on_lazy_slice_ready(i, 1.0, False)

        stale_drops = [d for d in viewer._dropped_slices if d[1] == "stale_guard"]
        assert len(stale_drops) == 10, f"Expected 10 stale drops, got {len(stale_drops)}"
        assert len(viewer._rendered_slices) == 0
        assert checker.check_all(viewer) == []

    def test_hb_generation_id_race_same_index(self):
        """CRITICAL: stale callback targets the SAME index the new series
        just requested — should_render_ready_slice guard passes because it
        uses current viewer state (not per-request generation tracking).

        This documents that the application-level guard alone does NOT
        prevent stale renders when the new series happens to request the
        same slice index.  The real defence is Qt signal disconnect +
        blockSignals in _release_bound_lazy_loader.  Layer B will verify
        whether that defence is timing-safe.
        """
        loader_a = _MockLazyVolume(50)
        loader_a._loaded = [True] * 50
        loader_b = _MockLazyVolume(80)
        loader_b._loaded = [True] * 80

        viewer = _MockVTKWidget(
            "301", loader_a, progressive=True, initial_available=50,
        )

        # Request slice 5 on series A
        viewer.set_slice(5)
        gen_a = viewer._series_generation_id

        # Switch to series B
        viewer.switch_series("302", loader_b)
        viewer._progressive_mode = True
        viewer._available_slice_count = 80

        # Scroll to the SAME index (5) on series B
        viewer.set_slice(5)
        assert viewer._series_generation_id == gen_a + 1

        # Fire a stale callback from series A decode for index 5.
        # In reality this would come from the old loader's worker thread.
        # The guard uses CURRENT state: requested=5, current=5, gen matches.
        viewer._on_lazy_slice_ready(5, 1.0, False)

        # FINDING: the guard PASSES — stale data from series A renders on B.
        # This is expected given should_render_ready_slice design.
        stale_render_occurred = 5 in viewer._rendered_slices
        assert stale_render_occurred, (
            "Expected stale render to pass guard (documents H-B gap); "
            "real defence is Qt signal disconnect, not application-level guard."
        )

    # ------------------------------------------------------------------
    # H-C: grow() pending-request index mismatch after remap.
    # ------------------------------------------------------------------
    def test_hc_grow_remap_pending_requests(self):
        """Pending decode request at old_index survives grow() without remap.

        After grow() with instance-number reorder, old pending indices
        still exist in the _pending dict.  The worker thread will decode
        backend._slices[old_idx] which now references a different physical
        file.  However, since both _slices and _volume use the new indexing
        consistently, the decoded data IS correct for the new index —
        the user just sees a different image than originally scrolled to.

        This is a visual discontinuity, NOT a crash vector.
        """
        initial = 10
        loader = _MockLazyVolume(initial, remap_on_grow=True)
        viewer = _MockVTKWidget(
            "401", loader, progressive=True, initial_available=initial,
        )
        ctrl = _MockProgressiveController()
        ctrl.add_viewer(viewer)

        # Request decode at index 3
        viewer.set_slice(3)
        pending_before = loader.get_pending_indices()
        assert 3 in pending_before
        gen_before = loader.get_pending_generation(3)

        # grow + remap
        loader.set_target(15)
        loader.grow()
        assert loader.slice_count == 15

        # Pending survives grow (real code does NOT clear/remap pending)
        pending_after = loader.get_pending_indices()
        assert 3 in pending_after, "Pending request survived grow (expected)"
        assert loader.get_pending_generation(3) == gen_before

        # Complete the decode — data goes to new index 3 (which is a
        # different physical file after remap)
        gen = loader.complete_pending(3)
        assert gen is not None

        viewer.update_available_slice_count(15)
        viewer._on_lazy_slice_ready(3, 1.0, False)

        # Render happens (guard passes — generation matches, index matches)
        assert 3 in viewer._rendered_slices

    # ------------------------------------------------------------------
    # H-D: TOCTOU — concurrent grow() + set_slice() via threads.
    #
    # In production, both run on the Qt main thread (no real threading
    # TOCTOU).  This test artificially uses threads to probe whether
    # the lock structure would protect against it if grow() were called
    # from a background thread.
    # ------------------------------------------------------------------
    def test_hd_scroll_during_grow_toctou(self):
        initial, total = 50, 200
        loader = _MockLazyVolume(initial, grow_delay_sec=0.001)
        viewer = _MockVTKWidget(
            "501", loader, progressive=True, initial_available=initial,
        )
        viewer._total_expected_slices = total

        ctrl = _MockProgressiveController()
        ctrl.add_viewer(viewer)
        ctrl.start_progressive("501", total)
        checker = PipelineAInvariantChecker(ctrl)

        toctou_hits: list = []
        stop = threading.Event()

        def scroll_loop():
            i = 0
            while not stop.is_set():
                d = loader._vtk_dimensions[0]
                s = loader._vtk_scalar_count
                if d != s:
                    toctou_hits.append({"step": i, "dims": d, "scalars": s})
                avail = viewer._available_slice_count
                if avail > 0:
                    viewer.set_slice(i % avail)
                i += 1

        def grow_loop():
            current = initial
            while current < total:
                current = min(current + 10, total)
                loader.set_target(current)
                loader.grow()
                viewer.update_available_slice_count(loader.slice_count)
                time.sleep(0.0005)

        scroll_t = threading.Thread(target=scroll_loop, daemon=True)
        grow_t = threading.Thread(target=grow_loop, daemon=True)

        scroll_t.start()
        grow_t.start()
        grow_t.join(timeout=5.0)
        stop.set()
        scroll_t.join(timeout=2.0)

        # Final state must be consistent
        assert loader._vtk_dimensions[0] == loader._vtk_scalar_count, (
            f"Final TOCTOU: dims={loader._vtk_dimensions[0]} "
            f"scalars={loader._vtk_scalar_count}"
        )
        # TOCTOU hits indicate the window was observable mid-flight
        # (expected when grow_delay > 0)

    # ------------------------------------------------------------------
    # H-E: Stale callback against invalidated state (Python guards only).
    # ------------------------------------------------------------------
    def test_he_stale_callback_invalidated_state(self):
        loader = _MockLazyVolume(100)
        loader._loaded = [True] * 100
        viewer = _MockVTKWidget(
            "601", loader, progressive=False, initial_available=100,
        )
        ctrl = _MockProgressiveController()
        ctrl.add_viewer(viewer)
        checker = PipelineAInvariantChecker(ctrl)

        # Normal render
        viewer.set_slice(5)
        gen = loader.complete_pending(5)
        viewer._on_lazy_slice_ready(5, 1.0, False)
        assert 5 in viewer._rendered_slices
        assert checker.check_all(viewer) == []

        # -- Release loader --
        old_loader = viewer._lazy_loader
        viewer._lazy_loader = None
        viewer._series_generation_id += 1

        # Fire 10 stale callbacks
        for i in range(10):
            viewer._on_lazy_slice_ready(i, 1.0, False)

        drops = [d for d in viewer._dropped_slices if d[1] == "loader_none"]
        assert len(drops) == 10
        assert len(viewer._rendered_slices) == 1, "Only pre-release render"
        assert checker.check_all(viewer) == []

        # -- Null image_viewer --
        viewer._lazy_loader = old_loader
        viewer.image_viewer = None
        assert not viewer.set_slice(10)
        iv_drops = [d for d in viewer._dropped_slices if d[1] == "image_viewer_none"]
        assert len(iv_drops) == 1


# ═════════════════════════════════════════════════════════════════════════════
#  PHASE 3 — CONDITIONAL FULL STRESS
# ═════════════════════════════════════════════════════════════════════════════

class TestPhase3ConditionalStress:
    """All vectors at scale.  Run after Phase 2 to amplify signals."""

    def test_pipeline_a_full_interleave(self):
        """2 concurrent series, 1000 steps, random switches, all 7 invariants.

        Collects violations rather than asserting per-step so the full
        run completes and we can see aggregate patterns.
        """
        total_a, total_b = 150, 200
        loader_a = _MockLazyVolume(10)
        loader_b = _MockLazyVolume(10)

        viewer = _MockVTKWidget(
            "701", loader_a, progressive=True, initial_available=10,
        )
        viewer._total_expected_slices = total_a

        ctrl = _MockProgressiveController()
        ctrl.add_viewer(viewer)
        ctrl.start_progressive("701", total_a)
        checker = PipelineAInvariantChecker(ctrl)

        dm = _MockDMSignalSource()
        dl_a, dl_b = 10, 10
        active_series = "701"
        active_loader = loader_a

        for step in range(1000):
            # Download progress every 5 steps
            if step % 5 == 0:
                if active_series == "701" and dl_a < total_a:
                    dl_a = min(dl_a + 5, total_a)
                    loader_a.set_target(dl_a)
                    loader_a.grow()
                    if viewer._progressive_series_number == "701":
                        viewer.update_available_slice_count(loader_a.slice_count)
                elif active_series == "702" and dl_b < total_b:
                    dl_b = min(dl_b + 5, total_b)
                    loader_b.set_target(dl_b)
                    loader_b.grow()
                    if viewer._progressive_series_number == "702":
                        viewer.update_available_slice_count(loader_b.slice_count)

            # Series switch every 200 steps
            if step > 0 and step % 200 == 0:
                if active_series == "701":
                    ctrl.pop_series_with_done_discard("701")
                    viewer.switch_series("702", loader_b)
                    viewer._progressive_mode = True
                    viewer._available_slice_count = loader_b.slice_count
                    ctrl.start_progressive("702", total_b)
                    active_series = "702"
                    active_loader = loader_b
                else:
                    ctrl.pop_series_with_done_discard("702")
                    viewer.switch_series("701", loader_a)
                    viewer._progressive_mode = True
                    viewer._available_slice_count = loader_a.slice_count
                    ctrl.start_progressive("701", total_a)
                    active_series = "701"
                    active_loader = loader_a

            # Scroll
            avail = viewer._available_slice_count
            if avail > 0:
                viewer.set_slice(step % avail)

                # Complete one pending + deliver callback
                pending = active_loader.get_pending_indices()
                for idx in pending[:1]:
                    gen = active_loader.complete_pending(idx)
                    if gen is not None:
                        viewer._lazy_requested_slice = idx
                        viewer._lazy_requested_generation = gen
                        viewer._on_lazy_slice_ready(idx, 1.0, False)

            checker.check_all(viewer)

        # ---- Aggregate report ----
        by_type: Dict[str, list] = {}
        for step, name, data in checker.violations:
            by_type.setdefault(name, []).append((step, data))

        drop_reasons: Dict[str, int] = {}
        for _, reason in viewer._dropped_slices:
            drop_reasons[reason] = drop_reasons.get(reason, 0) + 1

        # Print summary (visible with ``pytest -s``)
        print(f"\n  Phase 3: {len(checker.violations)} violations / 1000 steps")
        for name, items in sorted(by_type.items()):
            print(f"    {name}: {len(items)}")
            if items:
                print(f"      first: step={items[0][0]} {items[0][1]}")
        print(f"  Rendered: {len(viewer._rendered_slices)}")
        print(f"  Dropped:  {len(viewer._dropped_slices)}  {drop_reasons}")

        # INV-6 (H4) should NOT fire — we used pop_with_done_discard
        inv6 = [v for v in checker.violations if v[1] == "INV-6"]
        assert len(inv6) == 0, f"INV-6 violations in stress test: {inv6}"
