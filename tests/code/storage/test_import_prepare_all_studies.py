"""Guard for the multi-study import fast-viewer-prep fix (2026-06-15).

Bug: importing a folder with >1 study prepared ONLY the primary study for the
fast viewer, so the other studies opened with an empty "0 series" sidebar (their
per-series thumbnails were never built). Fix: prepare EVERY successfully-saved
study (primary first), in both the manual and startup import paths.

These tests exercise the pure ordering helper and the plural prepare wrapper
without standing up Qt — the wrapper is driven through a fake `self`.
"""
import ast
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO = Path(__file__).resolve().parents[3]
IMPORT_PY = REPO / "PacsClient/pacs/workstation_ui/home_ui/home_panel/_hp_import.py"


# ── ordering helper (pure: does not touch self) ──────────────────────────────

def _call_order_helper(imported, primary, failed):
    from PacsClient.pacs.workstation_ui.home_ui.home_panel._hp_import import _HPImportMixin
    return _HPImportMixin._studies_to_prepare_for_fast_open(
        SimpleNamespace(), imported, primary, failed
    )


def test_order_primary_first_then_rest():
    s1 = {"study_uid": "A"}
    s2 = {"study_uid": "B"}
    s3 = {"study_uid": "C"}
    out = _call_order_helper([s1, s2, s3], primary=s2, failed=[])
    assert [s["study_uid"] for s in out] == ["B", "A", "C"]  # primary first, no dup


def test_order_excludes_failed_studies():
    s1 = {"study_uid": "A"}
    s2 = {"study_uid": "B"}
    out = _call_order_helper([s1, s2], primary=s1, failed=["B"])
    assert [s["study_uid"] for s in out] == ["A"]  # B failed -> excluded


def test_order_failed_primary_excluded_but_others_prepared():
    s1 = {"study_uid": "A"}
    s2 = {"study_uid": "B"}
    out = _call_order_helper([s1, s2], primary=s1, failed=["A"])
    assert [s["study_uid"] for s in out] == ["B"]  # primary failed, B still prepared


def test_order_no_primary_still_prepares_all():
    s1 = {"study_uid": "A"}
    s2 = {"study_uid": "B"}
    out = _call_order_helper([s1, s2], primary=None, failed=[])
    assert {s["study_uid"] for s in out} == {"A", "B"}


def test_order_single_study_unchanged():
    s1 = {"study_uid": "A"}
    out = _call_order_helper([s1], primary=s1, failed=[])
    assert [s["study_uid"] for s in out] == ["A"]


# ── plural wrapper prepares EVERY study, isolates per-study failure ───────────

def test_plural_prepare_calls_each_study():
    from PacsClient.pacs.workstation_ui.home_ui.home_panel._hp_import import _HPImportMixin
    calls = []

    def fake_single(study):
        calls.append(study["study_uid"])
        return 3

    fake_self = SimpleNamespace(_prepare_imported_study_for_fast_open=fake_single)
    total = _HPImportMixin._prepare_imported_studies_for_fast_open(
        fake_self, [{"study_uid": "A"}, {"study_uid": "B"}]
    )
    assert calls == ["A", "B"]
    assert total == 6  # 3 + 3 generated thumbnails


def test_plural_prepare_isolates_one_failing_study():
    from PacsClient.pacs.workstation_ui.home_ui.home_panel._hp_import import _HPImportMixin
    calls = []

    def fake_single(study):
        calls.append(study["study_uid"])
        if study["study_uid"] == "A":
            raise RuntimeError("boom")
        return 5

    fake_self = SimpleNamespace(_prepare_imported_study_for_fast_open=fake_single)
    # A raises but must not stop B from being prepared.
    total = _HPImportMixin._prepare_imported_studies_for_fast_open(
        fake_self, [{"study_uid": "A"}, {"study_uid": "B"}]
    )
    assert calls == ["A", "B"]
    assert total == 5


# ── both import call sites now prepare ALL studies (source guard) ─────────────

def test_both_import_paths_use_plural_prepare():
    src = IMPORT_PY.read_text(encoding="utf-8-sig")  # strip BOM for ast.parse
    # The single-study prep must no longer be the job target at the call sites;
    # both paths go through the plural wrapper + ordering helper.
    assert src.count("_prepare_imported_studies_for_fast_open") >= 3  # def + 2 calls
    assert src.count("_studies_to_prepare_for_fast_open") >= 3        # def + 2 calls
    # The single-study fn is still called (by the plural wrapper) exactly once in source.
    tree = ast.parse(src)
    plural_call_sites = sum(
        1 for n in ast.walk(tree)
        if isinstance(n, ast.Attribute) and n.attr == "_prepare_imported_studies_for_fast_open"
    )
    assert plural_call_sites >= 2  # manual + startup import both use it
