"""Bounded transport diagnostics contain only fixed classifications."""
from concurrent.futures import ThreadPoolExecutor
import json

import pytest


def test_fixed_snapshot_defaults_and_isolation():
    from modules.ai_imaging.eagle_eye_remote.transport_diagnostics import Counters, REASONS, ROUTE_CLASSES
    counters = Counters()
    result = counters.snapshot()
    assert result['protocol'] == 1
    assert set(result['counts']) == set(REASONS)
    assert all(set(row) == set(ROUTE_CLASSES) and not any(row.values()) for row in result['counts'].values())
    result['counts']['handler_started']['other'] = 99
    assert counters.snapshot()['counts']['handler_started']['other'] == 0
    assert counters.snapshot()['instance_id'] == result['instance_id']


def test_threaded_updates_do_not_lose_counts():
    from modules.ai_imaging.eagle_eye_remote.transport_diagnostics import Counters
    counters = Counters()
    def add(_):
        for _ in range(500):
            counters.increment('response_completed', route_class='auth_session')
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(add, range(8)))
    assert counters.snapshot()['counts']['response_completed']['auth_session'] == 4000


@pytest.mark.parametrize('reason,route', [('secret-token', 'other'), ('handler_started', '/private/path'), (None, 'other')])
def test_untrusted_labels_are_rejected_without_echo(reason, route):
    from modules.ai_imaging.eagle_eye_remote.transport_diagnostics import Counters
    counters = Counters()
    with pytest.raises(ValueError) as caught:
        counters.increment(reason, route_class=route)
    assert str(caught.value) == 'Invalid transport diagnostic classification.'
    snapshot = json.dumps(counters.snapshot())
    assert 'secret-token' not in snapshot and '/private/path' not in snapshot


def test_counts_saturate_without_growth():
    from modules.ai_imaging.eagle_eye_remote.transport_diagnostics import Counters, MAX_COUNT
    counters = Counters()
    counters._counts['response_completed']['auth_me'] = MAX_COUNT - 1
    counters.increment('response_completed', route_class='auth_me')
    counters.increment('response_completed', route_class='auth_me')
    assert counters.snapshot()['counts']['response_completed']['auth_me'] == MAX_COUNT
