"""Process-local admission and private cooperative transition accounting.

Counters describe only this process since startup. They are never evidence that
an older executing revision has drained. No HTTP administration is exposed.
"""
import math
import threading
import time


class Quiesced(RuntimeError):
    """No new work may enter a transition in progress."""


class CompletionUncertain(RuntimeError):
    """Owned work cleanup could not prove completion."""


def budget(value):
    if type(value) not in (int, float) or not math.isfinite(value) or not 0 < value <= 600:
        raise ValueError('The drain budget must be finite and between 0 and 600 seconds.')
    return value


class Lease:
    def __init__(self, gate):
        self.gate = gate
        self.finished = False

    def finish(self, *, uncertain=False):
        with self.gate.condition:
            if self.finished:
                return
            self.finished = True
            self.gate.inflight -= 1
            self.gate.completed += 1
            self.gate.completion_uncertain |= uncertain
            self.gate.condition.notify_all()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.finish()


class Admission:
    def __init__(self):
        self.condition = threading.Condition()
        self.quiesced = threading.Event()
        self.state = 'open'
        self.inflight = self.accepted = self.completed = 0
        self.completion_uncertain = False
        self.transition_guards = {}
        self.held_guards = []

    def register_transition_guard(self, hold, release):
        """Register private native idle evidence; callbacks run outside the lock."""
        if not callable(hold) or not callable(release):
            raise ValueError('Transition guards require hold and release callbacks.')
        identity = object()
        with self.condition:
            if self.state != 'open':
                raise Quiesced('A native runtime cannot attach during a transition.')
            self.transition_guards[identity] = (hold, release)
        def unregister():
            with self.condition:
                if identity in self.transition_guards:
                    if self.state not in ('open', 'closed'):
                        self.completion_uncertain = True
                    self.transition_guards.pop(identity)
                    self.condition.notify_all()
        return unregister

    def _release_guards(self):
        with self.condition:
            held, self.held_guards = self.held_guards, []
        complete = True
        for _, release in reversed(held):
            try:
                complete = (release() is True) and complete
            except Exception:
                complete = False
        if not complete:
            self.poison()
        return complete

    def begin(self, kind):
        if kind not in ('http', 'model', 'text', 'secretary', 'crm', 'speech'):
            raise ValueError('Unknown work category.')
        with self.condition:
            if self.state != 'open':
                raise Quiesced('Server transition in progress. Do not retry automatically.')
            self.inflight += 1
            self.accepted += 1
            return Lease(self)

    def poison(self):
        with self.condition:
            self.completion_uncertain = True
            self.condition.notify_all()

    def snapshot(self):
        with self.condition:
            return {'state': self.state, 'inflight': self.inflight,
                    'accepted': self.accepted, 'completed': self.completed,
                    'completion_uncertain': self.completion_uncertain}

    def drain(self, timeout):
        deadline = time.monotonic() + budget(timeout)
        with self.condition:
            if self.state != 'open':
                raise RuntimeError('A transition is already in progress or committed.')
            self.state = 'draining'
            self.quiesced.set()
            guards = list(self.transition_guards.items())
        for identity, (hold, release) in guards:
            try:
                held = hold(deadline) is True
            except Exception:
                self.poison()
                held = False
            with self.condition:
                if identity not in self.transition_guards:
                    self.completion_uncertain = True
                # A lost hold receipt may still have fenced the GUI. Attempt
                # release on abort without treating that as proof of idle.
                self.held_guards.append((identity, release))
            if not held:
                self._release_guards()
                with self.condition:
                    self.state = 'open'
                    self.quiesced.clear()
                return False
        with self.condition:
            while self.inflight and not self.completion_uncertain:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                self.condition.wait(remaining)
            if self.inflight or self.completion_uncertain or time.monotonic() > deadline:
                aborted = True
            else:
                self.state = 'quiesced'
                return True
        if aborted:
            self._release_guards()
            with self.condition:
                self.state = 'open'
                self.quiesced.clear()
            return False

    def resume(self):
        with self.condition:
            if self.state != 'quiesced':
                return False
        complete = self._release_guards()
        with self.condition:
            if self.state != 'quiesced' or not complete:
                return False
            self.state = 'open'
            self.quiesced.clear()
            return True

    def commit(self, close):
        with self.condition:
            if self.state != 'quiesced' or self.inflight or self.completion_uncertain:
                return False
            self.state = 'closed'
        try:
            close()
        except BaseException:
            self.poison()
            raise
        return True
