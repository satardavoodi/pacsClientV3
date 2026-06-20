"""Unit tests for the pure multi-server profile foundation.

These load ``PacsClient/utils/server_profiles.py`` directly by file path so the
suite runs without PySide6 or the heavy ``PacsClient.utils`` import chain — the
module is pure stdlib by design.
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest

_MODULE_PATH = (
    Path(__file__).resolve().parents[3] / "PacsClient" / "utils" / "server_profiles.py"
)


def _load_module():
    spec = importlib.util.spec_from_file_location("server_profiles_under_test", _MODULE_PATH)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    # Register before exec so @dataclass annotation resolution can find the module
    # in sys.modules (Python 3.13 dataclasses._is_type requirement).
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


sp = _load_module()


@pytest.fixture()
def profiles_file(tmp_path, monkeypatch):
    """Point the module at an isolated temp profiles file + config dir."""
    cfg_dir = tmp_path / "config"
    cfg_dir.mkdir()
    path = cfg_dir / "server_profiles.json"
    monkeypatch.setenv(sp._ENV_PROFILES_PATH, str(path))
    monkeypatch.setenv(sp._ENV_CONFIG_DIR, str(cfg_dir))
    monkeypatch.delenv(sp._ENV_FLAG, raising=False)
    return path


# ── dataclass round-trip ─────────────────────────────────────────────────────
def test_profile_roundtrip_and_module_slots():
    prof = sp.ServerProfile(id="razi", display_name="Razi", host="192.168.2.222",
                            socket_port=50052, dicom_port=105)
    d = prof.to_dict()
    # every well-known module slot is present (None when unset)
    for key in sp.MODULE_ENDPOINT_KEYS:
        assert key in d["modules"]
    back = sp.ServerProfile.from_dict(d)
    assert back.id == "razi"
    assert back.socket_target() == ("192.168.2.222", 50052)
    assert back.dicom_port == 105
    assert back.ae_title == "aipacs"


def test_from_dict_coerces_and_defaults():
    prof = sp.ServerProfile.from_dict({"name": "Mehr", "host": "5.57.36.202", "port": "104"})
    # id derived from name when absent
    assert prof.id == "Mehr"
    assert prof.display_name == "Mehr"
    # servers.json "port" maps to dicom_port; socket defaults to 50052
    assert prof.dicom_port == 104
    assert prof.socket_port == sp.DEFAULT_SOCKET_PORT
    # bad socket port falls back to default, never raises
    p2 = sp.ServerProfile.from_dict({"id": "x", "host": "h", "socket_port": "not-a-port"})
    assert p2.socket_port == sp.DEFAULT_SOCKET_PORT


def test_module_endpoint_accessor():
    prof = sp.ServerProfile.from_dict(
        {"id": "razi", "host": "h", "modules": {"ai_breast": "192.168.2.222:8002", "bonj": "   "}}
    )
    assert prof.module_endpoint("ai_breast") == "192.168.2.222:8002"
    assert prof.module_endpoint("bonj") is None  # blank → None
    assert prof.module_endpoint("missing") is None


# ── data-namespace key ───────────────────────────────────────────────────────
def test_data_segment_is_filesystem_safe():
    assert sp.data_segment("razi") == "razi"
    assert sp.data_segment("Mehr Center #2") == "Mehr_Center_2"
    assert sp.data_segment("") == "default"
    # unicode / punctuation-only never yields an empty or unsafe name
    seg = sp.data_segment("…/…")
    assert seg and all(c.isalnum() or c in "._-" for c in seg)


# ── legacy migration (pure) ──────────────────────────────────────────────────
def test_build_profiles_from_legacy_matches_active_host_and_ports():
    servers = [
        {"name": "razi", "host": "192.168.2.222", "port": "105", "ae_title": "aipacs", "poor_connectivity": False},
        {"name": "mehr", "host": "5.57.36.202", "port": "104", "ae_title": "aipacs"},
    ]
    socket_cfg = {"socket_host": "192.168.2.222", "socket_port": 50052}
    ai = {"services": {"breast": "192.168.2.222:8002", "boneage": "192.168.2.222:8003",
                       "segmentation": "192.168.2.222:9000"}}
    doc = sp.build_profiles_from_legacy(servers, socket_cfg, ai)

    assert doc["active_profile_id"] == "razi"          # matches socket_host
    by_id = {p["id"]: p for p in doc["profiles"]}
    assert by_id["razi"]["socket_port"] == 50052
    assert by_id["razi"]["dicom_port"] == 105
    assert by_id["mehr"]["dicom_port"] == 104
    assert by_id["mehr"]["socket_port"] == sp.DEFAULT_SOCKET_PORT
    # AI services attributed to the matching host (razi) only, not mehr
    assert by_id["razi"]["modules"]["ai_breast"] == "192.168.2.222:8002"
    assert by_id["mehr"]["modules"]["ai_breast"] is None


def test_build_profiles_empty_is_safe():
    doc = sp.build_profiles_from_legacy([], {}, {})
    assert doc["profiles"] == []
    assert doc["active_profile_id"] == ""


# ── file load/save + migration-on-missing ───────────────────────────────────
def test_load_migrates_when_missing(profiles_file):
    cfg_dir = profiles_file.parent
    (cfg_dir / "servers.json").write_text(json.dumps([
        {"name": "razi", "host": "192.168.2.222", "port": "105", "ae_title": "aipacs"},
        {"name": "mehr", "host": "5.57.36.202", "port": "104", "ae_title": "aipacs"},
    ]), encoding="utf-8")
    (cfg_dir / "socket_config.json").write_text(json.dumps(
        {"socket_host": "192.168.2.222", "socket_port": 50052}), encoding="utf-8")
    (cfg_dir / "servers_address.json").write_text(json.dumps(
        {"services": {"breast": "192.168.2.222:8002"}}), encoding="utf-8")

    assert not profiles_file.exists()
    doc = sp.load_profiles_document()
    assert profiles_file.exists()                       # migration persisted
    assert doc["active_profile_id"] == "razi"
    ids = {p["id"] for p in doc["profiles"]}
    assert ids == {"razi", "mehr"}


def test_active_set_get_and_crud(profiles_file):
    sp.upsert_profile(sp.ServerProfile(id="razi", display_name="Razi", host="192.168.2.222",
                                       socket_port=50052, dicom_port=105))
    sp.upsert_profile(sp.ServerProfile(id="mehr", display_name="Mehr", host="5.57.36.202",
                                       socket_port=50052, dicom_port=104))
    assert {p.id for p in sp.list_profiles()} == {"razi", "mehr"}

    assert sp.set_active_profile_id("mehr") is True
    assert sp.get_active_profile_id() == "mehr"
    assert sp.get_active_profile().host == "5.57.36.202"
    assert sp.set_active_profile_id("nope") is False    # unknown id rejected

    # update existing (no duplicate)
    sp.upsert_profile(sp.ServerProfile(id="mehr", display_name="Mehr 2", host="5.57.36.202",
                                       socket_port=60000, dicom_port=104))
    assert len(sp.list_profiles()) == 2
    assert sp.get_profile("mehr").socket_port == 60000

    # delete reassigns active
    sp.delete_profile("mehr")
    assert {p.id for p in sp.list_profiles()} == {"razi"}
    assert sp.get_active_profile_id() == "razi"


def test_feature_flag_default_off_and_active_segment(profiles_file, monkeypatch):
    sp.upsert_profile(sp.ServerProfile(id="razi", display_name="Razi", host="h"))   # primary
    sp.upsert_profile(sp.ServerProfile(id="mehr", display_name="Mehr", host="h2"))  # secondary
    sp.set_active_profile_id("razi")
    # default off → namespace stays "default" so the legacy single-root layout holds
    assert sp.server_profiles_enabled() is False
    assert sp.active_data_segment() == "default"
    # enabled + primary active → still "default" (primary keeps the legacy root,
    # so enabling moves NO existing data)
    monkeypatch.setenv(sp._ENV_FLAG, "1")
    assert sp.server_profiles_enabled() is True
    assert sp.active_data_segment() == "default"
    # switching to a SECONDARY center → its own namespace folder
    sp.set_active_profile_id("mehr")
    assert sp.active_data_segment() == "mehr"


def test_socket_port_resolution_per_profile(profiles_file):
    sp.upsert_profile(sp.ServerProfile(id="razi", display_name="Razi", host="192.168.2.222",
                                       socket_port=50052, dicom_port=105))
    sp.upsert_profile(sp.ServerProfile(id="mehr", display_name="Mehr", host="5.57.36.202",
                                       socket_port=50052, dicom_port=104))
    # match by name
    assert sp.socket_port_for_server({"name": "mehr", "host": "5.57.36.202"}) == 50052
    # match by host when name differs
    assert sp.find_profile_by_host("192.168.2.222").id == "razi"
    # a center on a non-standard socket port resolves to ITS port, not the global 50052
    sp.upsert_profile(sp.ServerProfile(id="clinicx", display_name="ClinicX", host="10.1.1.9",
                                       socket_port=60055, dicom_port=104))
    assert sp.socket_port_for_server({"name": "ClinicX"}) == 60055
    # unknown server falls back to the standard default
    assert sp.socket_port_for_server({"name": "nope", "host": "1.2.3.4"}) == sp.DEFAULT_SOCKET_PORT
    assert sp.socket_port_for_server(None) == sp.DEFAULT_SOCKET_PORT


def test_clinical_data_root_off_is_identical(tmp_path):
    base = tmp_path / "user_data"
    # feature OFF → byte-identical legacy root (no servers/<id> insertion)
    assert sp.clinical_data_root(base, enabled=False) == base
    assert sp.clinical_data_root(base, enabled=False, segment="razi") == base
    # enabled but "default" segment also stays at the legacy root
    assert sp.clinical_data_root(base, enabled=True, segment="default") == base


def test_clinical_data_root_on_namespaces_by_segment(tmp_path):
    base = tmp_path / "user_data"
    assert sp.clinical_data_root(base, enabled=True, segment="razi") == base / "servers" / "razi"
    assert sp.clinical_data_root(base, enabled=True, segment="mehr") == base / "servers" / "mehr"
    # unsafe segment is slugified
    assert sp.clinical_data_root(base, enabled=True, segment="Mehr #2") == base / "servers" / "Mehr_2"


def test_server_data_root_primary_vs_secondary(profiles_file, tmp_path):
    # razi is the primary (first/active) → keeps the legacy root; mehr is secondary
    sp.upsert_profile(sp.ServerProfile(id="razi", display_name="Razi", host="192.168.2.222"))
    sp.upsert_profile(sp.ServerProfile(id="mehr", display_name="Mehr", host="5.57.36.202"))
    assert sp.get_primary_profile_id() == "razi"
    assert sp.profile_segment("razi") == "default"          # primary → legacy root
    assert sp.profile_segment("mehr") == "mehr"

    base = tmp_path / "user_data"
    assert sp.server_data_root(base, "razi") == base                          # primary
    assert sp.server_data_root(base, "mehr") == base / "servers" / "mehr"     # secondary


def test_delete_secondary_leaves_primary_untouched(profiles_file, tmp_path):
    sp.upsert_profile(sp.ServerProfile(id="razi", display_name="Razi", host="192.168.2.222"))
    sp.upsert_profile(sp.ServerProfile(id="mehr", display_name="Mehr", host="5.57.36.202"))
    base = tmp_path / "user_data"
    (base / "patients" / "dicom").mkdir(parents=True)
    (base / "patients" / "dicom" / "p.dcm").write_text("razi", encoding="utf-8")
    (base / "database").mkdir(parents=True)
    (base / "database" / "dicom.db").write_text("razi-db", encoding="utf-8")
    mehr = base / "servers" / "mehr"
    (mehr / "patients").mkdir(parents=True)
    (mehr / "patients" / "m.dcm").write_text("mehr", encoding="utf-8")

    # delete the SECONDARY → its tree is gone; the primary (legacy) data survives
    assert sp.delete_server_data(base, "mehr") is True
    assert not mehr.exists()
    assert (base / "patients" / "dicom" / "p.dcm").exists()
    assert (base / "database" / "dicom.db").exists()
    # deleting an absent secondary is a safe no-op
    sp.upsert_profile(sp.ServerProfile(id="ghost", display_name="Ghost", host="9.9.9.9"))
    assert sp.delete_server_data(base, "ghost") is True


def test_delete_primary_removes_only_clinical_subdirs(profiles_file, tmp_path):
    sp.upsert_profile(sp.ServerProfile(id="razi", display_name="Razi", host="192.168.2.222"))
    base = tmp_path / "user_data"
    (base / "patients").mkdir(parents=True)
    (base / "patients" / "p.dcm").write_text("x", encoding="utf-8")
    (base / "database").mkdir(parents=True)
    (base / "database" / "dicom.db").write_text("db", encoding="utf-8")
    (base / "logs").mkdir(parents=True)                 # shared → must survive
    (base / "logs" / "app.log").write_text("log", encoding="utf-8")

    assert sp.delete_server_data(base, "razi") is True
    assert not (base / "patients").exists()
    assert not (base / "database").exists()
    assert (base / "logs" / "app.log").exists()         # shared data preserved


def test_feature_enable_via_config(profiles_file, monkeypatch):
    sp.upsert_profile(sp.ServerProfile(
        id="razi", display_name="Razi", host="192.168.2.222",
        modules={"reception_api": "http://81.16.117.196:8080", "ai_breast": "192.168.2.222:8002"}))
    sp.set_active_profile_id("razi")

    # default OFF (env unset, config enabled=false) → endpoints fall back to global
    assert sp.server_profiles_enabled() is False
    assert sp.active_module_endpoint("reception_api") is None

    # enable via CONFIG (no env var needed)
    sp.set_feature_enabled(True)
    assert sp.is_feature_enabled_in_config() is True
    assert sp.server_profiles_enabled() is True
    assert sp.active_module_endpoint("reception_api") == "http://81.16.117.196:8080"
    assert sp.active_module_endpoint("ai_breast") == "192.168.2.222:8002"
    assert sp.active_module_endpoint("bonj") is None        # unset slot

    # the env var remains an override / kill-switch even when config says enabled
    monkeypatch.setenv(sp._ENV_FLAG, "0")
    assert sp.server_profiles_enabled() is False


def test_module_endpoints_follow_active_profile(profiles_file, monkeypatch):
    sp.upsert_profile(sp.ServerProfile(id="razi", display_name="Razi", host="192.168.2.222",
                                       modules={"reception_api": "http://10.0.0.1:8080"}))
    sp.upsert_profile(sp.ServerProfile(id="mehr", display_name="Mehr", host="5.57.36.202",
                                       modules={"reception_api": "http://5.57.36.202:8080"}))
    monkeypatch.setenv(sp._ENV_FLAG, "1")
    sp.set_active_profile_id("razi")
    assert sp.active_module_endpoint("reception_api") == "http://10.0.0.1:8080"
    # switching the active profile switches the resolved endpoint
    sp.set_active_profile_id("mehr")
    assert sp.active_module_endpoint("reception_api") == "http://5.57.36.202:8080"


def test_hand_edited_without_id_still_loads(profiles_file):
    profiles_file.write_text(json.dumps({
        "active_profile_id": "",
        "profiles": [{"name": "Clinic A", "host": "10.0.0.5", "port": 104}],
    }), encoding="utf-8")
    profs = sp.list_profiles()
    assert len(profs) == 1
    assert profs[0].id == "Clinic_A"        # slug derived from name
    assert sp.get_active_profile().host == "10.0.0.5"   # active backfilled
