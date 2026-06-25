"""Guard tests for the poor-network progressive-load KPIs + umbrella flag
(2026-06-24, slow-link "first usable image as early as possible" review).

Covers:
  * ``SocketConfig.is_poor_network_progressive_load_enabled`` resolution:
    env ``AIPACS_POOR_NETWORK_PROGRESSIVE_LOAD`` decisive (on/off); otherwise it
    MIRRORS the per-server poor-connectivity flag; fail-safe to False.
  * The ``[KPI]`` TTFI / TTFS / TTFC markers + the ``_POOR_NET_KPIS`` kill switch
    are wired into ``socket_client.download_series`` (source-pin — the download
    loop needs a live socket to exercise functionally; the markers are pure
    additive logging with no control-flow effect, so a wiring pin is the right
    guard).
  * The viewer-side ``[KPI] kind=TTFI scope=viewer`` marker is wired into
    ``qt_viewer_bridge``.

These are deliberately import-light (no PySide6 / no socket) so they run in the
offscreen verify lane.
"""
from pathlib import Path

import pytest


def _repo_root() -> Path:
    p = Path(__file__).resolve()
    for anc in p.parents:
        if (anc / "modules" / "network" / "socket_config.py").exists():
            return anc
    raise RuntimeError("repo root not found from %s" % __file__)


# --------------------------------------------------------------------------
# Umbrella-flag resolver (functional)
# --------------------------------------------------------------------------

@pytest.fixture()
def cfg():
    import modules.network.socket_config as sc
    return sc.get_socket_config()


def test_umbrella_env_forces_on(cfg, monkeypatch):
    monkeypatch.setenv("AIPACS_POOR_NETWORK_PROGRESSIVE_LOAD", "1")
    assert cfg.is_poor_network_progressive_load_enabled() is True


def test_umbrella_env_forces_off_wins_over_server(cfg, monkeypatch):
    # The umbrella OFF must win even when poor-connectivity is otherwise ON.
    monkeypatch.setenv("AIPACS_POOR_NETWORK_PROGRESSIVE_LOAD", "0")
    monkeypatch.setenv("AIPACS_POOR_CONNECTIVITY", "1")
    assert cfg.is_poor_network_progressive_load_enabled() is False


def test_umbrella_mirrors_poor_connectivity(cfg, monkeypatch):
    # No umbrella env → mirror the per-server poor-connectivity signal.
    monkeypatch.delenv("AIPACS_POOR_NETWORK_PROGRESSIVE_LOAD", raising=False)
    monkeypatch.setenv("AIPACS_POOR_CONNECTIVITY", "1")
    assert cfg.is_poor_network_progressive_load_enabled() is True
    monkeypatch.setenv("AIPACS_POOR_CONNECTIVITY", "0")
    assert cfg.is_poor_network_progressive_load_enabled() is False


def test_umbrella_module_level_never_raises(monkeypatch):
    import modules.network.socket_config as sc
    monkeypatch.delenv("AIPACS_POOR_NETWORK_PROGRESSIVE_LOAD", raising=False)
    monkeypatch.delenv("AIPACS_POOR_CONNECTIVITY", raising=False)
    assert sc.is_poor_network_progressive_load_enabled() in (True, False)


# --------------------------------------------------------------------------
# KPI marker wiring (source-pin)
# --------------------------------------------------------------------------

def test_kpi_markers_wired_in_socket_client():
    src = (_repo_root() / "modules" / "download_manager" / "network"
           / "socket_client.py").read_text(encoding="utf-8")
    # kill switch + default-on flag
    assert "_POOR_NET_KPIS" in src
    assert "AIPACS_POOR_NETWORK_KPIS" in src
    # TTFI / TTFS (one marker, kind chosen by count) + TTFC
    assert "kind=%s scope=download" in src
    assert "kind=TTFC scope=download" in src
    assert "avg_slice_ms" in src
    # TTFI/TTFS emitted only for a freshly-fetched series (no resume artifact)
    assert "skipped_count == 0 and downloaded_count in (1, 2)" in src


def test_kpi_marker_wired_in_viewer_bridge():
    src = (_repo_root() / "modules" / "viewer" / "fast"
           / "qt_viewer_bridge.py").read_text(encoding="utf-8")
    assert "kind=TTFI scope=viewer" in src
    assert "AIPACS_POOR_NETWORK_KPIS" in src
    # TTD (decode) + TTR (render) decomposition of the file→render path (review #6)
    assert "ttd_ms=" in src
    assert "ttr_ms=" in src

    # Live plugin-mirror parity (socket_client.py / qt_viewer_bridge.py are
    # mirrored) is enforced authoritatively by tools/dev/verify_plugin_mirrors.py,
    # not re-globbed here (that catches dist/ + backups/ build artifacts).


def test_ttssd_marker_wired_in_switch():
    """TTSSD = Time To Series Switch Display, anchored to the user drop/select →
    first visible image of the requested series (review areas #4/#5B)."""
    src = (_repo_root() / "PacsClient" / "pacs" / "patient_tab" / "ui"
           / "patient_ui" / "_vc_switch.py").read_text(encoding="utf-8")
    assert "kind=TTSSD scope=viewer" in src
    assert "ttssd_ms=" in src
    assert "AIPACS_POOR_NETWORK_KPIS" in src
