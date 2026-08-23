"""The sync engine, one test per rule.

This is the highest-value file in the module. Every rule the engine enforces
exists because of a failure that is silent when it happens and expensive to
find afterwards — a message that is never delivered, a read receipt that
un-reads itself, a banner that fires for the same event forever. None of them
are visible in a screenshot, so they are pinned here instead.

The engine takes the clock as a parameter, so nothing below sleeps.
"""

from modules.aipacs_chat.services.models import Filters
from modules.aipacs_chat.services.sync_engine import SyncEngine


def _envelope(**overrides):
    """A minimal well-formed sync answer."""
    payload = {
        "t": 1787170000,
        "cursor": {"m": 0, "rev": 1787170000, "ev": 0, "req": 1},
        "cold": False,
        "thread": None,
        "counts": {"unread": 0, "online": 0, "stalled": 0, "none": 0},
        "events": [],
        "rows": [],
    }
    payload.update(overrides)
    return payload


def _message(mid, body="hello", **overrides):
    msg = {
        "id": mid,
        "sender_type": "patient",
        "sender": None,
        "type": "text",
        "body": body,
        "meta": None,
        "ai_action": None,
        "edited": False,
        "removed": False,
        "editable": False,
        "reactions": {"patient": None, "staff_up": 0, "staff_down": 0},
        "my_reaction": None,
        "is_automated": False,
        "at": "2026-08-19T14:19:58+00:00",
    }
    msg.update(overrides)
    return msg


def _thread(case, messages=(), revised=(), **overrides):
    thread = {
        "case": case,
        "m": max([m["id"] for m in messages], default=0),
        "messages": list(messages),
        "revised": list(revised),
        "patient_online": True,
        "patient_typing": False,
        "read_at": None,
        "seen_at": None,
        "status": "new",
        "status_tone": "fresh",
    }
    thread.update(overrides)
    return thread


# --- the request ------------------------------------------------------------


def test_visible_is_always_sent_because_the_server_defaults_it_to_true():
    """Omitting it claims the operator read a screen nobody looked at.

    staff_last_read_at is written from this flag, and that timestamp is the
    patient's second tick.
    """
    engine = SyncEngine(now_ms=0)
    engine.set_visible(False, now_ms=1000)

    params = dict(engine.next_request(now_ms=1000))

    assert params["visible"] == "0"


def test_the_request_counter_increments_so_answers_can_be_ordered():
    engine = SyncEngine(now_ms=0)

    first = dict(engine.next_request(now_ms=0))["req"]
    second = dict(engine.next_request(now_ms=0))["req"]

    assert int(second) == int(first) + 1


def test_filters_ride_the_same_request_with_bracketed_multi_values():
    """attn[] and source[] are arrays; show and presence are not.

    Two entries cannot share a key, which is why these are pairs and not a
    dict — a map would silently keep only the last source chosen.
    """
    engine = SyncEngine(now_ms=0)
    engine.set_filters(
        Filters(show="all", attention=("unread", "stalled"), sources=("form", "crisp"))
    )

    pairs = engine.next_request(now_ms=0)

    assert ("show", "all") in pairs
    assert pairs.count(("attn[]", "unread")) == 1
    assert ("attn[]", "stalled") in pairs
    assert ("source[]", "form") in pairs
    assert ("source[]", "crisp") in pairs


def test_default_filters_are_not_sent_at_all():
    engine = SyncEngine(now_ms=0)

    keys = {k for k, _ in engine.next_request(now_ms=0)}

    assert "show" not in keys
    assert "presence" not in keys
    assert "price" not in keys
    assert "q" not in keys


# --- the cursor -------------------------------------------------------------


def test_a_failed_request_does_not_move_the_cursor():
    """Every request is already a catch-up request.

    If a failure advanced the cursor, the messages that answer would have
    carried are not delayed — they are lost.
    """
    engine = SyncEngine(now_ms=0)
    engine.apply(
        _envelope(cursor={"m": 412, "rev": 1787170000, "ev": 9, "req": 1}), now_ms=0
    )
    before = engine.cursor

    engine.record_failure()
    engine.record_failure()

    assert engine.cursor == before


def test_the_cursor_never_goes_backwards():
    engine = SyncEngine(now_ms=0)
    engine.apply(_envelope(cursor={"m": 412, "rev": 100, "ev": 9040, "req": 1}), now_ms=0)

    engine.apply(_envelope(cursor={"m": 5, "rev": 200, "ev": 12, "req": 2}), now_ms=0)

    assert engine.cursor.m == 412
    assert engine.cursor.ev == 9040


def test_an_answer_that_was_overtaken_is_discarded():
    """Responses overtake each other on a bad network.

    Applying an older one after a newer one is how a message that was read
    goes unread again.
    """
    engine = SyncEngine(now_ms=0)
    engine.apply(_envelope(cursor={"m": 10, "rev": 100, "ev": 0, "req": 5}), now_ms=0)

    late = engine.apply(
        _envelope(
            cursor={"m": 3, "rev": 90, "ev": 0, "req": 4},
            rows=[{"id": 1, "unread": 9}],
        ),
        now_ms=0,
    )

    assert late.applied is False
    assert late.reason == "stale-req"
    assert late.rows == ()


def test_switching_conversation_resets_the_message_cursor_but_not_the_event_cursor():
    """m is per-conversation in meaning even though ids are global.

    Carrying case 41's high-water mark into case 87 asks for "newer than 812"
    in a thread whose newest message is 90 — an empty transcript.
    """
    engine = SyncEngine(now_ms=0)
    engine.set_open_case(41)
    engine.apply(_envelope(cursor={"m": 812, "rev": 100, "ev": 9040, "req": 1}), now_ms=0)

    engine.set_open_case(87)

    assert engine.cursor.m == 0
    assert engine.cursor.rev == 0, "rev=0 asks the server for a cold answer, which is right"
    assert engine.cursor.ev == 9040, "notifications do not restart when the operator changes desk"


def test_reopening_the_same_conversation_does_not_reset_anything():
    engine = SyncEngine(now_ms=0)
    engine.set_open_case(41)
    engine.apply(_envelope(cursor={"m": 812, "rev": 100, "ev": 0, "req": 1}), now_ms=0)

    engine.set_open_case(41)

    assert engine.cursor.m == 812


# --- the thread -------------------------------------------------------------


def test_a_thread_for_another_conversation_is_dropped_but_the_list_is_kept():
    """The operator clicked away while this was in flight.

    The thread is wrong; the rows, counts and notification feed in the same
    payload are about the whole inbox and are still good.
    """
    engine = SyncEngine(now_ms=0)
    engine.set_open_case(87)

    outcome = engine.apply(
        _envelope(
            thread=_thread(41, messages=[_message(500)]),
            rows=[{"id": 87, "unread": 2, "tone": "wait"}],
        ),
        now_ms=0,
    )

    assert outcome.applied is True
    assert outcome.thread is None
    assert outcome.messages == ()
    assert len(outcome.rows) == 1


def test_messages_arrive_sorted_by_id_even_if_the_server_shuffles_them():
    engine = SyncEngine(now_ms=0)
    engine.set_open_case(41)

    outcome = engine.apply(
        _envelope(thread=_thread(41, messages=[_message(9), _message(3), _message(7)])),
        now_ms=0,
    )

    assert [m.id for m in outcome.messages] == [3, 7, 9]


def test_cold_is_reported_so_the_ui_replaces_instead_of_merging():
    engine = SyncEngine(now_ms=0)
    engine.set_open_case(41)

    outcome = engine.apply(
        _envelope(cold=True, thread=_thread(41, messages=[_message(1)])), now_ms=0
    )

    assert outcome.cold is True


def test_applying_the_same_answer_twice_delivers_nothing_twice():
    engine = SyncEngine(now_ms=0)
    engine.set_open_case(41)

    payload = _envelope(
        cursor={"m": 500, "rev": 100, "ev": 9040, "req": 1},
        thread=_thread(41, messages=[_message(500)]),
        events=[{"key": "e9040", "kind": "message", "case": 41, "at": 1}],
    )

    engine.apply(payload, now_ms=0)
    second = engine.apply(payload, now_ms=0)

    # The thread repeats — the server would not have sent it twice, and the
    # engine does not de-duplicate messages because the cursor already does.
    # The EVENTS must not, or the operator gets the same banner forever.
    assert second.events == ()


# --- notifications ----------------------------------------------------------


def test_an_event_is_announced_once_and_keyed_by_its_own_key():
    """The key is prefixed by kind, so an event id and a case id never collide."""
    engine = SyncEngine(now_ms=0)

    first = engine.apply(
        _envelope(events=[
            {"key": "e9040", "kind": "message", "case": 41, "at": 1},
            {"key": "u41", "kind": "unsubmitted", "case": 41, "at": 1},
        ]),
        now_ms=0,
    )

    assert {e.key for e in first.events} == {"e9040", "u41"}

    second = engine.apply(
        _envelope(events=[{"key": "u41", "kind": "unsubmitted", "case": 41, "at": 1}]),
        now_ms=0,
    )

    assert second.events == (), "unsubmitted is a standing condition re-sent every poll"


def test_only_message_and_request_raise_a_banner():
    engine = SyncEngine(now_ms=0)

    outcome = engine.apply(
        _envelope(events=[
            {"key": "e1", "kind": "message", "case": 1, "at": 1},
            {"key": "e2", "kind": "request", "case": 2, "at": 1},
            {"key": "e3", "kind": "status", "case": 3, "at": 1},
            {"key": "u4", "kind": "unsubmitted", "case": 4, "at": 1},
        ]),
        now_ms=0,
    )

    alerting = {e.kind for e in outcome.events if e.should_alert}

    assert alerting == {"message", "request"}


def test_the_event_cursor_survives_a_restart_with_no_age_limit():
    """The web client threw its event cursor away after five minutes.

    Every page load was a cold start and roughly half the notifications never
    fired — and because the server always returns the head of the log, an
    event dropped that way is never re-offered.
    """
    engine = SyncEngine(now_ms=0)
    engine.apply(_envelope(cursor={"m": 0, "rev": 100, "ev": 9040, "req": 1}), now_ms=0)

    saved = engine.event_cursor
    restarted = SyncEngine(now_ms=0, ev_cursor=saved)

    assert restarted.event_cursor == 9040
    assert dict(restarted.next_request(now_ms=0))["ev"] == "9040"


def test_the_seen_set_is_bounded():
    engine = SyncEngine(now_ms=0)

    for batch in range(40):
        engine.apply(
            _envelope(events=[
                {"key": f"e{batch}-{i}", "kind": "message", "case": 1, "at": 1}
                for i in range(10)
            ]),
            now_ms=0,
        )

    assert len(engine._seen_event_set) <= SyncEngine.SEEN_EVENT_KEYS


# --- cadence ----------------------------------------------------------------


def test_the_cadence_follows_the_conversation_not_a_timer():
    engine = SyncEngine(now_ms=0)

    engine.stir(now_ms=0)
    assert engine.delay_ms(now_ms=1000) == SyncEngine.ACTIVE_MS

    # 30 seconds after the last thing that moved, it settles down.
    assert engine.delay_ms(now_ms=31_000) == SyncEngine.IDLE_MS


def test_a_hidden_window_slows_down_and_a_long_hidden_one_slows_further():
    engine = SyncEngine(now_ms=0)
    engine.set_visible(False, now_ms=0)

    assert engine.delay_ms(now_ms=1000) == SyncEngine.HIDDEN_MS

    dead_at = SyncEngine.HIDDEN_STOP_MS + 1000
    assert engine.delay_ms(now_ms=dead_at) == SyncEngine.WATCH_MS


def test_a_long_hidden_window_stops_entirely_when_notifications_are_off():
    engine = SyncEngine(now_ms=0, notifications_enabled=False)
    engine.set_visible(False, now_ms=0)

    dead_at = SyncEngine.HIDDEN_STOP_MS + 1000

    assert engine.delay_ms(now_ms=dead_at) is None
    assert engine.should_poll(now_ms=dead_at) is False


def test_becoming_visible_again_resumes_fast_and_faster_still_if_it_had_died():
    engine = SyncEngine(now_ms=0)

    engine.set_visible(False, now_ms=0)
    assert engine.set_visible(True, now_ms=5_000) == SyncEngine.RESUME_MS

    engine.set_visible(False, now_ms=10_000)
    dead_at = 10_000 + SyncEngine.HIDDEN_STOP_MS + 1
    assert engine.set_visible(True, now_ms=dead_at) == SyncEngine.RESUME_DEAD_MS


def test_backoff_only_starts_after_a_few_misses_and_is_capped():
    engine = SyncEngine(now_ms=0)
    engine.stir(now_ms=0)

    engine.record_failure()
    engine.record_failure()
    assert engine.delay_ms(now_ms=0) == SyncEngine.ACTIVE_MS, "two drops is not an outage"

    engine.record_failure()
    assert engine.delay_ms(now_ms=0) == 6400

    for _ in range(10):
        engine.record_failure()
    assert engine.delay_ms(now_ms=0) <= SyncEngine.MAX_BACKOFF_MS


def test_any_answer_at_all_clears_the_backoff():
    engine = SyncEngine(now_ms=0)
    for _ in range(6):
        engine.record_failure()

    engine.apply(_envelope(), now_ms=0)

    assert engine.misses == 0


# --- typing -----------------------------------------------------------------


def test_typing_expires_on_its_own_and_costs_no_request():
    engine = SyncEngine(now_ms=0)
    engine.note_composer(True, now_ms=0)

    assert dict(engine.next_request(now_ms=1000))["typing"] == "1"
    assert dict(engine.next_request(now_ms=SyncEngine.TYPING_MS + 1))["typing"] == "0"


def test_clearing_the_composer_ends_typing_immediately():
    engine = SyncEngine(now_ms=0)
    engine.note_composer(True, now_ms=0)
    engine.note_composer(False, now_ms=100)

    assert dict(engine.next_request(now_ms=200))["typing"] == "0"


def test_a_hidden_window_is_never_typing():
    """"AI-PACS is typing…" under a window nobody is in front of is a lie."""
    engine = SyncEngine(now_ms=0)
    engine.note_composer(True, now_ms=0)
    engine.set_visible(False, now_ms=100)

    assert dict(engine.next_request(now_ms=200))["typing"] == "0"
