"""Guard: A1 network reachability monitor (OPT-04 / DM resume, 2026-07-08).

Pure stdlib module — no Qt — so it runs headless. Pins the edge semantics the
DM widget relies on: startup fires NO edge, only offline→online fires one, and
consume_online_edge() is one-shot.
"""
from modules.download_manager.network.net_monitor import (
    NetworkReachabilityMonitor,
    probe_reachable,
)


def test_no_edge_on_startup_when_first_probe_is_online():
    m = NetworkReachabilityMonitor("host", 1, probe=lambda *a: True)
    # First observation (was=None) must NOT be treated as an edge.
    assert m._record(True) is False
    assert m.consume_online_edge() is False
    assert m.is_online() is True


def test_offline_then_online_fires_exactly_one_edge():
    m = NetworkReachabilityMonitor("host", 1, probe=lambda *a: True)
    assert m._record(False) is False          # went offline (no edge)
    assert m._record(True) is True            # offline→online EDGE
    assert m.consume_online_edge() is True     # consumed once
    assert m.consume_online_edge() is False    # and cleared


def test_staying_online_fires_no_edge():
    m = NetworkReachabilityMonitor("host", 1)
    m._record(True)
    assert m._record(True) is False
    assert m._record(True) is False


def test_probe_unreachable_returns_false_and_never_raises():
    # Port 1 on loopback is closed; must return False, not raise.
    assert probe_reachable("127.0.0.1", 1, timeout=0.2) is False
