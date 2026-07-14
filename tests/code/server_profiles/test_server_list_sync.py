"""Welcome page ↔ Server Settings must render the SAME server list (2026-07-13).

Regression guard for the reported bug: *"when a server is deleted from Server
Settings it still remains in the Welcome Page server list"*.

Two stores existed:

* ``config/servers.json``          — edited by Settings ▸ Server Settings,
* ``config/server_profiles.json``  — read by the login/Welcome page picker.

``save_server()`` upserted a profile, but ``delete_server()`` never removed one
(and a RENAME orphaned the old profile as a duplicate, because the profile id is
derived from the name). The fix reconciles the WHOLE list from the single choke
point every mutation passes through (``SettingsServer.save_to_json``).

These tests pin the PURE reconciler + the wiring. Pure stdlib — no Qt.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from PacsClient.utils import server_profiles as sp


# ── helpers ──────────────────────────────────────────────────────────────────
def _srv(name, host, port="104", ae="aipacs", poor=False):
    return {
        "name": name,
        "host": host,
        "port": port,
        "ae_title": ae,
        "poor_connectivity": poor,
    }


def _doc(profiles, active="", primary=""):
    return {
        "schema_version": sp.SCHEMA_VERSION,
        "enabled": True,
        "primary_profile_id": primary,
        "active_profile_id": active,
        "profiles": profiles,
    }


def _prof(pid, name, host, **kw):
    return sp.ServerProfile(id=pid, display_name=name, host=host, **kw).to_dict()


def _names(doc):
    return [p["display_name"] for p in doc["profiles"]]


def _ids(doc):
    return [p["id"] for p in doc["profiles"]]


# ── THE BUG: delete must propagate ───────────────────────────────────────────
def test_deleting_a_server_removes_its_profile():
    doc = _doc(
        [_prof("razi", "razi", "192.168.2.222"), _prof("mehr", "mehr", "10.0.0.9")],
        active="razi",
    )
    # Server Settings deleted "mehr" -> servers.json now holds only razi.
    out = sp.reconcile_profiles(doc, [_srv("razi", "192.168.2.222")])

    assert _names(out) == ["razi"], "deleted server still present in the profile store"
    assert "mehr" not in _ids(out)


def test_deleting_the_ACTIVE_server_repoints_active():
    doc = _doc(
        [_prof("razi", "razi", "192.168.2.222"), _prof("mehr", "mehr", "10.0.0.9")],
        active="mehr",
    )
    out = sp.reconcile_profiles(doc, [_srv("razi", "192.168.2.222")])
    assert out["active_profile_id"] == "razi"


def test_deleting_every_server_empties_the_list():
    doc = _doc([_prof("razi", "razi", "192.168.2.222")], active="razi")
    out = sp.reconcile_profiles(doc, [])
    assert out["profiles"] == []
    assert out["active_profile_id"] == ""


# ── add / edit / rename ──────────────────────────────────────────────────────
def test_adding_a_server_creates_a_profile():
    doc = _doc([_prof("razi", "razi", "192.168.2.222")], active="razi")
    out = sp.reconcile_profiles(
        doc, [_srv("razi", "192.168.2.222"), _srv("Mehr Center", "10.0.0.9")]
    )
    assert _names(out) == ["razi", "Mehr Center"]


def test_editing_host_updates_in_place():
    doc = _doc([_prof("razi", "razi", "192.168.2.222")], active="razi")
    out = sp.reconcile_profiles(doc, [_srv("razi", "192.168.2.250")])
    assert len(out["profiles"]) == 1
    assert out["profiles"][0]["host"] == "192.168.2.250"


def test_rename_keeps_the_SAME_id_and_does_not_duplicate():
    """A rename must not orphan the old profile — the id is the data-namespace key,
    so a new id would silently move the centre's data root."""
    doc = _doc(
        [_prof("razi", "razi", "192.168.2.222", socket_port=50055)], active="razi"
    )
    out = sp.reconcile_profiles(doc, [_srv("Razi Imaging Center", "192.168.2.222")])

    assert len(out["profiles"]) == 1, "rename duplicated the profile"
    assert out["profiles"][0]["id"] == "razi", "rename changed the data-namespace id"
    assert out["profiles"][0]["display_name"] == "Razi Imaging Center"
    assert out["active_profile_id"] == "razi"


def test_reconcile_preserves_socket_port_and_module_endpoints():
    """servers.json owns name/host/DICOM-port/AE; the SOCKET port and the per-centre
    AI/reception endpoints live only on the profile and must survive."""
    doc = _doc(
        [
            _prof(
                "razi",
                "razi",
                "192.168.2.222",
                socket_port=50055,
                modules={"ai_breast": "192.168.2.222:8010"},
            )
        ],
        active="razi",
    )
    out = sp.reconcile_profiles(doc, [_srv("razi", "192.168.2.222", port="105")])
    p = out["profiles"][0]
    assert p["socket_port"] == 50055
    assert p["modules"]["ai_breast"] == "192.168.2.222:8010"
    assert p["dicom_port"] == 105  # servers.json IS the authority for this one


def test_reconcile_is_idempotent():
    servers = [_srv("razi", "192.168.2.222"), _srv("mehr", "10.0.0.9")]
    once = sp.reconcile_profiles(_doc([]), servers)
    twice = sp.reconcile_profiles(once, servers)
    assert once == twice


def test_two_servers_on_the_same_host_stay_distinct():
    out = sp.reconcile_profiles(
        _doc([]), [_srv("A", "10.0.0.9"), _srv("B", "10.0.0.9")]
    )
    assert len(out["profiles"]) == 2
    assert len(set(_ids(out))) == 2


# ── persistence wrappers (write through the real files) ──────────────────────
@pytest.fixture()
def cfg(tmp_path, monkeypatch):
    monkeypatch.setenv("AIPACS_CONFIG_DIR", str(tmp_path))
    monkeypatch.delenv("AIPACS_SERVER_PROFILES_PATH", raising=False)
    monkeypatch.setenv("AIPACS_SERVER_PROFILES", "1")
    monkeypatch.delenv("AIPACS_SERVER_LIST_SYNC", raising=False)
    return tmp_path


def test_sync_profiles_with_servers_persists_the_deletion(cfg: Path):
    sp.save_profiles_document(
        _doc(
            [_prof("razi", "razi", "192.168.2.222"), _prof("mehr", "mehr", "10.0.0.9")],
            active="razi",
        )
    )
    sp.sync_profiles_with_servers([_srv("razi", "192.168.2.222")])

    # This is exactly what the Welcome page reads.
    assert [p.display_name for p in sp.list_profiles()] == ["razi"]


def test_sync_is_skipped_when_kill_switch_off(cfg: Path, monkeypatch):
    sp.save_profiles_document(_doc([_prof("mehr", "mehr", "10.0.0.9")], active="mehr"))
    monkeypatch.setenv("AIPACS_SERVER_LIST_SYNC", "0")
    assert sp.sync_profiles_with_servers([]) is None
    assert [p.id for p in sp.list_profiles()] == ["mehr"]  # legacy behaviour kept


def test_sync_does_not_create_the_store_for_a_legacy_install(cfg: Path, monkeypatch):
    """Feature off + no profiles file -> byte-identical legacy (no file created)."""
    monkeypatch.setenv("AIPACS_SERVER_PROFILES", "0")
    assert sp.sync_profiles_with_servers([_srv("razi", "192.168.2.222")]) is None
    assert not (cfg / sp.PROFILES_FILENAME).exists()


def test_reverse_mirror_writes_profile_back_into_servers_json(cfg: Path):
    """An edit made on the Welcome page must show up in the Server Settings table."""
    (cfg / "servers.json").write_text(
        json.dumps([_srv("razi", "192.168.2.222", port="104", ae="aipacs")]),
        encoding="utf-8",
    )
    prof = sp.ServerProfile(
        id="razi", display_name="razi", host="192.168.2.250", ae_title="RAZI2"
    )
    assert sp.write_profile_to_servers_json(prof) is True

    records = json.loads((cfg / "servers.json").read_text(encoding="utf-8"))
    assert len(records) == 1, "reverse mirror duplicated the servers.json record"
    assert records[0]["host"] == "192.168.2.250"
    assert records[0]["ae_title"] == "RAZI2"


# ── wiring: the reconcile must hang off the ONE choke point ──────────────────
def test_settings_save_to_json_calls_the_reconciler():
    src = (
        Path(__file__).resolve().parents[3]
        / "PacsClient"
        / "pacs"
        / "workstation_ui"
        / "settings_ui"
        / "server_settings.py"
    ).read_text(encoding="utf-8", errors="replace")

    assert "_sync_server_profiles" in src
    # It must be invoked from save_to_json (through which add/edit/rename/DELETE
    # all pass) — not bolted onto save_server only.
    tail = src.split("def save_to_json", 1)[1][:600]
    assert "_sync_server_profiles(servers)" in tail
    assert "sync_profiles_with_servers" in src
