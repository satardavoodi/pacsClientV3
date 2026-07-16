"""OPT-35 / Q2 — STATEFUL model of the multi-study identity core (hypothesis).

This is the test technique the last ten bugs demanded and none of the 566 example-based tests
provided (Quality roadmap §2/§3-L3). 48912, 49836, 50238 and OPT-36 were all **order-dependent
state bugs**: a display key resolved to the WRONG study depending on the SEQUENCE of loads /
previous-exam merges. An example test picks one sequence; a `RuleBasedStateMachine` explores
*arbitrary* sequences and shrinks any failure to a minimal reproducer.

The model drives the pure `SeriesRef` authority (`PacsClient/utils/series_ref.py`) the way the real
multi-study viewer does, building `server_series_info` EXACTLY as `_rebuild_multistudy_series_index`
does (offset keys `slot*1_000_000 + orig`, stamped entries, stable first-seen slot order). It then
asserts the invariants the whole OPT-35 refactor is supposed to guarantee — under every reachable
state:

  I1  every display key resolves to ITS OWN study (never another study's), with the right
      original series number and the right globally-unique series_uid;
  I2  SLOT STABILITY — a key issued for a study must keep resolving to that SAME study after any
      number of later previous-exam merges (the 2026-06-20 "same key -> two studies over time"
      class);
  I3  display keys are unique and series_uids are globally unique (colliding orig numbers across
      studies get DISTINCT keys — the root enabler of the whole bug family);
  I4  the slot-fallback path (entry dropped by a later rebuild) resolves an offset key to the SAME
      study as the table path — never silently to the primary (the 2026-06-21 drag bug);
  I5  a synthetic series number (device omitted SeriesNumber -> 900001..999999) stays a PLAIN
      primary-study key, never mistaken for an offset key (C2).

Pure: stdlib + hypothesis only, no Qt/VTK/DB. Marked `property`.
"""

import pytest

pytest.importorskip("hypothesis")

from hypothesis import HealthCheck, settings
from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, invariant, rule

from PacsClient.utils.series_ref import (
    MULTISTUDY_OFFSET,
    build_series_ref_table,
    is_offset_key,
    resolve_series_ref,
)

SRC = "/src"
PRIMARY = "STUDY_P"


def _build_server_series_info(slot_order, series_by_study, source_root):
    """Faithful mirror of _rebuild_multistudy_series_index (_pw_thumbnails.py:592)."""
    info = {}
    for slot, su in enumerate(slot_order):
        offset = 0 if slot == 0 else slot * MULTISTUDY_OFFSET
        for orig in sorted(series_by_study[su]):
            suid = series_by_study[su][orig]
            key = str(orig + offset)
            info[key] = {
                "series_number": key,
                "_orig_series_number": str(orig),
                "_study_slot": slot,
                "study_uid": su,
                "series_path": f"{source_root}/{su}/{orig}",
                "series_uid": suid,
            }
    return info


class MultiStudyIdentityMachine(RuleBasedStateMachine):
    """A patient tab that accumulates studies (a primary + merged previous exams), each with
    series whose ORIGINAL numbers may collide across studies."""

    def __init__(self):
        super().__init__()
        self.primary = PRIMARY
        self.slot_order = [self.primary]           # stable, first-seen; primary always slot 0
        self.series_by_study = {self.primary: {}}   # study_uid -> {orig:int -> series_uid:str}
        self._uid_counter = 0
        self._issued = {}                           # display_key -> (study_uid, orig, series_uid)

    def _uid(self):
        self._uid_counter += 1
        return f"1.2.826.{self._uid_counter}"

    def _info(self):
        return _build_server_series_info(self.slot_order, self.series_by_study, SRC)

    # ── rules: how a real multi-study tab evolves ──────────────────────────
    @rule(orig=st.integers(min_value=1, max_value=15))
    def add_series_to_primary(self, orig):
        self.series_by_study[self.primary].setdefault(orig, self._uid())

    @rule(
        study=st.integers(min_value=1, max_value=4),
        origs=st.lists(st.integers(min_value=1, max_value=15), min_size=1, max_size=4, unique=True),
    )
    def merge_previous_exam(self, study, origs):
        su = f"STUDY_{study}"
        if su not in self.series_by_study:
            self.series_by_study[su] = {}
            self.slot_order.append(su)             # STABLE append — never reorder existing slots
        for orig in origs:
            self.series_by_study[su].setdefault(orig, self._uid())

    @rule(orig=st.integers(min_value=900001, max_value=999999))
    def add_synthetic_numbered_series_to_primary(self, orig):
        # A device that omitted SeriesNumber -> a synthetic number in the reserved band (C2/OPT-25).
        self.series_by_study[self.primary].setdefault(orig, self._uid())

    # ── invariants: checked after EVERY rule, in EVERY reachable state ─────
    @invariant()
    def resolution_is_correct_and_slot_stable(self):
        info = self._info()
        table = build_series_ref_table(info, self.primary, SRC)
        for slot, su in enumerate(self.slot_order):
            offset = 0 if slot == 0 else slot * MULTISTUDY_OFFSET
            for orig in self.series_by_study[su]:
                suid = self.series_by_study[su][orig]
                key = str(orig + offset)
                ref = resolve_series_ref(
                    key, table, server_series_info=info, primary_study_uid=self.primary,
                    source_root=SRC, studies_index=self.series_by_study, slot_order=self.slot_order,
                )
                # I1: resolves to its OWN study, number, uid.
                assert ref is not None, f"key {key} did not resolve"
                assert ref.study_uid == su, f"key {key} -> {ref.study_uid}, expected {su}"
                assert ref.series_number == str(orig), f"key {key} -> series {ref.series_number}"
                assert ref.series_uid == suid, f"key {key} -> uid {ref.series_uid}, expected {suid}"
                # I2: slot stability — a key never changes the study it points to over time.
                prev = self._issued.get(key)
                assert prev in (None, (su, str(orig), suid)), (
                    f"key {key} changed identity: was {prev}, now {(su, str(orig), suid)}"
                )
                self._issued[key] = (su, str(orig), suid)

    @invariant()
    def keys_and_uids_are_unique(self):
        info = self._info()
        keys = list(info.keys())
        assert len(keys) == len(set(keys)), "duplicate display key across studies"
        uids = [e["series_uid"] for e in info.values()]
        assert len(uids) == len(set(uids)), "duplicate series_uid across studies"

    @invariant()
    def slot_fallback_agrees_with_the_table(self):
        # I4: simulate the entry being dropped by a later rebuild — resolution must fall back to
        # the SAME study via the stable slot order, never silently to the primary.
        for slot, su in enumerate(self.slot_order):
            if slot == 0:
                continue                            # primary keys are bare; no offset fallback
            offset = slot * MULTISTUDY_OFFSET
            for orig in self.series_by_study[su]:
                key = str(orig + offset)
                ref = resolve_series_ref(
                    key, None, server_series_info={}, primary_study_uid=self.primary,
                    source_root=SRC, studies_index=self.series_by_study, slot_order=self.slot_order,
                )
                assert ref is not None and ref.source == "slot_fallback"
                assert ref.study_uid == su, (
                    f"slot-fallback key {key} -> {ref.study_uid}, expected {su} (leaked to primary?)"
                )
                assert ref.series_number == str(orig)

    @invariant()
    def synthetic_numbers_stay_plain_primary_keys(self):
        # I5: a synthetic 9xxxxx number on the primary must remain a PLAIN key (below the offset
        # threshold) resolving to the primary study.
        for orig in self.series_by_study[self.primary]:
            if 900001 <= orig <= 999999:
                key = str(orig)
                assert not is_offset_key(key)
                info = self._info()
                table = build_series_ref_table(info, self.primary, SRC)
                ref = resolve_series_ref(
                    key, table, server_series_info=info, primary_study_uid=self.primary,
                    source_root=SRC, studies_index=self.series_by_study, slot_order=self.slot_order,
                )
                assert ref is not None and ref.study_uid == self.primary and ref.is_primary


# Bind the machine as a pytest TestCase. `property` marker keeps it in the fast lane but lets the
# nightly lane bump the example/step counts. suppress the function-scoped-fixture health check
# (there are none) and keep the step count modest so the fast lane stays quick.
TestMultiStudyIdentity = MultiStudyIdentityMachine.TestCase
TestMultiStudyIdentity.settings = settings(
    max_examples=150,
    stateful_step_count=40,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
    deadline=None,
)
pytestmark = pytest.mark.property
