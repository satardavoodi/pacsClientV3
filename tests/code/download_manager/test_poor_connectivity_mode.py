"""Guards for the per-server "Poor Connectivity" download mode (2026-06-19).

Feature: a per-server boolean ``poor_connectivity`` in ``config/servers.json``
(toggled from Settings -> Servers). When enabled for the active download server,
``SocketDicomClient.download_series`` fetches ONE image per batch and disables
adaptive batch growth, so a slow/unstable link retries at the image level and
keeps every image already on disk (atomic ``.part`` + R19 resume) instead of
failing/re-fetching a whole multi-image batch. It reuses the *exact* mechanism of
the existing large-frame-modality force-single path, so there is no new
duplicate-download / cache-inconsistency risk.

Delivery across the download-subprocess boundary: the flag is resolved by
``modules.network.socket_config.SocketConfig.is_poor_connectivity_enabled()``
against the host the subprocess actually connects to (``socket_host`` from
``socket_config.json``), matched to the ``servers.json`` record. Env
``AIPACS_POOR_CONNECTIVITY`` is a manual override / master kill switch.

These tests pin (1) the resolver's precedence + per-server host matching and
(2) that the flag is actually wired into ``download_series`` (so the helper can't
pass while being dead code), plus the UI persistence + plugin-mirror parity.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

_SRC = (
    _REPO_ROOT / "modules/download_manager/network/socket_client.py"
).read_text(encoding="utf-8")
_CFG_SRC = (
    _REPO_ROOT / "modules/network/socket_config.py"
).read_text(encoding="utf-8")
_UI_SRC = (
    _REPO_ROOT / "PacsClient/pacs/workstation_ui/settings_ui/server_settings.py"
).read_text(encoding="utf-8")


def _socket_config_module():
    try:
        import modules.network.socket_config as mod
    except Exception as exc:  # heavy/absent deps in a minimal shard
        pytest.skip(f"socket_config import unavailable: {exc}")
    return mod


@pytest.fixture
def cfg(tmp_path):
    """A SocketConfig backed by a throwaway file (never touches the real one)."""
    mod = _socket_config_module()
    return mod.SocketConfig(config_path=str(tmp_path / "socket_config.json"))


def _patch_servers(monkeypatch, servers):
    try:
        import PacsClient.utils.utils as u
    except Exception as exc:
        pytest.skip(f"PacsClient.utils.utils unavailable: {exc}")
    monkeypatch.setattr(u, "get_all_servers", lambda: list(servers), raising=False)


# ---- resolver: env override (decisive, no servers.json needed) -----------

def test_env_force_on(cfg, monkeypatch):
    monkeypatch.setenv("AIPACS_POOR_CONNECTIVITY", "1")
    assert cfg.is_poor_connectivity_enabled() is True


def test_env_force_off_overrides_matching_poor_server(cfg, monkeypatch):
    # Master kill switch: env "0" wins even if the active server is flagged poor.
    monkeypatch.setenv("AIPACS_POOR_CONNECTIVITY", "0")
    _patch_servers(monkeypatch, [{"host": "1.2.3.4", "poor_connectivity": True}])
    cfg.set("socket_host", "1.2.3.4")
    assert cfg.is_poor_connectivity_enabled() is False


# ---- resolver: per-server resolution by active socket host ---------------

def test_host_match_poor_true(cfg, monkeypatch):
    monkeypatch.delenv("AIPACS_POOR_CONNECTIVITY", raising=False)
    _patch_servers(monkeypatch, [{"host": "5.57.36.202", "poor_connectivity": True}])
    cfg.set("socket_host", "5.57.36.202")
    assert cfg.is_poor_connectivity_enabled() is True


def test_host_match_flag_absent_is_false(cfg, monkeypatch):
    # Untouched/normal servers have no flag -> normal adaptive batching.
    monkeypatch.delenv("AIPACS_POOR_CONNECTIVITY", raising=False)
    _patch_servers(monkeypatch, [{"host": "192.168.2.222"}])
    cfg.set("socket_host", "192.168.2.222")
    assert cfg.is_poor_connectivity_enabled() is False


def test_host_match_flag_false_is_false(cfg, monkeypatch):
    monkeypatch.delenv("AIPACS_POOR_CONNECTIVITY", raising=False)
    _patch_servers(monkeypatch, [{"host": "192.168.2.222", "poor_connectivity": False}])
    cfg.set("socket_host", "192.168.2.222")
    assert cfg.is_poor_connectivity_enabled() is False


def test_no_host_match_is_false(cfg, monkeypatch):
    # A poor server exists but it is NOT the active host -> server-specific: off.
    monkeypatch.delenv("AIPACS_POOR_CONNECTIVITY", raising=False)
    _patch_servers(monkeypatch, [{"host": "10.0.0.1", "poor_connectivity": True}])
    cfg.set("socket_host", "192.168.2.222")
    assert cfg.is_poor_connectivity_enabled() is False


def test_two_servers_only_active_poor_one_engages(cfg, monkeypatch):
    monkeypatch.delenv("AIPACS_POOR_CONNECTIVITY", raising=False)
    _patch_servers(monkeypatch, [
        {"host": "192.168.2.222", "poor_connectivity": False},  # razi: fast LAN
        {"host": "5.57.36.202", "poor_connectivity": True},     # mehr: poor WAN
    ])
    cfg.set("socket_host", "5.57.36.202")
    assert cfg.is_poor_connectivity_enabled() is True
    cfg.set("socket_host", "192.168.2.222")
    assert cfg.is_poor_connectivity_enabled() is False


def test_empty_host_is_false(cfg, monkeypatch):
    monkeypatch.delenv("AIPACS_POOR_CONNECTIVITY", raising=False)
    cfg.set("socket_host", "")
    assert cfg.is_poor_connectivity_enabled() is False


def test_resolver_never_raises_on_bad_servers(cfg, monkeypatch):
    # A broken servers loader must degrade to False, never break downloading.
    monkeypatch.delenv("AIPACS_POOR_CONNECTIVITY", raising=False)
    try:
        import PacsClient.utils.utils as u
    except Exception as exc:
        pytest.skip(f"PacsClient.utils.utils unavailable: {exc}")

    def _boom():
        raise RuntimeError("servers.json unreadable")

    monkeypatch.setattr(u, "get_all_servers", _boom, raising=False)
    cfg.set("socket_host", "192.168.2.222")
    assert cfg.is_poor_connectivity_enabled() is False


# ---- socket_config source surface ---------------------------------------

def test_socket_config_exposes_resolver_and_env():
    assert "def is_poor_connectivity_enabled(self" in _CFG_SRC
    assert "AIPACS_POOR_CONNECTIVITY" in _CFG_SRC
    assert "poor_connectivity" in _CFG_SRC
    # module-level convenience used by the download client
    assert "def is_poor_connectivity_enabled() -> bool:" in _CFG_SRC


# ---- wiring into download_series (catches a refactor that drops it) ------

def test_client_helper_reads_socket_config():
    assert "def _poor_connectivity_active(self)" in _SRC
    assert "from modules.network.socket_config import" in _SRC
    assert "is_poor_connectivity_enabled as _ipc" in _SRC


def test_download_series_computes_force_single_from_poor_conn():
    assert "_poor_conn = self._poor_connectivity_active()" in _SRC
    assert "_force_single = _modality_force_single or _poor_conn" in _SRC
    # poor-connectivity pins one image per batch
    assert "if _poor_conn:" in _SRC
    assert _SRC.count("batch_size = 1") >= 2  # modality path + poor-conn path


def test_other_force_single_sites_use_combined_flag():
    # The legacy modality predicate is evaluated exactly ONCE (into
    # _modality_force_single); the first-image-prime arg and the adaptive-growth
    # gate now use the combined _force_single, so poor-connectivity also suppresses
    # the prime and the ramp-up. (The function definition line uses "series_info:"
    # and is not matched by the "(series_info)" call form.)
    assert _SRC.count("_should_force_single_instance_batches(series_info)") == 1
    assert "and not _force_single" in _SRC


def test_poor_conn_logs_mode_and_batch_size():
    # Requirement: log that the mode is active and the batch size in use.
    assert "[POOR_CONN]" in _SRC
    assert "batch_size=1" in _SRC


# ---- UI persistence + plugin-mirror parity -------------------------------

def test_ui_checkbox_persists_flag():
    assert "self.poor_conn_check" in _UI_SRC
    assert "QCheckBox" in _UI_SRC
    assert "'poor_connectivity': self.poor_conn_check.isChecked()" in _UI_SRC


def test_plugin_mirror_carries_the_change():
    mir = (
        _REPO_ROOT
        / "builder/plugin package/packages/download_manager/payload/python"
        / "modules/download_manager/network/socket_client.py"
    )
    if not mir.exists():
        pytest.skip("download_manager plugin mirror not present")
    t = mir.read_text(encoding="utf-8")
    assert "_force_single = _modality_force_single or _poor_conn" in t
    assert "def _poor_connectivity_active(self)" in t
