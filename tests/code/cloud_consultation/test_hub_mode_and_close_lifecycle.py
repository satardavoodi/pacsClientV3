"""Guards for hub-account mode + the close/respond lifecycle additions (2026-06-10).

Covers:
* ``hub_mode_enabled`` / ``consultation_address`` resolution (env → file → default);
* hub-tolerant share: a Drive share failure is non-fatal ONLY in hub mode;
* ``share_permission_id`` persistence and ``revoke_consultation_access``
  (best-effort: success revokes + clears + audits; failure never raises);
* ``stage_response_attachments`` copies INTO the package (re-seal covers them).
"""

import contextlib
import sqlite3

import pytest

from database import consultation_db
from modules.cloud_consultation import feature_flags
from modules.cloud_consultation.consultation import workflow
from modules.cloud_consultation.consultation.assignment import assign
from modules.cloud_consultation.consultation.service import stage_response_attachments

from ._fakes import FakeTransport


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    db_file = tmp_path / "consult.db"

    @contextlib.contextmanager
    def _conn():
        con = sqlite3.connect(db_file)
        try:
            yield con
        finally:
            con.close()

    monkeypatch.setattr(consultation_db, "_db_conn", _conn)
    monkeypatch.setattr(consultation_db, "_schema_ready", False)
    return db_file


# ── feature flags ──────────────────────────────────────────────────────────────
def test_hub_mode_env_resolution(monkeypatch):
    monkeypatch.setenv("AIPACS_CONSULTATION_HUB_MODE", "1")
    assert feature_flags.hub_mode_enabled() is True
    monkeypatch.setenv("AIPACS_CONSULTATION_HUB_MODE", "0")
    assert feature_flags.hub_mode_enabled() is False


def test_hub_mode_file_resolution(monkeypatch, tmp_path):
    monkeypatch.delenv("AIPACS_CONSULTATION_HUB_MODE", raising=False)
    flag = tmp_path / "cloud_consultation.json"
    flag.write_text('{"enabled": true, "hub_mode": true, "consultation_address": "Dr.B@clinic.ir"}',
                    encoding="utf-8")
    monkeypatch.setattr(feature_flags, "_flag_file_path", lambda: flag)
    assert feature_flags.hub_mode_enabled() is True
    # Address is normalized to lowercase; file beats the default.
    assert feature_flags.consultation_address(default="hub@gmail.com") == "dr.b@clinic.ir"


def test_consultation_address_fallbacks(monkeypatch, tmp_path):
    monkeypatch.delenv("AIPACS_CONSULTATION_ADDRESS", raising=False)
    flag = tmp_path / "missing.json"
    monkeypatch.setattr(feature_flags, "_flag_file_path", lambda: flag)
    # No env, no file → the caller's default (the Google handle) wins.
    assert feature_flags.consultation_address(default="Hub@Gmail.com") == "hub@gmail.com"
    monkeypatch.setenv("AIPACS_CONSULTATION_ADDRESS", "dr.a@clinic.ir")
    assert feature_flags.consultation_address(default="hub@gmail.com") == "dr.a@clinic.ir"


# ── hub-tolerant share + permission persistence ───────────────────────────────
def _seed_uploaded(cid="c-1"):
    consultation_db.upsert_consultation(
        cid, direction="outgoing", status="uploaded", remote_folder_id="f1",
        case_title="T",
    )
    return cid


def test_share_failure_fatal_in_personal_mode(temp_db, monkeypatch):
    monkeypatch.setenv("AIPACS_CONSULTATION_HUB_MODE", "0")
    t = FakeTransport()
    t.fail_share = True
    cid = _seed_uploaded()
    with pytest.raises(RuntimeError, match="share failure"):
        assign(t, cid, "b@x.com", remote_folder_id="f1")


def test_share_failure_tolerated_in_hub_mode(temp_db, monkeypatch):
    monkeypatch.setenv("AIPACS_CONSULTATION_HUB_MODE", "1")
    t = FakeTransport()
    t.fail_share = True
    cid = _seed_uploaded()
    share = assign(t, cid, "dr.b@clinic.ir", remote_folder_id="f1")
    assert share is None
    row = consultation_db.get_consultation(cid)
    assert row["assignee_email"] == "dr.b@clinic.ir"
    events = [e["event_type"] for e in consultation_db.list_events(cid)]
    assert "share_failed" in events and "assigned" in events


def test_share_permission_id_persisted(temp_db, monkeypatch):
    monkeypatch.setenv("AIPACS_CONSULTATION_HUB_MODE", "0")
    t = FakeTransport()
    cid = _seed_uploaded()
    assign(t, cid, "b@x.com", remote_folder_id="f1")
    row = consultation_db.get_consultation(cid)
    assert row["share_permission_id"] == "perm-1"


# ── revocation on close (best-effort) ─────────────────────────────────────────
def test_revoke_consultation_access_success(temp_db):
    t = FakeTransport()
    cid = _seed_uploaded()
    consultation_db.update_consultation_fields(cid, share_permission_id="perm-9")

    assert workflow.revoke_consultation_access(t, cid, actor_handle="a@x.com") is True
    assert t.revocations == [("f1", "perm-9")]
    row = consultation_db.get_consultation(cid)
    assert (row["share_permission_id"] or "") == ""
    assert "share_revoked" in [e["event_type"] for e in consultation_db.list_events(cid)]


def test_revoke_never_raises(temp_db):
    t = FakeTransport()
    t.fail_revoke = True
    cid = _seed_uploaded()
    consultation_db.update_consultation_fields(cid, share_permission_id="perm-9")

    assert workflow.revoke_consultation_access(t, cid) is False
    assert "share_revoke_failed" in [
        e["event_type"] for e in consultation_db.list_events(cid)
    ]


def test_revoke_noop_without_permission(temp_db):
    t = FakeTransport()
    cid = _seed_uploaded()
    assert workflow.revoke_consultation_access(t, cid) is False
    assert t.revocations == []


# ── response attachments ──────────────────────────────────────────────────────
def test_stage_response_attachments_copies_into_package(tmp_path):
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    f1 = tmp_path / "report.pdf"
    f1.write_bytes(b"PDF")
    f2 = tmp_path / "slice.png"
    f2.write_bytes(b"PNG")

    refs = stage_response_attachments(pkg, [str(f1), str(f2)])

    assert len(refs) == 2
    for ref in refs:
        assert ref.startswith("responses/")
        assert (pkg / ref).is_file()
    assert (pkg / refs[0]).read_bytes() == b"PDF"


def test_stage_response_attachments_disambiguates_duplicates(tmp_path):
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    a = tmp_path / "a" / "img.png"
    b = tmp_path / "b" / "img.png"
    a.parent.mkdir()
    b.parent.mkdir()
    a.write_bytes(b"A")
    b.write_bytes(b"B")

    refs = stage_response_attachments(pkg, [str(a), str(b)])
    names = sorted(r.rsplit("/", 1)[-1] for r in refs)
    assert names == ["img.png", "img_1.png"]


def test_stage_response_attachments_missing_file_raises(tmp_path):
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    with pytest.raises(FileNotFoundError):
        stage_response_attachments(pkg, [str(tmp_path / "nope.pdf")])


def test_stage_response_attachments_empty_is_noop(tmp_path):
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    assert stage_response_attachments(pkg, []) == []
    assert not (pkg / "responses").exists()


# ── ADR-0008: linked aipacs_web identity address fallback ──────────────────────
def _linked_identity(gmail="Linked.Doctor@Gmail.com", handle="backend@x.com"):
    from modules.Identity.models import ExternalIdentity

    return ExternalIdentity(
        provider="aipacs_web", subject_id="12", handle=handle,
        aipacs_user="drv", extra={"link": {"gmail_email": gmail}},
    )


def test_linked_address_beats_default(monkeypatch, tmp_path):
    from modules.Identity.providers import aipacs_web as aw

    monkeypatch.delenv("AIPACS_CONSULTATION_ADDRESS", raising=False)
    monkeypatch.setattr(feature_flags, "_flag_file_path", lambda: tmp_path / "missing.json")
    monkeypatch.setattr(
        aw, "find_aipacs_web_identity",
        lambda user: _linked_identity() if user == "drv" else None,
    )
    # Linked gmail wins over the Google-handle default; lowercased.
    assert feature_flags.consultation_address(
        default="hub@gmail.com", aipacs_user="drv"
    ) == "linked.doctor@gmail.com"
    # Without aipacs_user the pre-ADR-0008 behaviour is byte-identical.
    assert feature_flags.consultation_address(default="Hub@Gmail.com") == "hub@gmail.com"
    # Unknown user → no link → default.
    assert feature_flags.consultation_address(
        default="hub@gmail.com", aipacs_user="other"
    ) == "hub@gmail.com"


def test_linked_address_env_and_file_still_win(monkeypatch, tmp_path):
    from modules.Identity.providers import aipacs_web as aw

    monkeypatch.setattr(
        aw, "find_aipacs_web_identity", lambda user: _linked_identity()
    )
    flag = tmp_path / "cloud_consultation.json"
    flag.write_text('{"consultation_address": "dr.file@clinic.ir"}', encoding="utf-8")
    monkeypatch.setattr(feature_flags, "_flag_file_path", lambda: flag)
    monkeypatch.delenv("AIPACS_CONSULTATION_ADDRESS", raising=False)
    assert feature_flags.consultation_address(
        default="hub@gmail.com", aipacs_user="drv"
    ) == "dr.file@clinic.ir"
    monkeypatch.setenv("AIPACS_CONSULTATION_ADDRESS", "dr.env@clinic.ir")
    assert feature_flags.consultation_address(
        default="hub@gmail.com", aipacs_user="drv"
    ) == "dr.env@clinic.ir"


def test_linked_address_falls_back_to_handle_and_never_raises(monkeypatch, tmp_path):
    from modules.Identity.providers import aipacs_web as aw

    monkeypatch.delenv("AIPACS_CONSULTATION_ADDRESS", raising=False)
    monkeypatch.setattr(feature_flags, "_flag_file_path", lambda: tmp_path / "missing.json")

    # No link snapshot in extra → the identity handle routes.
    from modules.Identity.models import ExternalIdentity

    ident = ExternalIdentity(provider="aipacs_web", subject_id="1",
                             handle="Dr.B@Clinic.ir", aipacs_user="drv")
    monkeypatch.setattr(aw, "find_aipacs_web_identity", lambda user: ident)
    assert feature_flags.linked_consultation_address("drv") == "dr.b@clinic.ir"

    # A broken lookup must never raise into the poller wiring.
    def _boom(user):
        raise RuntimeError("db down")

    monkeypatch.setattr(aw, "find_aipacs_web_identity", _boom)
    assert feature_flags.linked_consultation_address("drv") == ""
    assert feature_flags.consultation_address(
        default="hub@gmail.com", aipacs_user="drv"
    ) == "hub@gmail.com"
