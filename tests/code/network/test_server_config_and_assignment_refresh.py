"""Server config comes from Server Settings; assignment comes from the SERVER.

Guards for the 2026-07-14 work (patient 50210):

1. **No hard-coded center address in source.** ``reception_api_config`` used to
   carry ``_DEFAULT_HOST = "81.16.117.196"`` — the DEVELOPER center's IP — as its
   fallback. The build sanitizer only cleans ``config/``, never source, so it
   shipped to every customer: a center that had not configured reception quietly
   queried OUR server. Every address now resolves from the ACTIVE SERVER PROFILE.

2. **The assign REST base follows the PACS host, not the reception host.**

3. **Assignment state is read from the server** and merged with the local
   lifecycle log, so an assignment made on ANOTHER workstation is visible here.

Pure/offline — no Qt, no network.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from modules.network import ino_assignment_models as m
from modules.network import ino_assignment_refresh as refresh

REPO = Path(__file__).resolve().parents[3]


# ── 1. no hard-coded center address in source ────────────────────────────────
def test_reception_config_has_no_hardcoded_center_host():
    import modules.network.reception_api_config as rc

    assert rc._DEFAULT_HOST == "", "a center IP must never be baked into source"
    assert rc._DEFAULT_BASE_URL == ""


def test_reception_source_file_contains_no_center_ip():
    src = (REPO / "modules" / "network" / "reception_api_config.py").read_text(
        encoding="utf-8", errors="replace")
    # Strip comments/docstrings that legitimately explain the history.
    code = "\n".join(
        ln for ln in src.splitlines()
        if not ln.lstrip().startswith("#")
    )
    for ip in re.findall(r"\b\d{1,3}(?:\.\d{1,3}){3}\b", code):
        assert ip in ("0.0.0.0", "127.0.0.1"), f"hard-coded address {ip} in source"


def test_unconfigured_reception_resolves_to_empty_not_our_center(monkeypatch):
    """A center with nothing configured must get "", never the developer's server."""
    import modules.network.reception_api_config as rc

    monkeypatch.delenv("AIPACS_RECEPTION_BASE_URL", raising=False)
    monkeypatch.delenv("RECEPTION_API_BASE_URL", raising=False)
    monkeypatch.setattr(rc, "get_reception_api_config",
                        lambda: type("C", (), {"get_base_url": lambda s: "",
                                               "get_port": lambda s: 8080})())
    import PacsClient.utils.server_profiles as sp
    monkeypatch.setattr(sp, "active_module_endpoint", lambda name: None)
    monkeypatch.setattr(sp, "active_reception_base", lambda port=8080: "")

    assert rc.get_reception_api_base_url() == ""


def test_reception_derives_from_the_active_profile_host(monkeypatch):
    """A center whose profile has no explicit reception slot still gets ITS OWN
    server (profile host + port) — never the developer's."""
    import modules.network.reception_api_config as rc
    import PacsClient.utils.server_profiles as sp

    monkeypatch.delenv("AIPACS_RECEPTION_BASE_URL", raising=False)
    monkeypatch.delenv("RECEPTION_API_BASE_URL", raising=False)
    monkeypatch.setattr(sp, "active_module_endpoint", lambda name: None)
    monkeypatch.setattr(rc, "get_reception_api_config",
                        lambda: type("C", (), {"get_base_url": lambda s: "",
                                               "get_port": lambda s: 8080})())
    # A profile with NO reception_api slot configured.
    prof = sp.ServerProfile.from_dict({"id": "new", "host": "10.20.30.40"})
    monkeypatch.setattr(sp, "get_active_profile", lambda: prof)
    monkeypatch.setattr(sp, "active_host", lambda: "10.20.30.40")

    assert rc.get_reception_api_base_url() == "http://10.20.30.40:8080"


def test_explicit_profile_reception_slot_wins_over_host_derivation(monkeypatch):
    import PacsClient.utils.server_profiles as sp

    prof = sp.ServerProfile.from_dict(
        {"id": "razi", "host": "192.168.2.222",
         "modules": {"reception_api": "http://81.16.117.196:8080"}})
    monkeypatch.setattr(sp, "get_active_profile", lambda: prof)
    assert sp.active_reception_base(8080) == "http://81.16.117.196:8080"


# ── 2. the assign base follows the PACS profile host ────────────────────────
def test_pacs_http_base_comes_from_the_profile_host_not_reception(monkeypatch):
    """The assign API lives on the PACS host. Deriving it from the RECEPTION host
    (the old behaviour) sends assign calls to the wrong machine at any center where
    the two differ — here the profile host is 192.168.2.222 while reception is the
    port-forwarded 81.16.117.196."""
    import PacsClient.utils.server_profiles as sp
    import modules.network.ino_assignment as ia

    monkeypatch.delenv("AIPACS_INO_ASSIGNMENT_BASE_URL", raising=False)
    monkeypatch.delenv("INO_ASSIGNMENT_BASE_URL", raising=False)
    monkeypatch.setattr(sp, "active_host", lambda: "192.168.2.222")
    monkeypatch.setattr(sp, "get_active_profile", lambda: None)
    # Reception points somewhere ELSE entirely — it must not be used.
    monkeypatch.setattr(ia, "get_reception_api_base_url",
                        lambda: "http://81.16.117.196:8080")

    assert ia._derive_pacs_http_base() == "http://192.168.2.222:8000"


def test_pacs_http_slot_is_a_profile_module_key():
    import PacsClient.utils.server_profiles as sp

    assert "pacs_http" in sp.MODULE_ENDPOINT_KEYS
    prof = sp.ServerProfile.from_dict(
        {"id": "x", "host": "1.1.1.1", "modules": {"pacs_http": "http://9.9.9.9:8000"}})
    assert prof.module_endpoint("pacs_http") == "http://9.9.9.9:8000"


# ── 3. assignment: parse + identity + merge ─────────────────────────────────
_SERVER_50210 = {
    "radiologist": {"id": "6887a95ae7e66cdc2029a960",
                    "name": "دكتر وحید علیزاده",
                    "source": "ris_personnel"},
    "typist": {"id": "", "name": "", "source": ""},
    "last_assigned_at": "2026-07-14T11:10:14.770000",
    "last_assigned_by": "69f9041818d430369ecdab06",
}


def test_parse_assignment_reads_the_real_50210_payload():
    p = refresh.parse_assignment(_SERVER_50210)
    assert p["assigned"] is True
    assert p["assign_type"] == "radiologist"
    assert p["assignee_id"] == "6887a95ae7e66cdc2029a960"
    assert p["assignee_source"] == "ris_personnel"


def test_empty_id_is_not_an_assignment():
    p = refresh.parse_assignment({"radiologist": {"id": "", "name": ""},
                                  "typist": {"id": "", "name": ""}})
    assert p["assigned"] is False and p["assignee_id"] == ""


# ── regression 2026-07-15: the RIS reporting radiologist is NOT an assignment ──
# The PACS /assign endpoint returns the auto-populated reporting radiologist for
# almost every reported reception (source=ris_personnel, last_assigned_by="").
# Treating any radiologist id as "assigned" made every reported patient show as
# internally assigned (live: 50258/50016/50107/50304). A real assign records the
# assigner (X-User-Id → last_assigned_by), so that is the discriminator.
_SERVER_50304_REPORTING = {
    "radiologist": {"id": "6011aa22bb33cc44dd55ee66",
                    "name": "دكتر رضا علیزاده",
                    "source": "ris_personnel"},
    "typist": {"id": "", "name": "", "source": ""},
    "last_assigned_at": "2026-07-15T16:23:31.536000",
    "last_assigned_by": "",   # ← auto-populated reporting radiologist, no assigner
}


def test_reporting_radiologist_without_assigner_is_not_assigned():
    p = refresh.parse_assignment(_SERVER_50304_REPORTING)
    assert p["assigned"] is False, "reporting radiologist (no assigner) must not count"
    # identity fields are still exposed (for a tooltip), only the verdict is gated
    assert p["radiologist_name"] == "دكتر رضا علیزاده"
    assert p["last_assigned_by"] == ""


def test_same_payload_becomes_assigned_once_an_assigner_is_present():
    assigned_payload = dict(_SERVER_50304_REPORTING,
                            last_assigned_by="69f9041818d430369ecdab06")
    p = refresh.parse_assignment(assigned_payload)
    assert p["assigned"] is True


def test_require_assigner_flag_off_restores_legacy_id_only(monkeypatch):
    monkeypatch.setenv("AIPACS_INO_ASSIGN_REQUIRE_ASSIGNER", "0")
    p = refresh.parse_assignment(_SERVER_50304_REPORTING)
    assert p["assigned"] is True, "flag off = legacy id-only behaviour"


def test_require_assigner_is_default_on(monkeypatch):
    monkeypatch.delenv("AIPACS_INO_ASSIGN_REQUIRE_ASSIGNER", raising=False)
    assert refresh.require_assigner() is True


def test_identity_is_matched_by_ID_not_display_name():
    ids = ["507f1f77bcf86cd799439011", "6887a95ae7e66cdc2029a960"]
    assert refresh.assignment_is_mine("6887a95ae7e66cdc2029a960", ids) is True
    assert refresh.assignment_is_mine("someone-else", ids) is False
    # A name must never be accepted as an identity.
    assert refresh.assignment_is_mine("دكتر وحید علیزاده", ids) is False
    assert refresh.assignment_is_mine("", ids) is False


# ── the merge rule: server owns "assigned?", local owns completed/deactivated ─
def test_server_assignment_from_another_pc_becomes_active():
    """THE 50210 BUG: the local log is empty (this PC never did the assign), the
    server says assigned → the row must show ACTIVE with the server's name."""
    out = m.merge_assignment_status(True, "دكتر وحید علیزاده", local_status="")
    assert out["status"] == m.STATUS_ACTIVE
    assert out["assignee_name"] == "دكتر وحید علیزاده"


def test_unknown_server_state_never_wipes_a_known_assignment():
    """None = "not fetched / call failed" — NOT "unassigned"."""
    out = m.merge_assignment_status(None, "", local_status=m.STATUS_ACTIVE,
                                    local_name="Dr X")
    assert out["status"] == m.STATUS_ACTIVE and out["assignee_name"] == "Dr X"


def test_local_completed_survives_a_server_refresh():
    """`completed` is the ONE local lifecycle state (the server's assign model has no
    status field), so a refresh must not clobber it. A local `removed`, by contrast,
    must NOT win over a server that still reports the assignment."""
    out = m.merge_assignment_status(True, "Dr S", local_status=m.STATUS_COMPLETED,
                                    local_name="Dr S")
    assert out["status"] == m.STATUS_COMPLETED

    stale = m.merge_assignment_status(True, "Dr S", local_status="cancelled")
    assert stale["status"] == m.STATUS_ACTIVE, "the server owns 'is this assigned'"


def test_server_unassign_is_reflected():
    out = m.merge_assignment_status(False, "", local_status=m.STATUS_ACTIVE,
                                    local_name="Dr X")
    assert out["status"] == m.STATUS_REMOVED


def test_never_assigned_stays_blank():
    out = m.merge_assignment_status(False, "", local_status="")
    assert out["status"] == "" and out["assignee_name"] == ""


def test_completed_locally_then_cleared_on_server_stays_completed():
    out = m.merge_assignment_status(False, "", local_status=m.STATUS_COMPLETED,
                                    local_name="Dr X")
    assert out["status"] == m.STATUS_COMPLETED


# ── a failed fetch must not be persisted as "unassigned" ────────────────────
def test_failed_fetch_returns_none_and_is_counted_as_failed(monkeypatch):
    monkeypatch.setattr(refresh, "fetch_assignment", lambda rid: None)
    out = refresh.refresh_assignments(["50210", "50211"])
    assert out["updated"] == 0 and out["failed"] == 2 and out["ok"] is False
    assert out["rows"] == {}


def test_refresh_persists_the_server_answer(monkeypatch, tmp_path):
    from modules.network import ino_assignment_server_state as state

    monkeypatch.setattr(state, "_base_dir", lambda: str(tmp_path))
    parsed = dict(refresh.parse_assignment(_SERVER_50210), mine=True,
                  reception_id="50210")
    monkeypatch.setattr(refresh, "fetch_assignment", lambda rid: dict(parsed))

    out = refresh.refresh_assignments(["50210"])
    assert out["updated"] == 1 and out["ok"] is True

    snap = state.get_state("50210")
    assert snap and snap["assigned"] is True
    assert snap["assignee_name"] == "دكتر وحید علیزاده"


def test_reception_ids_are_deduplicated(monkeypatch):
    seen = []
    monkeypatch.setattr(refresh, "fetch_assignment",
                        lambda rid: (seen.append(rid), None)[1])
    refresh.refresh_assignments(["1", "1", "2", " ", None, "2"])
    assert seen == ["1", "2"]


# ── wiring pins ─────────────────────────────────────────────────────────────
def _src(*parts) -> str:
    return (REPO.joinpath(*parts)).read_text(encoding="utf-8", errors="replace")


def test_refresh_button_also_refreshes_the_assignment():
    src = _src("PacsClient", "pacs", "workstation_ui", "home_ui", "patient_table_widget.py")
    # the body of refresh_download_statuses, up to the next method definition
    body = src.split("def refresh_download_statuses", 1)[1]
    body = body.split("\n    def ", 1)[0]
    # force=True: an explicit refresh must never serve a cached snapshot.
    assert "_start_assignment_refresh(force=True)" in body, (
        "Refresh Status must re-read the server assignment — that is the whole "
        "reason a cross-machine assignment (50210) never appeared")
    assert "reportRefreshRequested.emit()" in body     # existing behaviour kept
    assert "_download_status_cache" in body


def test_refresh_button_no_longer_fakes_success():
    src = _src("PacsClient", "pacs", "workstation_ui", "home_ui", "patient_table_widget.py")
    assert "_set_refresh_result" in src
    anim = src.split("def animate_refresh", 1)[1][:600]
    assert "#10b981" not in anim, (
        "the spinner must not end on an unconditional green tick — a refresh that "
        "silently did nothing looked identical to one that worked")


def test_columns_read_the_merged_server_state():
    src = _src("PacsClient", "pacs", "workstation_ui", "home_ui", "patient_table_widget.py")
    assert "ino_assignment_server_state" in src
    assert "merge_assignment_status" in src
    assert "def assignment_display_for" in src


def test_cache_revalidates_instead_of_returning_forever():
    src = _src("PacsClient", "pacs", "workstation_ui", "home_ui", "home_panel", "_hp_search.py")
    assert "_reporter_cache_is_fresh" in src
    assert "_mark_reporter_cached" in src
    assert "phase='revalidate'" in src
    assert "_queue_assignment_hydration" in src
