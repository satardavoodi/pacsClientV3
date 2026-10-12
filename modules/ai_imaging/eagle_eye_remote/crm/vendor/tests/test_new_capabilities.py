"""The four capabilities the v3 benchmark found missing, and the traps in them.

Twenty-one of seventy questions were unanswerable, and in every case the data
was already on the reception server. These tests hold the parts that are easy to
get wrong and impossible to notice: a join whose two sides are different types, a
percentage with no denominator, a caveat that lives in a docstring instead of in
the payload, and patient names returned by default.

Mongo is not available in this suite, so the database is stubbed. That is the
right boundary: what is being tested is the arithmetic and the honesty, not
pymongo.
"""

from __future__ import annotations

import pytest

from reception_crm.core.registry import default_registry
from reception_crm.local import appointments
from reception_crm.local import datamodel as dm
from reception_crm.local import people


class _FakeCollection:
    def __init__(self, docs):
        self._docs = list(docs)

    def find(self, query=None, projection=None):
        if query and query.get("field") == "typist":
            return _FakeCursor([
                doc for doc in self._docs
                if doc.get("field") == "typist"
                and doc.get("action") in query["action"]["$in"]
            ])
        return _FakeCursor(self._docs)

    def count_documents(self, query=None):
        return len(self._docs)


class _FakeCursor:
    def __init__(self, docs):
        self._docs = list(docs)

    def limit(self, n):
        return iter(self._docs[:n])

    def sort(self, *_args, **_kwargs):
        return self

    def __iter__(self):
        return iter(self._docs)


class _FakeDb:
    def __init__(self, collections):
        self._collections = collections

    def __getitem__(self, name):
        return _FakeCollection(self._collections.get(name, []))


class _NoLock:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


# --------------------------------------------------------- the room join trap

ROOM_ID = "68807061-room-a"

ROOMS = [
    {
        "_id": ROOM_ID,                      # a STRING, as this database stores it
        "name": "MRI 1",
        "persianName": "ام آر آی ۱",
        "roomNumber": "101",
        "modalityId": "2",
        "isActive": True,
        # ⚠️ THE NESTING IS THE POINT. A shift carries a NAME and its windows;
        # `day` and `capacity` live on the WINDOW. Both wrong versions of this
        # tool put them on the shift, and both produced a confident number.
        # 1405/06/02 is a دوشنبه.
        "shifts": [
            {"isActive": True, "name": "صبح", "timeSlots": [
                {"day": "دوشنبه", "startTime": "08:00", "endTime": "12:00",
                 "capacity": 3, "isAvailable": True},
                # A different weekday: must not count towards Monday's capacity.
                {"day": "سه‌شنبه", "startTime": "08:00", "endTime": "12:00",
                 "capacity": 40, "isAvailable": True},
                # Declared for today but switched off.
                {"day": "دوشنبه", "startTime": "12:00", "endTime": "13:00",
                 "capacity": 9, "isAvailable": False},
            ]},
            # The whole shift is off, so nothing inside it counts either.
            {"isActive": False, "name": "شب", "timeSlots": [
                {"day": "دوشنبه", "startTime": "20:00", "endTime": "21:00",
                 "capacity": 50, "isAvailable": True},
            ]},
        ],
    },
    {
        "_id": "room-with-no-diary",
        "name": "CT 1", "persianName": "سی تی ۱", "modalityId": "1",
        "isActive": True, "shifts": [],
    },
]


class _ObjectIdLike:
    """A stand-in for bson.ObjectId: not a str, but str() gives the same text.

    ⚠️ This is the whole point of the test. `Rooms._id` is a string in this
    database and `appointment.room` is an ObjectId, so the two sides of the join
    are never equal even when they name the same room. A free-slot report whose
    join silently fails says every room is empty — which is indistinguishable
    from a genuinely empty day and is the worst possible failure for this tool.
    """

    def __init__(self, text):
        self._text = text

    def __str__(self):
        return self._text

    def __eq__(self, other):
        return isinstance(other, _ObjectIdLike) and other._text == self._text

    def __hash__(self):
        return hash(self._text)


BOOKED = [
    {"ReceptionID": 1, "Date": "1405/06/02", "imagingWorkflow": {"appointment": {
        "persianDate": "1405/06/02", "startTime": "08:00", "endTime": "08:30",
        "duration": 30, "timeSlot": "08:00 تا 08:30", "shiftName": "صبح",
        "room": _ObjectIdLike(ROOM_ID)}}},
    {"ReceptionID": 2, "Date": "1405/06/01", "imagingWorkflow": {"appointment": {
        "persianDate": "1405/06/02", "startTime": "08:30", "endTime": "09:00",
        "duration": 30, "timeSlot": "08:30 تا 09:00", "shiftName": "صبح",
        "room": _ObjectIdLike(ROOM_ID)}}},
]


@pytest.fixture
def diary(monkeypatch):
    monkeypatch.setattr(appointments, "scan_slot", _NoLock)
    monkeypatch.setattr(appointments, "reception_db",
                        lambda: _FakeDb({"Rooms": ROOMS, "receptions": BOOKED}))


def test_a_room_is_matched_although_the_two_ids_are_different_types(diary):
    """The join hazard, held down. If this breaks, availability reports every
    room as empty and reads exactly like a quiet day."""
    out = appointments.appointments_on(date="1405/06/02")
    assert out["booked_total"] == 2
    assert out["rows"][0]["room"] == "ام آر آی ۱", (
        "the room name did not resolve — the ObjectId/str join has failed again"
    )


def test_utilisation_is_none_where_the_room_has_no_shift_that_day(diary):
    """⚠️ None, never 0.0. A percentage against a diary nobody wrote is a
    statement about our arithmetic, not about the clinic — and «۰٪ پر شده»
    would be read as an empty room rather than an undeclared one."""
    out = appointments.availability(date="1405/06/02")
    rows = {row["room"]: row for row in out["rows"]}
    assert rows["سی تی ۱"]["declared_capacity"] == 0
    assert rows["سی تی ۱"]["utilisation_percent"] is None
    assert rows["سی تی ۱"]["places_left"] is None


def test_capacity_comes_from_the_window_not_from_counting_windows(diary):
    """⚠️ THE TWO DENOMINATORS THAT WERE WRONG.

    First version: capacity = the NUMBER of time slots → 127 bookings against
    64 slots, 198% utilisation, and a room is never more than full.

    Second version: capacity = Σ `shift.capacity`, filtered on `shift.day` —
    fields that do not exist. Every room matched nothing, capacity came out 0,
    and the tool reported `null` on a day holding 127 appointments.

    `day` and `capacity` are on the WINDOW (`shifts[].timeSlots[]`)."""
    out = appointments.availability(date="1405/06/02")
    rows = {row["room"]: row for row in out["rows"]}
    assert rows["ام آر آی ۱"]["declared_capacity"] == 3
    assert rows["ام آر آی ۱"]["booked"] == 2
    assert rows["ام آر آی ۱"]["utilisation_percent"] == round(200 / 3, 1)
    assert rows["ام آر آی ۱"]["places_left"] == 1


def test_another_weekdays_window_is_not_todays_capacity(diary):
    """A window's `day` is a Persian WEEKDAY, so the diary is a weekly pattern.
    Counting all of them would put Tuesday's 40 places into Monday's
    utilisation — wrong in the direction that looks reassuring: plenty of room,
    on a day that is full."""
    out = appointments.availability(date="1405/06/02")
    assert out["weekday"] == "دوشنبه"
    rows = {row["room"]: row for row in out["rows"]}
    windows = rows["ام آر آی ۱"]["windows_today"]
    assert len(windows) == 1 and windows[0]["capacity"] == 3


def test_a_window_that_is_switched_off_is_not_capacity(diary):
    """Both levels can be off — the shift, and the window inside it. Counting
    either would offer places the clinic cannot actually sell."""
    out = appointments.availability(date="1405/06/02")
    rows = {row["room"]: row for row in out["rows"]}
    assert rows["ام آر آی ۱"]["declared_capacity"] == 3, (
        "the unavailable window (9) or the inactive shift (50) leaked in"
    )


def test_more_bookings_than_capacity_is_flagged_not_reported_as_a_percentage(monkeypatch):
    """A room is never more than full, so a figure above 100% means the declared
    capacity is not what the clinic worked to that day. Saying that is the
    answer; quoting 198% as a utilisation is not."""
    monkeypatch.setattr(appointments, "scan_slot", _NoLock)
    monkeypatch.setattr(appointments, "reception_db",
                        lambda: _FakeDb({"Rooms": ROOMS,
                                         "receptions": BOOKED + BOOKED + BOOKED}))
    out = appointments.availability(date="1405/06/02")
    assert out["booked_total"] == 6 and out["declared_capacity_total"] == 3
    assert out["over_capacity"] is True
    assert "over_capacity" in out["meaning_fa"]


def test_a_day_with_nothing_booked_answers_zero_rather_than_failing(monkeypatch):
    """A ZERO IS AN ANSWER. The benchmark's «نوبت‌های فردا» had none, and «۰
    نوبت» stated plainly is correct — not a refusal, and not a silence that
    reads as a failure to find data."""
    monkeypatch.setattr(appointments, "scan_slot", _NoLock)
    monkeypatch.setattr(appointments, "reception_db",
                        lambda: _FakeDb({"Rooms": ROOMS, "receptions": []}))
    out = appointments.appointments_on(date="1405/06/04")
    assert out["booked_total"] == 0
    assert "error" not in out
    assert out["meaning_fa"]


def test_a_missing_date_is_refused_rather_than_defaulted(diary):
    out = appointments.appointments_on(date=None)
    assert out["error"]["code"] == "DATE_REQUIRED"


def test_the_booking_versus_attendance_answer_is_structural(diary):
    """«چند نفر نوبت داشتن ولی پذیرش نشدن؟» has no numeric answer, because an
    appointment is a field ON a reception. Explaining that is the answer."""
    out = appointments.appointment_vs_reception(date="1405/06/02")
    assert out["appointments_on_the_day"] == 2
    assert out["of_those_admitted_the_same_day"] == 1
    assert "ناممکن" in out["meaning_fa"]


# ------------------------------------- the modality filter on a free-slot day

class _FakeModality:
    """Enough of `datamodel.Modality` for the room filter to compare codes."""

    def __init__(self, code: str, label: str):
        self.code = code
        self.label = label


_CATALOGUE = {"1": _FakeModality("1", "CT (سی تی)"),
              "2": _FakeModality("2", "MRI (ام آر آی)")}


@pytest.fixture
def catalogue(monkeypatch, diary):
    """The vendor catalogue, stubbed: a word in, a CODE out."""
    words = {"mri": "2", "ام آر آی": "2", "ct": "1", "سی تی": "1", "سونوگرافی": "3"}

    def resolve(value):
        code = words.get(str(value).strip().lower())
        if code is None:
            raise dm.UnknownValue("modality", str(value),
                                  [m.label for m in _CATALOGUE.values()])
        return _CATALOGUE.get(code) or _FakeModality(code, f"code {code}")

    monkeypatch.setattr(appointments.dm, "resolve_modality", resolve)
    monkeypatch.setattr(appointments.dm, "modalities", lambda: _CATALOGUE)


def test_a_modality_asked_for_in_words_still_selects_its_room(catalogue):
    """⚠️ THE BUG THIS PINS DOWN. `Rooms.modalityId` is the vendor's code —
    '1', '2' — and the user says «ام آر آی». The filter compared the word
    against the code, matched no room, and the tool answered «برای این روز هیچ
    اتاق یا ظرفیت فعالی تعریف نشده است» on a day with rooms and capacity.

    Four benchmark questions were answered that way, and none of them looked
    like an error: an empty diary and an unmatched filter print the same."""
    out = appointments.availability(date="1405/06/02", modality="MRI")
    assert out["filter_matched_no_room"] is False
    assert out["rooms_considered"] == 1
    assert out["declared_capacity_total"] == 3
    assert out["modality_requested"] == "MRI (ام آر آی)"


def test_a_modality_with_no_room_is_not_reported_as_a_day_with_no_capacity(catalogue):
    """The zeros are about the SELECTION. Saying so — and naming what does have
    a room — is the difference between "we don't book that here" and "the
    centre is shut tomorrow"."""
    out = appointments.availability(date="1405/06/02", modality="سونوگرافی")
    assert out["filter_matched_no_room"] is True
    assert out["rooms_considered"] == 0
    assert out["modalities_with_a_room"] == ["CT (سی تی)", "MRI (ام آر آی)"]


def test_an_unfiltered_day_is_unaffected_by_any_of_this(catalogue):
    out = appointments.availability(date="1405/06/02")
    assert out["filter_matched_no_room"] is False
    assert out["modality_requested"] is None
    assert out["rooms_considered"] == 2


def test_a_modality_this_database_never_heard_of_is_refused_with_the_vocabulary(catalogue):
    """Refused, not silently empty — the rule `datamodel` exists to keep. The
    refusal travels through the TOOL, because that is where the model reads it."""
    from reception_crm.core.tools import people_local

    out = people_local._availability({"date": "1405/06/02", "modality": "پانورامیک"})
    assert out["error"]["code"]
    assert "MRI (ام آر آی)" in str(out["error"])


# ------------------------------------------------------------------ referrers

@pytest.fixture
def referrals(monkeypatch):
    monkeypatch.setattr(people, "scan_slot", _NoLock)
    monkeypatch.setattr(people, "reception_db", lambda: _FakeDb({
        "receptions": [
            {"referrerPhysician": "ref-a", "patient": "p1"},
            {"referrerPhysician": "ref-a", "patient": "p1"},
            {"referrerPhysician": "ref-a", "patient": "p2"},
            {"referrerPhysician": "ref-b", "patient": "p3"},
        ],
        "ReferrerPhysician": [
            {"_id": "ref-a", "FullName": "دکتر الف", "Expertise": "ارتوپدی"},
        ],
    }))


def test_receptions_and_distinct_patients_are_both_reported(referrals):
    """⚠️ They are different numbers and the question is usually ambiguous
    between them: the same patient referred twice is two receptions and one
    person. Reporting one without the other invites the reader to assume the
    other."""
    out = people.referring_physicians(date_from="1405/06/01", date_to="1405/06/30")
    top = out["rows"][0]
    assert top["receptions"] == 3
    assert top["patients"] == 2


def test_a_referrer_id_is_resolved_to_a_name(referrals):
    out = people.referring_physicians(date_from="1405/06/01", date_to="1405/06/30")
    assert out["rows"][0]["name"] == "دکتر الف (ارتوپدی)"


def test_an_unresolvable_referrer_is_counted_not_hidden(referrals):
    """A referrer whose record is gone still sent patients. Dropping the row
    would quietly shrink the total; leaving it unnamed says what is true."""
    out = people.referring_physicians(date_from="1405/06/01", date_to="1405/06/30")
    assert out["unresolved_names"] == 1
    assert any(row["name"] is None for row in out["rows"])


def test_an_unbounded_referrer_query_is_refused(referrals):
    """⚠️ Not a convenience. This scans the database a clinic is using right
    now, and «کدوم پزشک این ماه» always has a month in it."""
    out = people.referring_physicians()
    assert out["error"]["code"] == "PERIOD_REQUIRED"


# ------------------------------------------------------- staff activity windows

def test_the_activity_window_says_it_is_not_attendance(monkeypatch):
    """⚠️ THE WHOLE POINT OF THE TOOL. There is no attendance table here, so the
    first recorded action is a LOWER BOUND on arrival. The caveat is bound to
    the payload rather than left in a docstring, because the model reads the
    payload and never sees the docstring."""
    monkeypatch.setattr(people, "scan_slot", _NoLock)
    monkeypatch.setattr(people, "reception_db", lambda: _FakeDb({
        "receptions": [
            {"registeredBy": "u1", "Date": "1405/06/02", "Time": "08:08:48"},
            {"registeredBy": "u1", "Date": "1405/06/02", "Time": "14:14:45"},
        ],
        "transactions": [
            {"registeredBy": "u1", "date": "1405/06/02", "time": "07:54:34"},
        ],
        "ReportLogs": [],
        "AdminUsers": [],
    }))
    out = people.staff_activity(date_from="1405/06/02", date_to="1405/06/02")
    assert "not clock-in" in out["⚠️_not_attendance"]
    assert "حضور و غیاب" in out["meaning_fa"]

    row = out["rows"][0]
    assert row["activity"]["registrations"]["first"] == "1405/06/02 08:08:48"
    assert row["activity"]["registrations"]["last"] == "1405/06/02 14:14:45"
    # ⚠️ Counted separately from the registrations, because 53 receptions
    # registered and 105 transactions processed are not the same quantity and
    # ranking «حجم کار» by adding them produces a league table of nothing.
    assert row["activity"]["transactions"]["first"] == "1405/06/02 07:54:34"
    assert set(row["activity"]) == {"registrations", "transactions"}
    assert out["report_activity_quality"]["attribution_coverage_percent"] is None


def test_report_log_events_are_not_presented_as_report_counts(monkeypatch):
    """A single report emits several log rows; duplicate approvals are still
    one distinct report. Editing/assignment activity is not approval work."""
    monkeypatch.setattr(people, "scan_slot", _NoLock)
    monkeypatch.setattr(people, "reception_db", lambda: _FakeDb({
        "receptions": [],
        "transactions": [],
        "ReportLogs": [
            {"changedBy": "u1", "persianDate": "1405/06/12",
             "persianTime": "10:00", "receptionID": 101,
             "action": "secretary_approved"},
            {"changedBy": "u1", "persianDate": "1405/06/12",
             "persianTime": "10:01", "receptionID": 101,
             "action": "secretary_approved"},
            {"changedBy": "u1", "persianDate": "1405/06/12",
             "persianTime": "10:02", "receptionID": 101,
             "action": "physician_approved"},
            {"changedBy": "u1", "persianDate": "1405/06/12",
             "persianTime": "10:03", "receptionID": 101,
             "action": "status_changed"},
            {"changedBy": "u1", "persianDate": "1405/06/12",
             "persianTime": "10:04", "receptionID": 102,
             "action": "secretary_approved"},
            {"changedBy": "u1", "persianDate": "1405/06/12",
             "persianTime": "10:05", "receptionID": 102,
             "action": "content_updated"},
            {"changedBy": "u2", "persianDate": "1405/06/12",
             "persianTime": "11:00", "receptionID": 103,
             "action": "content_updated"},
            {"changedBy": "u2", "persianDate": "1405/06/12",
             "persianTime": "11:01", "receptionID": 103,
             "action": "findings_updated"},
            {"changedBy": "u2", "persianDate": "1405/06/12",
             "persianTime": "11:02", "receptionID": 103,
             "action": "radiologist_assigned"},
            {"changedBy": None, "persianDate": "1405/06/12",
             "persianTime": "11:03", "receptionID": 104,
             "action": "status_changed"},
            {"persianDate": "1405/06/12", "persianTime": "11:04",
             "receptionID": 105, "action": "content_updated"},
            {"persianDate": "1405/06/12", "persianTime": "11:05",
             "action": "content_updated"},
        ],
        "AdminUsers": [],
    }))

    out = people.staff_activity(date_from="1405/06/12", date_to="1405/06/12")
    rows = {row["userId"]: row for row in out["rows"]}
    u1 = rows["u1"]["activity"]["report_actions"]
    assert u1["count"] == u1["events"] == 6
    assert u1["distinct_reports"] == 2
    assert u1["secretary_approved_reports"] == 2
    assert u1["physician_approved_reports"] == 1
    assert u1["approval_reports"] == 2
    assert u1["content_edited_reports"] == 1
    assert u1["distinct_reports_by_action"]["secretary_approved"] == 2
    assert u1["event_counts_by_action"]["secretary_approved"] == 3

    u2 = rows["u2"]["activity"]["report_actions"]
    assert u2["distinct_reports"] == 1
    assert u2["approval_reports"] == 0
    assert u2["content_edited_reports"] == 1
    assert u2["radiologist_assigned_reports"] == 1

    quality = out["report_activity_quality"]
    assert quality == {
        "log_events": 12,
        "attributed_events": 9,
        "unattributed_events": 3,
        "events_missing_reception_id": 1,
        "attribution_coverage_percent": 75.0,
        "distinct_reports_with_log_activity": 5,
        "distinct_reports_with_attributed_activity": 3,
        "distinct_reports_without_attributed_activity": 2,
        "report_attribution_coverage_percent": 60.0,
        "capped": False,
    }
    assert "لاگ" in out["meaning_fa"]
    assert "not reports" in u1["metric_note"]
    edits = out["report_content_activity"]
    assert edits["distinct_edited_reports"] == 3
    assert edits["reports_with_attributed_edits"] == 2
    assert edits["reports_with_only_unattributed_edits"] == 1
    assert edits["unattributed_edit_events"] == 2
    assert "پزشک" in out["role_definitions"]["service_performer"]
    assert out["typist_assignments"]["assigned_reports"] == 0


# ------------------------------------------------------------ name-change trail

NAME_CHANGE_DOCS = [
    {"persianDate": "1405/06/02", "persianTime": "10:00", "changedBy": "u1",
     "changedByName": "کاربر یک", "reason": "admin_override", "blocked": False,
     "oldName": "نام قدیمی", "newName": "نام جدید",
     "relatedReceptions": [{"receptionId": 55773}]},
    {"persianDate": "1405/06/02", "persianTime": "11:00", "changedBy": "u2",
     "changedByName": "کاربر دو", "reason": "spelling", "blocked": True,
     "oldName": "الف", "newName": "ب", "relatedReceptions": []},
]


@pytest.fixture
def trail(monkeypatch):
    monkeypatch.setattr(people, "reception_db",
                        lambda: _FakeDb({"PatientNameChangeLogs": NAME_CHANGE_DOCS}))


def test_patient_names_are_withheld_unless_asked_for(trail):
    """The counts, reasons and actors answer «آیا تغییری ثبت شده؟» without
    naming a patient. The names are the exception and they are opt-in."""
    out = people.name_changes(date_from="1405/06/02", date_to="1405/06/02")
    assert out["names_included"] is False
    assert out["rows"][0]["oldName"].startswith("<withheld:")
    assert out["rows"][0]["newName"].startswith("<withheld:")


def test_names_are_returned_when_the_caller_asks(trail):
    out = people.name_changes(date_from="1405/06/02", date_to="1405/06/02",
                              include_names=True)
    assert out["rows"][0]["oldName"] == "نام قدیمی"


def test_a_blocked_change_is_reported_as_blocked(trail):
    """`blocked: true` means the change did NOT happen. Counting it as one
    would turn a working control into an incident."""
    out = people.name_changes(date_from="1405/06/02", date_to="1405/06/02")
    assert out["blocked"] == 1
    assert out["by_reason"] == {"admin_override": 1, "spelling": 1}


def test_the_trail_does_not_call_itself_a_finding(trail):
    out = people.name_changes(date_from="1405/06/02", date_to="1405/06/02")
    assert "تخلف" in out["meaning_fa"], (
        "the payload should say a record is not misconduct, because the scenario "
        "that reads it is the one looking for misconduct"
    )


# ------------------------------------------------------------ registry hygiene

def test_the_diary_and_the_waiting_queue_are_different_tools():
    """⚠️ The first draft of the diary registered as `appointments.list` and
    REPLACED the waiting-queue tool in silence. Nothing failed and no test
    noticed; the only symptom would have been the queue tool answering a
    different question from the one its description promises."""
    tools = default_registry().tools
    assert "appointments.list" in tools and "appointments.day" in tools
    assert "queue" in tools["appointments.list"].description.lower()
    assert tools["appointments.day"].handler is not tools["appointments.list"].handler


def test_registering_a_name_twice_is_refused():
    from reception_crm.core.registry import ToolRegistry

    registry = ToolRegistry()
    first = default_registry().get("appointments.day")
    second = default_registry().get("appointments.availability")
    registry.register(first)
    with pytest.raises(ValueError, match="already registered"):
        registry.register(
            type(second)(**{**second.__dict__, "name": first.name})
        )
