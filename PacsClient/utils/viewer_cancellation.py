"""Request-scoped cancellation keyed by ``ViewerHandle`` — the teardown / supersession primitive.

S5 of ``docs/plans/architecture/VIEWER_UNIFICATION_STAGED_PLAN_2026-06-25.md`` (also the
cancellation half of S3b). **Pure stdlib + threading** (no Qt / VTK). Introduced **UNUSED** in S5a
so the contract is locked + unit-tested (incl. concurrency) before any wiring (S5b → zero runtime
risk now).

What it closes
--------------
The architecture review found **D1 / D2**: an off-thread ``AsyncSwitchLoad`` apply that touches
the viewport WITHOUT the close-time guard ``_finish_on_ui`` has, and is **not cancelled on tab
close** (only asyncio tasks are) — a use-after-free class (the same family as the curved-MPR
crash); plus the ``_dl_watchdog_timer`` not stopped in ``closeEvent``. And the recurring stale-
worker races came from grid-index tokens, not a real cancellation signal.

This primitive gives the viewer ONE cancellation authority keyed by the **stable**
``ViewerHandle``:

- a new request for a viewport ``new_token(handle)`` and cancels the prior in-flight op for the
  SAME handle via :meth:`cancel_handle` (request supersession — replaces the grid-index token
  race);
- on tab/patient close, :meth:`cancel_handle` (or :meth:`cancel_all`) cancels every in-flight op
  for that viewport so a late apply finds its token cancelled and bails BEFORE touching a deleted
  C++ object (the D1 fix);
- a worker checks ``token.cancelled`` / ``token.raise_if_cancelled()`` at its apply points.

Cross-viewport isolation is structural: tokens are bucketed by ``ViewerHandle`` UUID, so cancelling
one viewport never touches another's in-flight work.
"""
from __future__ import annotations

import threading
from typing import Dict, Set


class OperationCancelled(Exception):
    """Raised by ``raise_if_cancelled`` when the op's token has been cancelled."""


class CancellationToken:
    """A one-shot, thread-safe cancellation flag handed to an in-flight op."""

    __slots__ = ("_event", "handle_uuid")

    def __init__(self, handle_uuid: str = "") -> None:
        self._event = threading.Event()
        self.handle_uuid = handle_uuid

    def cancel(self) -> None:
        self._event.set()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    def raise_if_cancelled(self) -> None:
        if self._event.is_set():
            raise OperationCancelled()

    def wait_cancelled(self, timeout=None) -> bool:
        return self._event.wait(timeout)


class CancellationRegistry:
    """Buckets :class:`CancellationToken` by ``ViewerHandle`` UUID. Thread-safe."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._by_handle: Dict[str, Set[CancellationToken]] = {}

    @staticmethod
    def _key(handle_or_uuid) -> str:
        u = getattr(handle_or_uuid, "uuid", handle_or_uuid)
        return str(u or "").strip()

    def new_token(self, handle_or_uuid, *, supersede: bool = False) -> CancellationToken:
        """Create + register a token for a viewer handle. When ``supersede`` is True, cancel every
        prior in-flight token for the SAME handle first (a new request replacing the old one)."""
        key = self._key(handle_or_uuid)
        doomed: Set[CancellationToken] = set()
        with self._lock:
            if supersede:
                doomed = self._by_handle.pop(key, set())
            tok = CancellationToken(handle_uuid=key)
            self._by_handle.setdefault(key, set()).add(tok)
        for t in doomed:
            t.cancel()
        return tok

    def cancel_handle(self, handle_or_uuid) -> int:
        """Cancel every in-flight op for one viewer handle (tab close / supersession). Returns the
        number cancelled. Isolated — never touches another handle's tokens."""
        key = self._key(handle_or_uuid)
        with self._lock:
            toks = self._by_handle.pop(key, set())
        for t in toks:
            t.cancel()
        return len(toks)

    def retire(self, token: CancellationToken) -> None:
        """Drop a token whose op finished cleanly (so it isn't cancelled later)."""
        if token is None:
            return
        key = token.handle_uuid
        with self._lock:
            s = self._by_handle.get(key)
            if s is not None:
                s.discard(token)
                if not s:
                    self._by_handle.pop(key, None)

    def cancel_all(self) -> int:
        """Cancel every in-flight op (full teardown). Returns the number cancelled."""
        with self._lock:
            buckets = list(self._by_handle.values())
            self._by_handle.clear()
        n = 0
        for s in buckets:
            for t in s:
                t.cancel()
                n += 1
        return n

    def active_count(self, handle_or_uuid=None) -> int:
        with self._lock:
            if handle_or_uuid is None:
                return sum(len(s) for s in self._by_handle.values())
            return len(self._by_handle.get(self._key(handle_or_uuid), ()))
