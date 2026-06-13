"""Guards for the account-pill badge count + the center_id flag (workflow v2).

Qt-free: ``badge_core.count_pending_received`` is the pill badge's whole
counting contract — pending received consultations (registry inbox status in
pending/requested/accepted) plus unread HIGH/CRITICAL notifications. The Qt
rendering/worker in ``account_hook`` only composes it.
"""

from modules.cloud_consultation.ui.badge_core import (
    BADGE_PRIORITIES,
    PENDING_RECEIVED_STATUSES,
    badge_text,
    count_pending_received,
)


# ── registry inbox rows ────────────────────────────────────────────────────────
def test_pending_and_accepted_inbox_rows_count():
    rows = [
        {"status": "pending"},
        {"status": "accepted"},
        {"status": "requested"},   # older backend vocabulary, tolerated
    ]
    assert count_pending_received(rows) == 3


def test_answered_declined_closed_do_not_count():
    rows = [{"status": "answered"}, {"status": "declined"}, {"status": "closed"}]
    assert count_pending_received(rows) == 0


def test_missing_status_defaults_to_pending():
    assert count_pending_received([{}]) == 1


def test_malformed_rows_are_skipped_never_raise():
    assert count_pending_received([None, "x", 5, {"status": "pending"}]) == 1


# ── notifications ──────────────────────────────────────────────────────────────
def test_unread_high_and_critical_notifications_count():
    notifications = [
        {"status": "unread", "priority": "high"},
        {"status": "unread", "priority": "critical"},
    ]
    assert count_pending_received([], notifications) == 2


def test_read_or_low_normal_notifications_do_not_count():
    notifications = [
        {"status": "read", "priority": "critical"},   # read → no badge
        {"status": "unread", "priority": "normal"},
        {"status": "unread", "priority": "low"},
        {"status": "unread", "priority": ""},
    ]
    assert count_pending_received([], notifications) == 0


def test_combined_count_is_sum_of_both_sources():
    rows = [{"status": "pending"}, {"status": "accepted"}]
    notifications = [{"status": "unread", "priority": "high"}]
    assert count_pending_received(rows, notifications) == 3


def test_zero_for_empty_or_none_inputs():
    assert count_pending_received([]) == 0
    assert count_pending_received(None, None) == 0


def test_tier_sets_match_the_2026_06_11_tier_table():
    assert BADGE_PRIORITIES == {"high", "critical"}
    assert PENDING_RECEIVED_STATUSES == {"pending", "requested", "accepted"}


# ── badge caption ──────────────────────────────────────────────────────────────
def test_badge_text_zero_renders_nothing():
    assert badge_text(0) == ""
    assert badge_text(-3) == ""
    assert badge_text(None) == ""


def test_badge_text_caps_at_nine_plus():
    assert badge_text(1) == "1"
    assert badge_text(9) == "9"
    assert badge_text(10) == "9+"
    assert badge_text(42) == "9+"


# ── center_id flag (creation-only metadata source) ─────────────────────────────
def test_center_id_defaults_empty(monkeypatch):
    from modules.cloud_consultation import feature_flags as ff

    monkeypatch.delenv("AIPACS_CONSULTATION_CENTER_ID", raising=False)
    monkeypatch.setattr(ff, "_flag_payload", lambda: {})
    assert ff.center_id() == ""
    assert ff.center_id(default="C0") == "C0"


def test_center_id_reads_flag_file(monkeypatch):
    from modules.cloud_consultation import feature_flags as ff

    monkeypatch.delenv("AIPACS_CONSULTATION_CENTER_ID", raising=False)
    monkeypatch.setattr(ff, "_flag_payload", lambda: {"center_id": " C42 "})
    assert ff.center_id() == "C42"


def test_center_id_env_wins(monkeypatch):
    from modules.cloud_consultation import feature_flags as ff

    monkeypatch.setenv("AIPACS_CONSULTATION_CENTER_ID", "ENV-9")
    monkeypatch.setattr(ff, "_flag_payload", lambda: {"center_id": "C42"})
    assert ff.center_id() == "ENV-9"


def test_center_id_never_raises(monkeypatch):
    from modules.cloud_consultation import feature_flags as ff

    monkeypatch.delenv("AIPACS_CONSULTATION_CENTER_ID", raising=False)

    def _boom():
        raise RuntimeError("config unreadable")

    monkeypatch.setattr(ff, "_flag_payload", _boom)
    assert ff.center_id() == ""
