"""Bounded, identity-free timing of completed Advanced VTK constructions.

No image, metadata, widget, timer, or render callback is retained. A single log
record is emitted after construction; native failures still use the existing
sampler/native evidence. Durations measure elapsed time, not exclusive CPU time.
"""
from itertools import count
from time import perf_counter


_BUILD_IDS = count(1)


class AdvancedStartupTiming:
    def __init__(self, logger):
        self._logger = logger
        self._build_id = next(_BUILD_IDS)
        self._start = self._last = perf_counter()
        self._phases = []
        self._finished = False

    def mark(self, phase):
        """Record a fixed source-code phase label, never metadata-derived text."""
        if self._finished:
            return
        now = perf_counter()
        self._phases.append((phase, (now - self._last) * 1000.0))
        self._last = now

    def finish(self):
        if self._finished:
            return
        self.mark('finalize')
        self._finished = True
        total_ms = (self._last - self._start) * 1000.0
        phases = ' '.join(f'{name}_ms={elapsed:.3f}' for name, elapsed in self._phases)
        try:
            self._logger.info(
                '[ADVANCED-STARTUP-KPI] schema=1 build=%d outcome=complete total_ms=%.3f %s',
                self._build_id, total_ms, phases,
                extra={'component': 'viewer', 'function': 'ImageViewer2D.__init__',
                       'stage': 'startup_complete'},
            )
        except Exception:
            # Diagnostics must not turn a successfully constructed viewer into a failure.
            pass
