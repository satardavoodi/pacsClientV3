"""Fixed-cardinality transport counters without identities or clinical data."""
import threading
import uuid

MAX_COUNT = (1 << 63) - 1
REASONS = (
    'connection_capacity_refused', 'first_byte_timeout',
    'first_byte_read_failed', 'peer_closed_before_preface',
    'tls_unavailable', 'tls_handshake_failed', 'invalid_preface',
    'handler_started', 'response_completed', 'response_write_failed',
    'request_body_timeout', 'handler_unexpected_failure',
)
ROUTE_CLASSES = ('other', 'auth_session', 'auth_me', 'public_capabilities')


def valid_snapshot(value):
    """Strict allowlist for a private child receipt, without copying extra data."""
    if not isinstance(value, dict) or set(value) not in ({'protocol', 'instance_id', 'counts'}, {'protocol', 'instance_id', 'counts', 'native_pipe'}):
        return False
    if 'native_pipe' in value:
        from .native_pipe_diagnostics import valid_evidence
        if not valid_evidence(value['native_pipe']):
            return False
    try:
        if type(value['protocol']) is not int or value['protocol'] != 1 or str(uuid.UUID(value['instance_id'])) != value['instance_id']:
            return False
    except (ValueError, TypeError, AttributeError):
        return False
    counts = value['counts']
    return (isinstance(counts, dict) and set(counts) == set(REASONS)
            and all(isinstance(row, dict) and set(row) == set(ROUTE_CLASSES)
                    and all(type(n) is int and 0 <= n <= MAX_COUNT for n in row.values())
                    for row in counts.values()))


class Counters:
    """One server instance; snapshots never expose mutable internal rows."""

    def __init__(self):
        self._lock = threading.Lock()
        self._instance_id = str(uuid.uuid4())
        self._counts = {reason: dict.fromkeys(ROUTE_CLASSES, 0) for reason in REASONS}
        self._native_pipe_provider = None

    def set_native_pipe_provider(self, provider):
        if not callable(provider):
            raise ValueError('Invalid private native diagnostic provider.')
        with self._lock:
            self._native_pipe_provider = provider

    def increment(self, reason, route_class='other'):
        if (type(reason) is not str or reason not in REASONS
                or type(route_class) is not str or route_class not in ROUTE_CLASSES):
            raise ValueError('Invalid transport diagnostic classification.')
        with self._lock:
            self._counts[reason][route_class] = min(
                MAX_COUNT, self._counts[reason][route_class] + 1)

    def snapshot(self):
        with self._lock:
            value = {'protocol': 1, 'instance_id': self._instance_id,
                     'counts': {reason: dict(row) for reason, row in self._counts.items()}}
            provider = self._native_pipe_provider
        if provider is not None:
            from .native_pipe_diagnostics import valid_evidence
            native = provider()
            if valid_evidence(native):
                value['native_pipe'] = dict(native)
        return value
