"""Pipeline A Crash Reproduction — Layer B (Qt-Integrated Signal Timing)

Real QApplication + real QObject signals emitted from worker threads.
Tests whether Qt's ``disconnect()`` / ``blockSignals(True)`` / deferred
``QTimer.singleShot(0)`` defence stack is timing-safe against stale-callback
delivery in the FAST viewer lazy-load path.

Hypotheses under test
---------------------
H-B  Same-index stale callback across series handoff
     Level 1 — Does disconnect() prevent delivery of already-queued signal?
     Level 2 — Full handoff: accepted stale frame after reconnect + same-index scroll?
H-E  Deferred release ordering (close() vs queued signals)
H-F  Reference-line metadata race during grow  (CONDITIONAL)

Requires PySide6.  No VTK, no GPU, no DICOM I/O.
"""
from __future__ import annotations

import sys
import threading
import time
from typing import List, Optional

import pytest

from PySide6.QtCore import QObject, QTimer, Signal, Slot, QThread, QCoreApplication
from PySide6.QtWidgets import QApplication


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
#  HELPERS
# ═════════════════════════════════════════════════════════════════════════════


class _FakeLoader(QObject):
    """Minimal QObject that emits ``slice_ready`` from a worker thread.

    Mirrors ``PyDicomLazyVolume.slice_ready = Signal(int, float, bool)``
    but contains no real decode logic.  Signal uses the default
    ``AutoConnection``, which Qt promotes to ``QueuedConnection`` when
    emitter and receiver live on different threads — exactly matching
    production behaviour.
    """

    slice_ready = Signal(int, float, bool)

    def __init__(self, loader_id: str = "loader", parent=None):
        super().__init__(parent)
        self.loader_id = loader_id
        self._closed = False

    def emit_from_worker(self, slice_index: int, decode_ms: float = 1.0,
                         cache_hit: bool = False, *, done_event: threading.Event = None):
        """Emit ``slice_ready`` from a background thread, then signal done."""

        def _worker():
            self.slice_ready.emit(slice_index, decode_ms, cache_hit)
            if done_event is not None:
                done_event.set()

        t = threading.Thread(target=_worker, daemon=True)
        t.start()
        return t

    def close(self):
        self._closed = True


class _StaleCallbackReceiver(QObject):
    """Mirrors the guard logic of ``_on_lazy_slice_ready_impl``.

    Records every invocation so tests can inspect delivery/drop counts.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        # Mutable state — mirrors VTKWidget attrs
        self._lazy_loader: Optional[_FakeLoader] = None
        self._lazy_requested_slice: Optional[int] = None
        self._lazy_requested_generation: int = 0
        self._series_generation_id: int = 0

        # Recording
        self.delivered: List[dict] = []
        self.dropped: List[dict] = []

    @Slot(int, float, bool)
    def on_ready(self, slice_index: int, decode_ms: float, cache_hit: bool):
        """Slot wired to loader.slice_ready."""
        record = {
            "slice": slice_index,
            "decode_ms": decode_ms,
            "cache_hit": cache_hit,
            "loader": (self._lazy_loader.loader_id
                       if self._lazy_loader is not None else None),
            "req_slice": self._lazy_requested_slice,
            "req_gen": self._lazy_requested_generation,
            "series_gen": self._series_generation_id,
        }

        # Guard 1: loader is None → drop
        if self._lazy_loader is None:
            record["reason"] = "loader_none"
            self.dropped.append(record)
            return

        # Guard 2: stale frame guard
        guard_current_slice = self._lazy_requested_slice  # PyDicom override
        if not should_render_ready_slice(
            ready_slice=int(slice_index),
            requested_slice=self._lazy_requested_slice,
            current_slice=guard_current_slice,
            ready_generation=int(self._lazy_requested_generation),
            current_generation=int(self._series_generation_id),
        ):
            record["reason"] = "generation_mismatch"
            self.dropped.append(record)
            return

        # Would-render
        record["reason"] = "accepted"
        self.delivered.append(record)


def _process_events_thoroughly(app: QApplication, rounds: int = 10,
                               per_round_ms: int = 5):
    """Drain the Qt event queue thoroughly.

    Multiple processEvents rounds with small sleeps allow QueuedConnection
    events to propagate through the event loop.
    """
    for _ in range(rounds):
        app.processEvents()
        time.sleep(per_round_ms / 1000.0)
    app.processEvents()


# ═════════════════════════════════════════════════════════════════════════════
#  FIXTURES
# ═════════════════════════════════════════════════════════════════════════════


@pytest.fixture(scope="session")
def qapp():
    """Session-scoped QApplication.  Reused across all tests."""
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv[:1])
    yield app


@pytest.fixture()
def receiver():
    return _StaleCallbackReceiver()


# ═════════════════════════════════════════════════════════════════════════════
#  H-B: SAME-INDEX STALE CALLBACK ACROSS SERIES HANDOFF
# ═════════════════════════════════════════════════════════════════════════════


class TestHB_StaleCallbackTiming:
    """Test whether disconnect() prevents delivery of already-queued
    cross-thread QueuedConnection signals, and whether the stale frame
    guard catches same-index stale data after full series handoff.
    """

    # ── Level 1: signal delivery question ─────────────────────────────────

    def test_hb_disconnect_drops_queued_signal(self, qapp, receiver):
        """Variant (a) — Level 1 primary.

        Emit from worker → DO NOT processEvents → blockSignals + disconnect →
        processEvents → stale callback should NOT be delivered.

        Repeated N times for statistical confidence.
        """
        N_TRIALS = 200
        delivery_count = 0

        for trial in range(N_TRIALS):
            loader = _FakeLoader(f"old_{trial}")
            recv = _StaleCallbackReceiver()
            recv._lazy_loader = loader
            recv._lazy_requested_slice = 5
            recv._series_generation_id = 1
            recv._lazy_requested_generation = 1

            loader.slice_ready.connect(recv.on_ready)

            # Emit from worker thread — queues QMetaCallEvent
            done = threading.Event()
            t = loader.emit_from_worker(5, done_event=done)
            done.wait(timeout=2.0)
            t.join(timeout=2.0)

            # DO NOT processEvents — signal is queued but not delivered

            # Mirror _release_bound_lazy_loader sequence
            recv._lazy_loader = None
            loader.blockSignals(True)
            try:
                loader.slice_ready.disconnect(recv.on_ready)
            except Exception:
                pass

            # Now drain
            _process_events_thoroughly(qapp)

            if len(recv.delivered) > 0:
                delivery_count += 1

            # Cleanup
            recv.deleteLater()
            loader.deleteLater()

        # Report
        print(f"\n[H-B Level 1a] Stale callback delivered in {delivery_count}/{N_TRIALS} trials")
        if delivery_count > 0:
            print("[H-B Level 1a] CRITICAL: disconnect() does NOT reliably drop queued signals!")
        else:
            print("[H-B Level 1a] disconnect() reliably drops queued signals in all trials")

        # The test records the result — Level 2 (variant d) is the actionable proof.
        # We don't assert here so the test suite always completes.
        # Instead, mark via attribute for downstream inspection.
        TestHB_StaleCallbackTiming._level1a_delivery_count = delivery_count

    def test_hb_no_disconnect_delivers_signal(self, qapp, receiver):
        """Variant (b) — Level 1 control.

        Same setup but WITHOUT disconnect.  Signal MUST be delivered to
        prove the test harness works (signal was actually queued).
        """
        N_TRIALS = 50
        delivery_count = 0

        for trial in range(N_TRIALS):
            loader = _FakeLoader(f"ctrl_{trial}")
            recv = _StaleCallbackReceiver()
            recv._lazy_loader = loader
            recv._lazy_requested_slice = 5
            recv._series_generation_id = 1
            recv._lazy_requested_generation = 1

            loader.slice_ready.connect(recv.on_ready)

            done = threading.Event()
            t = loader.emit_from_worker(5, done_event=done)
            done.wait(timeout=2.0)
            t.join(timeout=2.0)

            # NO disconnect — just drain
            _process_events_thoroughly(qapp)

            if len(recv.delivered) > 0:
                delivery_count += 1

            recv.deleteLater()
            loader.deleteLater()

        print(f"\n[H-B Level 1b] Control: signal delivered in {delivery_count}/{N_TRIALS} trials")
        assert delivery_count == N_TRIALS, (
            f"Control variant: signal should be delivered in ALL trials, "
            f"but only delivered in {delivery_count}/{N_TRIALS}"
        )

    def test_hb_post_disconnect_emit_blocked(self, qapp, receiver):
        """Variant (c) — Level 1 validation.

        Disconnect first, THEN emit from another thread.
        Signal should NOT be delivered (validates disconnect for new emissions).
        """
        N_TRIALS = 100
        delivery_count = 0

        for trial in range(N_TRIALS):
            loader = _FakeLoader(f"post_{trial}")
            recv = _StaleCallbackReceiver()
            recv._lazy_loader = loader
            recv._lazy_requested_slice = 5
            recv._series_generation_id = 1
            recv._lazy_requested_generation = 1

            loader.slice_ready.connect(recv.on_ready)

            # Disconnect BEFORE emission
            recv._lazy_loader = None
            loader.blockSignals(True)
            try:
                loader.slice_ready.disconnect(recv.on_ready)
            except Exception:
                pass

            # Now emit from worker
            done = threading.Event()
            t = loader.emit_from_worker(5, done_event=done)
            done.wait(timeout=2.0)
            t.join(timeout=2.0)

            _process_events_thoroughly(qapp)

            if len(recv.delivered) > 0 or len(recv.dropped) > 0:
                delivery_count += 1

            recv.deleteLater()
            loader.deleteLater()

        print(f"\n[H-B Level 1c] Post-disconnect emit delivered in {delivery_count}/{N_TRIALS} trials")
        assert delivery_count == 0, (
            f"Post-disconnect emissions should never reach the slot, "
            f"but {delivery_count}/{N_TRIALS} reached the receiver"
        )

    # ── Level 2: accepted stale frame (the stronger proof) ────────────────

    def test_hb_same_index_after_reconnect(self, qapp, receiver):
        """Variant (d) — Level 2: full series handoff + same-index scroll.

        Complete timeline:
        1. loader_old emits slice_ready(5) from worker → queued
        2. Main thread: release old loader (blockSignals, disconnect)
        3. Increment gen_id (cleanup: +1)
        4. Bind new loader, increment gen_id (bind: +1), connect
        5. Set requested_slice=5, requested_gen=new_gen (same index!)
        6. processEvents → check if stale data from loader_old is ACCEPTED

        This is the attack timeline from the plan.  If the stale callback
        passes should_render_ready_slice, we have a confirmed stale render.
        """
        N_TRIALS = 200
        stale_accepted_count = 0
        stale_delivered_but_dropped = 0
        stale_details: list = []

        for trial in range(N_TRIALS):
            loader_old = _FakeLoader(f"old_{trial}")
            loader_new = _FakeLoader(f"new_{trial}")
            recv = _StaleCallbackReceiver()

            # Initial state: generation=10, connected to loader_old
            GEN_INITIAL = 10
            recv._series_generation_id = GEN_INITIAL
            recv._lazy_requested_generation = GEN_INITIAL
            recv._lazy_loader = loader_old
            recv._lazy_requested_slice = 5

            loader_old.slice_ready.connect(recv.on_ready)

            # Step 1: Worker emits slice_ready(5) from old loader → queued
            done = threading.Event()
            t = loader_old.emit_from_worker(5, done_event=done)
            done.wait(timeout=2.0)
            t.join(timeout=2.0)

            # DO NOT processEvents — signal is queued

            # Step 2: Release old loader (mirrors _release_bound_lazy_loader)
            recv._lazy_loader = None
            loader_old.blockSignals(True)
            try:
                loader_old.slice_ready.disconnect(recv.on_ready)
            except Exception:
                pass

            # Step 3: Generation increment (cleanup path in _vw_series.py)
            recv._series_generation_id += 1  # now GEN_INITIAL + 1
            recv._lazy_requested_generation = recv._series_generation_id
            recv._lazy_requested_slice = None

            # Step 4: Bind new loader (mirrors _bind_backend_from_metadata)
            recv._series_generation_id += 1  # now GEN_INITIAL + 2
            recv._lazy_requested_generation = recv._series_generation_id
            recv._lazy_requested_slice = None
            recv._lazy_loader = loader_new
            loader_new.slice_ready.connect(recv.on_ready)

            # Step 5: User scrolls to same index (5) on new series
            recv._lazy_requested_slice = 5

            # Step 6: Drain event queue — does the OLD emission reach the slot?
            _process_events_thoroughly(qapp)

            # Analyze
            for d in recv.delivered:
                if d.get("loader") == loader_old.loader_id:
                    stale_accepted_count += 1
                    stale_details.append({
                        "trial": trial,
                        "record": d,
                    })

            for d in recv.dropped:
                if d.get("loader") is None:
                    # loader was None at delivery time — stale was delivered
                    # but caught by loader_none guard
                    stale_delivered_but_dropped += 1

            loader_old.deleteLater()
            loader_new.deleteLater()
            recv.deleteLater()

        print(f"\n[H-B Level 2d] Full handoff results ({N_TRIALS} trials):")
        print(f"  Stale frame ACCEPTED:             {stale_accepted_count}")
        print(f"  Stale delivered but caught by guard: {stale_delivered_but_dropped}")
        print(f"  Stale fully suppressed (disconnect): {N_TRIALS - stale_accepted_count - stale_delivered_but_dropped}")

        if stale_accepted_count > 0:
            print(f"\n[H-B Level 2d] CRITICAL: Stale data ACCEPTED in "
                  f"{stale_accepted_count}/{N_TRIALS} trials!")
            print("[H-B Level 2d] First 5 details:")
            for detail in stale_details[:5]:
                print(f"  trial={detail['trial']} record={detail['record']}")
        else:
            print("[H-B Level 2d] No accepted stale frames — disconnect defence held.")

        TestHB_StaleCallbackTiming._level2d_stale_accepted = stale_accepted_count
        TestHB_StaleCallbackTiming._level2d_stale_dropped = stale_delivered_but_dropped

        # Variant (d) Level 2 finding is the key result.
        # We record it for the implementation-prep output.
        # If stale was accepted, the fix surface is:
        #   - should_render_ready_slice needs a loader-identity parameter
        #   - or _on_lazy_slice_ready_impl needs to check loader identity


# ═════════════════════════════════════════════════════════════════════════════
#  H-E: DEFERRED RELEASE ORDERING
# ═════════════════════════════════════════════════════════════════════════════


class TestHE_DeferredReleaseOrdering:
    """Test that QTimer.singleShot(0, close) runs AFTER all queued
    QueuedConnection signals — ensuring the QObject is not destroyed
    while Qt still holds references to it in the event queue.
    """

    def test_he_close_after_queued_signals(self, qapp):
        """The singleShot(0) deferred release must execute AFTER any
        already-queued slice_ready signals, even though both are
        posted in the same event loop tick.
        """
        N_TRIALS = 200
        order_violations = 0
        event_log: List[dict] = []

        for trial in range(N_TRIALS):
            trial_log: List[str] = []

            loader = _FakeLoader(f"he_{trial}")

            def _on_signal(idx, ms, hit, _tl=trial_log, _lid=loader.loader_id):
                _tl.append(f"signal:{_lid}")

            loader.slice_ready.connect(_on_signal)

            # Emit from worker → queued
            done = threading.Event()
            t = loader.emit_from_worker(5, done_event=done)
            done.wait(timeout=2.0)
            t.join(timeout=2.0)

            # Mirror release sequence
            loader.blockSignals(True)
            try:
                loader.slice_ready.disconnect(_on_signal)
            except Exception:
                pass

            # Deferred close
            def _deferred_close(_l=loader, _tl=trial_log):
                _tl.append(f"close:{_l.loader_id}")
                _l.close()

            QTimer.singleShot(0, _deferred_close)

            # Drain
            _process_events_thoroughly(qapp)

            # Check ordering
            signal_indices = [i for i, e in enumerate(trial_log) if e.startswith("signal:")]
            close_indices = [i for i, e in enumerate(trial_log) if e.startswith("close:")]

            if close_indices and signal_indices:
                if min(close_indices) < max(signal_indices):
                    order_violations += 1
                    event_log.append({"trial": trial, "log": list(trial_log)})

            loader.deleteLater()

        print(f"\n[H-E] Ordering violations: {order_violations}/{N_TRIALS}")
        if order_violations > 0:
            print("[H-E] WARNING: close() ran BEFORE queued signal in some trials!")
            for detail in event_log[:5]:
                print(f"  trial={detail['trial']} log={detail['log']}")
        else:
            print("[H-E] Deferred close always runs after queued signals (or signals were dropped)")

        TestHE_DeferredReleaseOrdering._order_violations = order_violations

    def test_he_stress_100_signals_then_close(self, qapp):
        """Stress variant: 100 rapid emissions → blockSignals → disconnect →
        singleShot(0, close) → processEvents.

        No crash, close runs last (or signals all dropped by disconnect).
        """
        N_TRIALS = 20
        crash_count = 0
        order_violations = 0

        for trial in range(N_TRIALS):
            trial_log: List[str] = []
            loader = _FakeLoader(f"stress_{trial}")
            delivery_count = 0

            def _on_signal(idx, ms, hit, _tl=trial_log):
                _tl.append("signal")

            loader.slice_ready.connect(_on_signal)

            # Emit 100 signals from worker threads rapidly
            threads = []
            events = []
            for i in range(100):
                ev = threading.Event()
                events.append(ev)
                t = loader.emit_from_worker(i, done_event=ev)
                threads.append(t)

            # Wait for all emissions
            for ev in events:
                ev.wait(timeout=5.0)
            for t in threads:
                t.join(timeout=5.0)

            # Release sequence
            loader.blockSignals(True)
            try:
                loader.slice_ready.disconnect(_on_signal)
            except Exception:
                pass

            def _deferred_close(_l=loader, _tl=trial_log):
                _tl.append("close")
                _l.close()

            QTimer.singleShot(0, _deferred_close)

            try:
                _process_events_thoroughly(qapp, rounds=20, per_round_ms=5)
            except Exception as exc:
                crash_count += 1
                print(f"[H-E stress] Trial {trial} crashed: {exc}")

            # Check close is last (or only event)
            if trial_log:
                close_pos = [i for i, e in enumerate(trial_log) if e == "close"]
                signal_pos = [i for i, e in enumerate(trial_log) if e == "signal"]
                if close_pos and signal_pos:
                    if min(close_pos) < max(signal_pos):
                        order_violations += 1

            loader.deleteLater()

        print(f"\n[H-E stress] Crashes: {crash_count}/{N_TRIALS}")
        print(f"[H-E stress] Ordering violations: {order_violations}/{N_TRIALS}")
        assert crash_count == 0, f"Stress test crashed in {crash_count}/{N_TRIALS} trials"


# ═════════════════════════════════════════════════════════════════════════════
#  H-F: REFERENCE-LINE METADATA RACE DURING GROW (CONDITIONAL)
# ═════════════════════════════════════════════════════════════════════════════


class TestHF_MetadataRaceDuringGrow:
    """Test whether a QTimer callback can fire between
    update_available_slice_count() and metadata['instances'] extension.

    CONDITIONAL: Only meaningful if H-B Level 2 is clean AND H-E is clean.
    The tests run regardless (for data collection), but the interpretation
    depends on H-B/H-E results.
    """

    def test_hf_timer_cannot_interleave_synchronous_main_thread(self, qapp):
        """Demonstrate that two sequential main-thread calls (no await,
        no processEvents between them) cannot be interleaved by a QTimer.

        This simulates _grow_progressive_fast's call sequence:
          1. loader.grow()   → returns new count
          2. viewer.update_available_slice_count(new_count)  → slider updated
          3. _refresh_stored_metadata_instances()             → instances extended

        Between steps 2 and 3, there is NO processEvents/await in the real code.
        A pending QTimer.timeout should NOT fire between them.
        """
        N_TRIALS = 100
        interleave_count = 0

        for trial in range(N_TRIALS):
            metadata = {"instances": [{"idx": i} for i in range(20)]}
            available_count = 20
            timer_fired_between = False
            timer_saw_index: Optional[int] = None

            def _timer_callback():
                nonlocal timer_fired_between, timer_saw_index
                # Simulate reference-line: access metadata['instances'][available_count - 1]
                try:
                    _ = metadata["instances"][available_count - 1]
                    timer_saw_index = available_count - 1
                except IndexError:
                    timer_fired_between = True
                    timer_saw_index = available_count - 1

            # Start a very short timer (1ms)
            timer = QTimer()
            timer.setSingleShot(True)
            timer.timeout.connect(_timer_callback)
            timer.start(1)

            # Small sleep to let timer become "ready"
            time.sleep(0.005)

            # Simulate grow — step 2: update available count
            available_count = 30

            # NO processEvents() here — mirrors real code

            # Simulate grow — step 3: extend instances
            metadata["instances"].extend([{"idx": i} for i in range(20, 30)])

            # Now drain events — timer fires HERE (after both steps)
            _process_events_thoroughly(qapp, rounds=5, per_round_ms=2)

            if timer_fired_between:
                interleave_count += 1

            timer.deleteLater()

        print(f"\n[H-F] Timer interleaved in {interleave_count}/{N_TRIALS} trials")
        if interleave_count > 0:
            print("[H-F] CRITICAL: Timer fired between grow steps!")
        else:
            print("[H-F] Timer cannot interleave synchronous main-thread calls — race NOT possible")

        TestHF_MetadataRaceDuringGrow._interleave_count = interleave_count

    def test_hf_timer_fires_if_process_events_called_between(self, qapp):
        """Control: if processEvents() IS called between steps 2 and 3,
        the timer CAN fire and cause IndexError.  This proves the test
        harness detects the race when it exists.
        """
        N_TRIALS = 50
        interleave_count = 0

        for trial in range(N_TRIALS):
            metadata = {"instances": [{"idx": i} for i in range(20)]}
            available_count = 20
            timer_fired_between = False

            def _timer_callback():
                nonlocal timer_fired_between
                try:
                    _ = metadata["instances"][available_count - 1]
                except IndexError:
                    timer_fired_between = True

            timer = QTimer()
            timer.setSingleShot(True)
            timer.timeout.connect(_timer_callback)
            timer.start(1)

            time.sleep(0.005)

            # Step 2: update available count
            available_count = 30

            # INTENTIONALLY call processEvents between steps — this is the
            # code pattern that WOULD be dangerous if it existed in production
            _process_events_thoroughly(qapp, rounds=3, per_round_ms=2)

            # Step 3: extend instances (too late — timer already fired)
            metadata["instances"].extend([{"idx": i} for i in range(20, 30)])

            if timer_fired_between:
                interleave_count += 1

            timer.deleteLater()

        print(f"\n[H-F control] Timer interleaved in {interleave_count}/{N_TRIALS} trials")
        # We expect MOST trials to interleave (timer had time to fire)
        # Not all may interleave due to timer precision, so just require >0
        assert interleave_count > 0, (
            "Control: timer should fire between steps at least once "
            "when processEvents is called between them"
        )


# ═════════════════════════════════════════════════════════════════════════════
#  SUMMARY COLLECTOR
# ═════════════════════════════════════════════════════════════════════════════


class TestLayerBSummary:
    """Run last.  Collects all hypothesis results and prints a summary."""

    def test_zz_summary(self, qapp):
        """Aggregate results.  Named zz_ to run after all other tests."""
        print("\n" + "=" * 72)
        print("  LAYER B RESULTS SUMMARY")
        print("=" * 72)

        # H-B Level 1a
        l1a = getattr(TestHB_StaleCallbackTiming, "_level1a_delivery_count", None)
        if l1a is not None:
            status = "CONFIRMED" if l1a > 0 else "REJECTED"
            print(f"  H-B Level 1a (disconnect drops queued): {status} (delivered={l1a})")
        else:
            print("  H-B Level 1a: NOT RUN")

        # H-B Level 2d
        l2d = getattr(TestHB_StaleCallbackTiming, "_level2d_stale_accepted", None)
        l2d_drop = getattr(TestHB_StaleCallbackTiming, "_level2d_stale_dropped", None)
        if l2d is not None:
            status = "CONFIRMED" if l2d > 0 else "REJECTED"
            print(f"  H-B Level 2d (accepted stale frame):    {status} "
                  f"(accepted={l2d}, dropped_by_guard={l2d_drop})")
            if l2d > 0:
                print("\n  >>> IMPLEMENTATION-PREP OUTPUT REQUIRED <<<")
                print("  Fix surface: should_render_ready_slice or _on_lazy_slice_ready_impl")
                print("  Missing: loader identity check (stale callback from old loader")
                print("           passes all guards when same index on new series)")
        else:
            print("  H-B Level 2d: NOT RUN")

        # H-E
        he_viol = getattr(TestHE_DeferredReleaseOrdering, "_order_violations", None)
        if he_viol is not None:
            status = "CONFIRMED" if he_viol > 0 else "REJECTED"
            print(f"  H-E (close before signal):              {status} (violations={he_viol})")
        else:
            print("  H-E: NOT RUN")

        # H-F
        hf_inter = getattr(TestHF_MetadataRaceDuringGrow, "_interleave_count", None)
        if hf_inter is not None:
            status = "CONFIRMED" if hf_inter > 0 else "REJECTED"
            print(f"  H-F (metadata race):                    {status} (interleaves={hf_inter})")
        else:
            print("  H-F: NOT RUN")

        print("=" * 72)
