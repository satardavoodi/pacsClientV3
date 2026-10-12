"""Bounded private native-channel evidence, without identities or payloads."""
import threading
import time

MAX_VALUE = (1 << 31) - 1
STAGES = frozenset({'idle', 'admission', 'lock', 'auth', 'send', 'receive', 'validate', 'complete'})
REASONS = frozenset({'none', 'unknown', 'local_closed', 'read_deadline', 'write_deadline',
    'peer_disconnected', 'auth_required', 'access_denied', 'auth_busy',
    'upstream_unavailable', 'deadline', 'correlation', 'invalid_state'})
FIELDS = {'stage', 'reason', 'calls', 'succeeded', 'elapsed_ms', 'last_success_age_ms'}


def failure_reason(error):
    reason = getattr(error, 'reason', None)
    if isinstance(reason, str) and reason in REASONS:
        return reason
    code = getattr(error, 'code', None)
    if code == 'UPSTREAM_AUTH_BUSY':
        return 'auth_busy'
    status = getattr(error, 'status', None)
    if status == 401:
        return 'auth_required'
    if status == 403 or isinstance(error, PermissionError):
        return 'access_denied'
    if status == 503:
        return 'upstream_unavailable'
    if isinstance(error, TimeoutError):
        return 'deadline'
    if isinstance(error, ValueError):
        return 'invalid_state'
    return 'unknown'


def valid_evidence(value):
    return (isinstance(value, dict) and set(value) == FIELDS
        and isinstance(value['stage'], str) and value['stage'] in STAGES
        and isinstance(value['reason'], str) and value['reason'] in REASONS
        and all(type(value[key]) is int and 0 <= value[key] <= MAX_VALUE
                for key in FIELDS - {'stage', 'reason'}))


class Evidence:
    def __init__(self, clock=None):
        self.clock = clock or time.monotonic
        self.lock = threading.Lock()
        self.value = dict(stage='idle', reason='none', calls=0, succeeded=0,
                          elapsed_ms=0, last_success_age_ms=0)
        self.started = self.last_success = None
        self.generation = 0

    def begin(self):
        with self.lock:
            self.started = self.clock()
            self.generation += 1
            self.value.update(reason='none', elapsed_ms=0)
            self.value['calls'] = min(MAX_VALUE, self.value['calls'] + 1)
            return (self.generation, self.started)

    def stage(self, stage, token=None):
        with self.lock:
            if token is not None and token[0] != self.generation:
                return
            self.value['stage'] = stage if stage in STAGES else 'idle'

    def finish(self, error=None, token=None):
        with self.lock:
            now = self.clock()
            current = token is None or token[0] == self.generation
            started = token[1] if token is not None else self.started
            if current:
                self.value['elapsed_ms'] = min(MAX_VALUE, max(0, int((now - (started if started is not None else now)) * 1000)))
                self.value['reason'] = failure_reason(error) if error is not None else 'none'
            if error is None:
                if current:
                    self.value['stage'] = 'complete'
                self.value['succeeded'] = min(MAX_VALUE, self.value['succeeded'] + 1)
                self.last_success = now

    def snapshot(self):
        with self.lock:
            result = dict(self.value)
            result['last_success_age_ms'] = (min(MAX_VALUE, max(0, int((self.clock() - self.last_success) * 1000)))
                if self.last_success is not None else 0)
            return result
