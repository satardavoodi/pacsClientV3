"""Guard: OPT-24 patient-search client-side waste removal (2026-07-11).

Context (measured, 2026-07-11 logs): the ~5 s patient-list latency is SERVER-side
(`[NET_TIMING] endpoint=GetPatientList server_wait_ms=5016..5941 transfer_ms=0-1
parse_ms=0`), while a patient_id lookup on the SAME socket returns in 139 ms. The
client cannot remove that — but it WAS adding avoidable work to every search:

  * `test_connection()` pre-flight = a FULL extra GetPatientList round-trip
    (~125 ms). ~140 of 215 server calls in one session were just these probes.
  * `socket_service.cleanup()` after each search closed all 5 pooled connections,
    so the connection pool never pooled anything (95 rebuilds / session).
  * the socket config FILE was rewritten to disk on every search (111 writes).

These tests pin the decision logic + every kill switch. The socket-config save-skip
is exercised against the REAL method.
"""

import importlib

import pytest


# ── config save-skip (real method) ─────────────────────────────────────
socket_config = importlib.import_module("modules.network.socket_config")


def _cfg(monkeypatch, host="1.2.3.4", port=50052):
    cfg = socket_config.SocketConfig.__new__(socket_config.SocketConfig)
    store = {"socket_host": host, "socket_port": port}
    saves = []
    monkeypatch.setattr(cfg, "get", lambda k, d=None: store.get(k, d), raising=False)
    monkeypatch.setattr(cfg, "set", lambda k, v: store.__setitem__(k, v), raising=False)
    monkeypatch.setattr(cfg, "save_config", lambda: saves.append(1), raising=False)
    return cfg, store, saves


def test_config_not_rewritten_when_host_port_unchanged(monkeypatch):
    monkeypatch.delenv("AIPACS_SOCKET_CFG_SKIP_UNCHANGED_SAVE", raising=False)
    cfg, store, saves = _cfg(monkeypatch)
    cfg.update_server_settings("1.2.3.4", 50052)
    assert saves == [], "unchanged host/port must NOT rewrite the config file"
    # in-memory values still set
    assert store["socket_host"] == "1.2.3.4"
    assert store["socket_port"] == 50052


def test_config_written_when_settings_change(monkeypatch):
    monkeypatch.delenv("AIPACS_SOCKET_CFG_SKIP_UNCHANGED_SAVE", raising=False)
    cfg, store, saves = _cfg(monkeypatch)
    cfg.update_server_settings("9.9.9.9", 50052)
    assert len(saves) == 1, "a real change must still persist"
    assert store["socket_host"] == "9.9.9.9"


def test_config_save_kill_switch_restores_legacy(monkeypatch):
    monkeypatch.setenv("AIPACS_SOCKET_CFG_SKIP_UNCHANGED_SAVE", "0")
    cfg, _store, saves = _cfg(monkeypatch)
    cfg.update_server_settings("1.2.3.4", 50052)
    assert len(saves) == 1, "kill switch: always save (legacy behaviour)"


def test_config_save_to_file_false_never_writes(monkeypatch):
    monkeypatch.delenv("AIPACS_SOCKET_CFG_SKIP_UNCHANGED_SAVE", raising=False)
    cfg, _store, saves = _cfg(monkeypatch)
    cfg.update_server_settings("9.9.9.9", 50052, save_to_file=False)
    assert saves == []


# ── probe-skip / keep-pool / enrich-probe decisions ────────────────────
def _env_on(env, name, default="1"):
    return (env.get(name, default) or default).strip() != "0"


def _should_probe(env, fresh):
    """Mirrors search_server: probe only when not skipping, or connectivity stale."""
    return (not _env_on(env, "AIPACS_SEARCH_SKIP_PROBE")) or (not fresh)


def test_probe_runs_on_first_search_but_is_skipped_when_fresh():
    # First search of a session: connectivity unknown -> probe (correctness).
    assert _should_probe({}, fresh=False) is True
    # Connectivity proven by a recent successful search -> SKIP the round-trip.
    assert _should_probe({}, fresh=True) is False


def test_probe_kill_switch_restores_per_search_probe():
    assert _should_probe({"AIPACS_SEARCH_SKIP_PROBE": "0"}, fresh=True) is True


@pytest.mark.parametrize(
    "flag", ["AIPACS_SEARCH_KEEP_POOL", "AIPACS_SEARCH_ENRICH_PROBE", "AIPACS_SEARCH_SKIP_PROBE"]
)
def test_flags_default_on_with_kill_switch(flag):
    assert _env_on({}, flag) is True           # default ON
    assert _env_on({flag: "0"}, flag) is False  # kill switch


# ── connectivity TTL semantics ─────────────────────────────────────────
class _Svc:
    """Mirrors HomeSearchService._connectivity_is_fresh/_mark_connectivity."""

    def __init__(self, now):
        self._now = now
        self._conn_ok_until = 0.0

    def fresh(self):
        return self._now() < float(self._conn_ok_until or 0.0)

    def mark(self, ok, ttl=300.0):
        self._conn_ok_until = (self._now() + ttl) if ok else 0.0


def test_connectivity_ttl_expires_and_failure_forces_reprobe():
    t = [1000.0]
    svc = _Svc(lambda: t[0])

    assert svc.fresh() is False          # unknown at start -> probe
    svc.mark(True, ttl=300.0)
    assert svc.fresh() is True           # recent success -> skip probe

    t[0] += 299.0
    assert svc.fresh() is True           # still inside TTL
    t[0] += 2.0
    assert svc.fresh() is False          # TTL expired -> probe again

    svc.mark(True, ttl=300.0)
    assert svc.fresh() is True
    svc.mark(False)                      # a failure must force an immediate re-probe
    assert svc.fresh() is False


def test_empty_result_must_be_verified_when_probe_was_skipped():
    """search_patients_sync returns [] for BOTH 'no patients' and 'connection dead',
    so an empty result on a skipped-probe search must trigger a verification probe."""
    def needs_verify(patients, probed):
        return (not patients) and (not probed)

    assert needs_verify([], probed=False) is True    # empty + skipped -> verify
    assert needs_verify([], probed=True) is False    # already probed this search
    assert needs_verify([{"patient_id": "1"}], probed=False) is False  # got rows -> fine


# ── OPT-24c: the singleton getter must NOT rebuild the pool every call ─────
class _Pool:
    def __init__(self, host, port):
        self.host, self.port = host, port


class _Svc2:
    """Mirrors SocketPatientService.reload_if_server_changed."""

    def __init__(self, host, port):
        self.connection_pool = _Pool(host, port)
        self._cfg = {"h": host, "p": port}
        self.rebuilds = 0

    def reload_connection(self):
        self.rebuilds += 1
        self.connection_pool = _Pool(self._cfg["h"], self._cfg["p"])

    def reload_if_server_changed(self, env=None):
        env = env or {}
        if (env.get("AIPACS_SOCKET_POOL_REUSE", "1") or "1").strip() == "0":
            self.reload_connection()
            return True
        pool = self.connection_pool
        if pool is None:
            self.reload_connection()
            return True
        if str(pool.host) != str(self._cfg["h"]) or int(pool.port) != int(self._cfg["p"]):
            self.reload_connection()
            return True
        return False


def test_pool_is_reused_when_server_unchanged():
    svc = _Svc2("1.2.3.4", 50052)
    for _ in range(10):           # 10 searches
        svc.reload_if_server_changed()
    assert svc.rebuilds == 0, "warm pool must be reused across searches"


def test_pool_rebuilt_when_server_changes():
    svc = _Svc2("1.2.3.4", 50052)
    svc._cfg["h"] = "9.9.9.9"     # user switched server profile
    assert svc.reload_if_server_changed() is True
    assert svc.rebuilds == 1


def test_pool_reuse_kill_switch():
    svc = _Svc2("1.2.3.4", 50052)
    svc.reload_if_server_changed({"AIPACS_SOCKET_POOL_REUSE": "0"})
    assert svc.rebuilds == 1, "kill switch: always reload (legacy)"


def test_pool_none_falls_back_to_legacy_reload():
    svc = _Svc2("1.2.3.4", 50052)
    svc.connection_pool = None
    assert svc.reload_if_server_changed() is True
    assert svc.rebuilds == 1
