"""Unit tests for the Qt-free ADR-0007 section logic (dashboard_core).

Covers the My Consultations bucket grouping (Drive + registry merge with the
dedupe preserved), the Consultant Directory filtering, and the storage summary
helpers used by the Storage section + account-popup line. Headless — no Qt.
"""

from modules.education.online_consultation import assign_core, dashboard_core
from modules.education.online_consultation.dashboard_core import (
    BUCKET_ANSWERED,
    BUCKET_AWAITING_RESPONSE,
    BUCKET_AWAITING_REVIEW,
    BUCKET_CLOSED,
    BUCKET_ORDER,
    BUCKET_PENDING,
    STORAGE_CACHE_TTL_SEC,
    bucket_for_drive,
    bucket_for_registry,
    consultant_specialties,
    drive_row_actionable,
    filter_consultants,
    format_bytes,
    group_consultations,
    storage_cache_fresh,
    storage_summary,
)


# ── bucket mapping ──────────────────────────────────────────────────────────────
def test_drive_buckets_outgoing():
    assert bucket_for_drive("pending", "outgoing") == BUCKET_PENDING
    for s in ("uploaded", "downloaded", "reviewed", "conflict"):
        assert bucket_for_drive(s, "outgoing") == BUCKET_AWAITING_RESPONSE
    assert bucket_for_drive("answered", "outgoing") == BUCKET_ANSWERED
    assert bucket_for_drive("closed", "outgoing") == BUCKET_CLOSED


def test_drive_buckets_incoming():
    assert bucket_for_drive("pending", "incoming") == BUCKET_PENDING
    for s in ("uploaded", "downloaded", "reviewed", "conflict"):
        assert bucket_for_drive(s, "incoming") == BUCKET_AWAITING_REVIEW
    assert bucket_for_drive("answered", "incoming") == BUCKET_ANSWERED
    assert bucket_for_drive("closed", "incoming") == BUCKET_CLOSED


def test_drive_bucket_unknown_status_falls_to_pending():
    assert bucket_for_drive("weird", "outgoing") == BUCKET_PENDING
    assert bucket_for_drive(None, "incoming") == BUCKET_PENDING


def test_registry_buckets():
    assert bucket_for_registry("pending", "sent") == BUCKET_AWAITING_RESPONSE
    assert bucket_for_registry("accepted", "sent") == BUCKET_AWAITING_RESPONSE
    assert bucket_for_registry("answered", "sent") == BUCKET_ANSWERED
    assert bucket_for_registry("declined", "sent") == BUCKET_CLOSED
    assert bucket_for_registry("closed", "sent") == BUCKET_CLOSED
    assert bucket_for_registry("pending", "inbox") == BUCKET_PENDING
    assert bucket_for_registry("accepted", "inbox") == BUCKET_AWAITING_REVIEW
    assert bucket_for_registry("answered", "inbox") == BUCKET_ANSWERED


def test_drive_row_actionable():
    assert drive_row_actionable(
        {"status": "uploaded", "remote_folder_id": "r1"}, "incoming") is True
    assert drive_row_actionable({"status": "uploaded"}, "incoming") is False
    assert drive_row_actionable(
        {"status": "downloaded", "local_path": "/x"}, "incoming") is True
    assert drive_row_actionable({"status": "reviewed"}, "incoming") is False
    assert drive_row_actionable({"status": "answered"}, "outgoing") is True
    assert drive_row_actionable({"status": "uploaded"}, "outgoing") is False


# ── grouping (Drive + registry merge) ───────────────────────────────────────────
def _mixed_rows():
    drive_in = [
        {"consultation_id": "c-in-1", "status": "uploaded",
         "remote_folder_id": "fold-in-1", "case_title": "Knee MRI"},
        {"consultation_id": "c-in-2", "status": "answered"},
    ]
    drive_out = [
        {"consultation_id": "c-out-1", "status": "uploaded",
         "remote_folder_id": "fold-out-1"},
        {"consultation_id": "c-out-2", "status": "closed"},
    ]
    registry_inbox = [
        {"id": 1, "type": "internal", "status": "pending", "patient_ref": "44113 DOE"},
    ]
    registry_sent = [
        # external twin of drive c-out-1 → must be deduped away
        {"id": 2, "type": "external", "status": "pending",
         "drive_folder_id": "fold-out-1"},
        {"id": 3, "type": "internal", "status": "answered", "patient_ref": "44504 X"},
    ]
    return drive_in, drive_out, registry_inbox, registry_sent


def test_group_consultations_buckets_and_dedup():
    buckets = group_consultations(*_mixed_rows())
    assert set(buckets) == set(BUCKET_ORDER)
    flat = [r for rows in buckets.values() for r in rows]
    # 4 drive rows + 2 registry rows survive (the external twin is deduped).
    assert len(flat) == 6
    assert all(not (r.get("_source") == "registry" and r.get("id") == 2)
               for r in flat)

    review = buckets[BUCKET_AWAITING_REVIEW]
    assert [r["consultation_id"] for r in review if r["_source"] == "drive"] == ["c-in-1"]
    assert buckets[BUCKET_PENDING][0]["id"] == 1  # registry inbox pending
    answered_ids = {r.get("consultation_id") or r.get("id")
                    for r in buckets[BUCKET_ANSWERED]}
    assert answered_ids == {"c-in-2", 3}
    assert [r["consultation_id"] for r in buckets[BUCKET_CLOSED]] == ["c-out-2"]
    assert [r["consultation_id"] for r in buckets[BUCKET_AWAITING_RESPONSE]] == ["c-out-1"]


def test_group_consultations_annotations():
    buckets = group_consultations(*_mixed_rows())
    for bucket, rows in buckets.items():
        for r in rows:
            assert r["_bucket"] == bucket
            assert r["_source"] in ("drive", "registry")
            assert r["_direction"] in ("incoming", "outgoing")
    # actionable flags: incoming uploaded drive row + registry rows with actions
    review = buckets[BUCKET_AWAITING_REVIEW]
    assert any(r["_actionable"] for r in review if r["_source"] == "drive")
    pending = buckets[BUCKET_PENDING]
    assert pending[0]["_actionable"] is True  # inbox pending → accept/decline
    closed = buckets[BUCKET_CLOSED]
    assert all(not r["_actionable"] for r in closed)


def test_group_consultations_never_mutates_inputs():
    drive_in, drive_out, reg_in, reg_sent = _mixed_rows()
    snapshot = [dict(r) for r in drive_in]
    group_consultations(drive_in, drive_out, reg_in, reg_sent)
    assert drive_in == snapshot  # Drive rows untouched (additive merge)


def test_group_consultations_empty_inputs():
    buckets = group_consultations([], [], [], [])
    assert all(rows == [] for rows in buckets.values())


# ── consultant directory filtering ──────────────────────────────────────────────
_ROSTER = [
    {"name": "Dr Ada", "specialty": "Neuroradiology", "expertise": "MRI brain",
     "type": "internal", "availability": "available"},
    {"name": "Dr Bob", "specialty": "MSK", "expertise": "Knee MRI",
     "type": "external", "availability": "busy"},
    {"name": "Dr Cyn", "specialty": "Chest", "expertise": "HRCT",
     "type": "internal", "availability": "away"},
]


def test_filter_consultants_query_matches_name_specialty_expertise():
    assert [c["name"] for c in filter_consultants(_ROSTER, query="ada")] == ["Dr Ada"]
    assert [c["name"] for c in filter_consultants(_ROSTER, query="msk")] == ["Dr Bob"]
    assert [c["name"] for c in filter_consultants(_ROSTER, query="hrct")] == ["Dr Cyn"]
    assert [c["name"] for c in filter_consultants(_ROSTER, query="MRI")] == [
        "Dr Ada", "Dr Bob"]


def test_filter_consultants_kind_and_availability():
    assert [c["name"] for c in filter_consultants(_ROSTER, kind="external")] == ["Dr Bob"]
    assert [c["name"] for c in filter_consultants(_ROSTER, kind="internal")] == [
        "Dr Ada", "Dr Cyn"]
    assert [c["name"] for c in filter_consultants(_ROSTER, availability="busy")] == ["Dr Bob"]
    assert [c["name"] for c in filter_consultants(
        _ROSTER, kind="internal", availability="away")] == ["Dr Cyn"]


def test_filter_consultants_all_and_empty():
    assert filter_consultants(_ROSTER) == _ROSTER
    assert filter_consultants(_ROSTER, query="zzz") == []
    assert filter_consultants([], query="a") == []


def test_filter_consultants_specialty_exact_case_insensitive():
    assert [c["name"] for c in filter_consultants(
        _ROSTER, specialty="neuroradiology")] == ["Dr Ada"]
    assert [c["name"] for c in filter_consultants(_ROSTER, specialty="MSK")] == ["Dr Bob"]
    assert filter_consultants(_ROSTER, specialty="Cardiac") == []
    assert filter_consultants(_ROSTER, specialty="all") == _ROSTER
    # combined with kind: internal + Chest → only Dr Cyn
    assert [c["name"] for c in filter_consultants(
        _ROSTER, kind="internal", specialty="chest")] == ["Dr Cyn"]


def test_consultant_specialties_distinct_sorted_tolerant():
    rows = _ROSTER + [
        {"name": "Dr Dup", "specialty": "msk"},          # case-dup of MSK
        {"name": "Dr Legacy", "speciality": "Cardiac"},  # legacy spelling
        {"name": "Dr None"},                             # no specialty
    ]
    specs = consultant_specialties(rows)
    assert [s.lower() for s in specs] == ["cardiac", "chest", "msk",
                                          "neuroradiology"]
    assert consultant_specialties([]) == []


def test_filter_consultants_unknown_kind_defaults_internal():
    roster = [{"name": "Dr D"}]  # no type → assign_core defaults to internal
    assert assign_core.consultant_kind(roster[0]) == assign_core.INTERNAL
    assert filter_consultants(roster, kind="internal") == roster
    assert filter_consultants(roster, kind="external") == []


# ── storage helpers ─────────────────────────────────────────────────────────────
def test_storage_summary_warn_threshold():
    s = storage_summary({"quota_bytes": 100, "used_bytes": 85})
    assert s["warn"] is True and abs(s["fraction"] - 0.85) < 1e-9
    s = storage_summary({"quota_bytes": 100, "used_bytes": 79})
    assert s["warn"] is False


def test_storage_summary_tolerates_key_variants_and_strings():
    s = storage_summary({"quota": "200", "used": 50})
    assert s["quota"] == 200 and s["used"] == 50 and s["fraction"] == 0.25


def test_storage_summary_missing_quota_never_warns():
    s = storage_summary({"used_bytes": 999})
    assert s["fraction"] is None and s["warn"] is False
    assert storage_summary(None)["warn"] is False
    assert storage_summary({})["fraction"] is None


def test_storage_summary_alert_threshold():
    s = storage_summary({"quota_bytes": 100, "used_bytes": 95})
    assert s["warn"] is True and s["alert"] is True
    s = storage_summary({"quota_bytes": 100, "used_bytes": 90})
    assert s["warn"] is True and s["alert"] is False
    s = storage_summary({"quota_bytes": 100, "used_bytes": 10})
    assert s["warn"] is False and s["alert"] is False
    # no quota → alert can never trip (fails open, ADR-0005)
    assert storage_summary({"used_bytes": 999})["alert"] is False


def test_storage_cache_fresh_ttl():
    assert storage_cache_fresh(None) is False
    assert storage_cache_fresh(1000.0, now_monotonic=1000.0 + 60.0) is True
    assert storage_cache_fresh(
        1000.0, now_monotonic=1000.0 + STORAGE_CACHE_TTL_SEC) is False
    assert storage_cache_fresh(
        1000.0, now_monotonic=1000.0 + STORAGE_CACHE_TTL_SEC - 0.1) is True
    assert storage_cache_fresh(1000.0, now_monotonic=1030.0, ttl=10.0) is False
    assert storage_cache_fresh("junk", now_monotonic=1.0) is False


def test_format_bytes():
    assert format_bytes(0) == "0 B"
    assert format_bytes(1536) == "1.5 KB"
    assert format_bytes(5 * 1024 * 1024) == "5.0 MB"
    assert format_bytes(None) == "—"
    assert format_bytes("junk") == "—"
