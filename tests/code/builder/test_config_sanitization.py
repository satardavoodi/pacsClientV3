"""Guard: the production build must never package the developer centre's config.

Root cause it guards (2026-07-09): AIPacs.spec bundled the repo's ``config/``
verbatim (``('config','config')``) and ``aipacs_runtime.seed_user_config_defaults()``
copies the BUNDLED templates into every client's roaming config on first run — so
the dev centre's PACS host IPs, AE titles, reception API URL, EchoMind ``api_key``
and Google OAuth ``client_secret`` were shipped to and seeded into every client.

The build now packages a SANITIZED copy (builder/config_sanitizer.py). These tests
pin that (a) the sanitized tree is clean, (b) the developer's config/ is never
modified, and (c) the spec + release gate are wired to the sanitizer.
"""
import json
import os
import shutil
import sys
import tempfile

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from builder.config_sanitizer import (  # noqa: E402
    SANITIZE, KEEP_AS_IS, build_clean_config_tree, sanitize_obj, sanitize_bytes,
    scan_for_center_values,
)

_CONFIG = os.path.join(_ROOT, "config")


def _hashes(root):
    out = {}
    for base, _dirs, files in os.walk(root):
        for f in files:
            p = os.path.join(base, f)
            with open(p, "rb") as fh:
                out[os.path.relpath(p, root)] = hash(fh.read())
    return out


def test_sanitized_tree_of_real_config_has_no_center_values():
    """THE test: whatever the developer currently has saved, the tree that gets
    packaged must contain no IP, API key, OAuth secret or password."""
    tmp = tempfile.mkdtemp(prefix="cfgclean_")
    try:
        build_clean_config_tree(_CONFIG, tmp)
        leaks = scan_for_center_values(tmp)
        assert leaks == [], f"centre-specific values would ship: {leaks}"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_sanitizer_never_modifies_the_developer_config():
    """The dev machine's settings must survive untouched (explicit requirement)."""
    before = _hashes(_CONFIG)
    tmp = tempfile.mkdtemp(prefix="cfgclean_")
    try:
        build_clean_config_tree(_CONFIG, tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    assert _hashes(_CONFIG) == before, "sanitizer must only READ config/"


def test_known_secret_fields_are_blanked():
    m = sanitize_obj("echomind_settings.json", {"api_key": "REAL", "llm_backend": "company"})
    assert m["api_key"] == ""
    assert m["llm_backend"] == "company"  # product default preserved

    g = sanitize_obj("identity/google_oauth.json",
                     {"installed": {"client_id": "X", "client_secret": "S",
                                    "project_id": "P", "token_uri": "https://t"}})
    assert g["installed"]["client_secret"] == ""
    assert g["installed"]["client_id"] == ""
    assert g["installed"]["token_uri"] == "https://t"  # generic endpoint kept


def test_server_lists_are_emptied():
    assert sanitize_obj("servers.json", [{"host": "10.0.0.1", "ae_title": "X"}]) == []
    sp = sanitize_obj("server_profiles.json",
                      {"profiles": [{"host": "10.0.0.1"}], "active_profile_id": "a",
                       "enabled": True})
    assert sp["profiles"] == []
    assert sp["active_profile_id"] == ""
    assert sp["enabled"] is True  # feature flag preserved


def test_socket_and_reception_hosts_blanked_ports_kept():
    s = sanitize_obj("socket_config.json", {"socket_host": "1.2.3.4", "socket_port": 50052})
    assert s["socket_host"] == "" and s["socket_port"] == 50052
    r = sanitize_obj("reception_api_config.json",
                     {"reception_api_base_url": "http://1.2.3.4:8080",
                      "reception_api_host": "1.2.3.4", "reception_api_port": 8080})
    assert r["reception_api_base_url"] == "" and r["reception_api_host"] == ""
    assert r["reception_api_port"] == 8080


def test_files_needed_for_install_are_left_alone():
    for rel in KEEP_AS_IS:
        assert rel not in SANITIZE, f"{rel} must not be sanitized (breaks install)"


def test_dev_leftovers_and_secrets_are_excluded_from_the_package():
    tmp = tempfile.mkdtemp(prefix="cfgclean_")
    try:
        build_clean_config_tree(_CONFIG, tmp)
        staged = {
            os.path.relpath(os.path.join(b, f), tmp).replace("\\", "/")
            for b, _d, fs in os.walk(tmp) for f in fs
        }
        assert not [p for p in staged if ".bak" in p], "backup files must not ship"
        assert not [p for p in staged if p.endswith(".gitignore")]
        assert not [p for p in staged if "secrets/" in p], "secrets must never ship"
        assert not [p for p in staged if p.endswith(".local.json")], "dev overrides must not ship"
        # OPT-21: machine-generated state, not a template. A persisted PASS is
        # trusted with ZERO probing, so shipping the dev box's result would make a
        # client with a weak OpenGL driver SKIP its own pre-flight and walk into
        # the native MPR crash the probe exists to prevent.
        assert "hardware_check.json" not in staged, (
            "hardware_check.json is per-INSTALL machine state and must never ship"
        )
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_production_build_ships_an_EMPTY_server_configuration():
    """Every client centre must configure its own servers after installation —
    the build carries no server list, no host, no AI/reception endpoint."""
    tmp = tempfile.mkdtemp(prefix="cfgsrv_")
    try:
        build_clean_config_tree(_CONFIG, tmp)

        def _load(rel):
            p = os.path.join(tmp, rel)
            return json.loads(open(p, encoding="utf-8").read()) if os.path.exists(p) else None

        assert _load("servers.json") == [], "the DICOM server list must ship empty"

        profiles = _load("server_profiles.json") or {}
        assert profiles.get("profiles") == [], "no server profile may ship"
        assert not profiles.get("active_profile_id")
        assert not profiles.get("primary_profile_id")

        assert not (_load("socket_config.json") or {}).get("socket_host")
        assert not any((_load("servers_address.json") or {}).get("services", {}).values())

        reception = _load("reception_api_config.json") or {}
        assert not reception.get("reception_api_base_url")
        assert not reception.get("reception_api_host")

        assert (_load("external_pacs_servers.json") or {}).get("servers") == []
        assert (_load("offline_cloud_servers.json") or {}).get("servers") == []
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_sanitize_bytes_is_idempotent_and_shared_with_the_gate():
    raw = json.dumps({"socket_host": "1.2.3.4", "socket_port": 50052}).encode()
    once = sanitize_bytes("socket_config.json", raw)
    twice = sanitize_bytes("socket_config.json", once)
    assert once == twice, "gate and build must agree on the expected bytes"
    assert b'"socket_host": ""' in once


def test_spec_packages_the_sanitized_tree_not_raw_config():
    spec = open(os.path.join(_ROOT, "AIPacs.spec"), encoding="utf-8", errors="replace").read()
    assert "config_sanitizer" in spec
    assert "config_clean" in spec
    # the raw passthrough must be gone
    assert "('config', 'config')" not in spec


def test_release_gate_expects_sanitized_and_scans_for_leaks():
    gate = open(os.path.join(_ROOT, "builder", "release_gate.py"),
                encoding="utf-8", errors="replace").read()
    assert "sanitize_bytes" in gate
    assert "scan_for_center_values" in gate


def test_production_pyinstaller_spec_packages_sanitized_tree():
    """build_release.py builds from builder/spec/appA_workstation.spec, whose datas
    come from spec_utils.common_app_datas() — this is THE production path (the root
    AIPacs.spec is not what build_release uses)."""
    su = os.path.join(_ROOT, "builder", "spec", "spec_utils.py")
    src = open(su, encoding="utf-8", errors="replace").read()
    assert "sanitized_config_rel" in src, "production spec must sanitize config"
    assert "config_sanitizer" in src
    # the raw curated entry must be gone from BOTH app A and app B data lists
    assert '\n        "config",' not in src, "raw config/ still packaged by spec_utils"


def test_nuitka_spec_also_packages_the_sanitized_tree():
    """BOTH builders must be safe (ARM64/x64 dual-build directive) — the Nuitka
    spec packaged raw config/ too."""
    spec = os.path.join(_ROOT, "builder nuitka", "AIPacs_nuitka.spec.py")
    if not os.path.exists(spec):
        return
    src = open(spec, encoding="utf-8", errors="replace").read()
    assert "config_sanitizer" in src, "Nuitka build must sanitize config"
    assert "config_clean" in src
    assert '("config", "config"),' not in src, "Nuitka still packages raw config/"
