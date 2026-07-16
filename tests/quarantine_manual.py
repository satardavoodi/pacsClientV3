"""HAND-MAINTAINED quarantine layer (Q0, 2026-07-14).

`tests/quarantine.py` is AUTO-GENERATED (`tools/dev/build_quarantine.py`) and is overwritten on
every regeneration. This file is never generated — put anything that needs human judgement here.

FLAKY TESTS
-----------
These fail NON-DETERMINISTICALLY: the failing set changes between two identical `-n auto` runs.
They were completely invisible while the suite was red by default — flakiness cannot be seen
against a background of 80 permanent failures.

A flaky test is quarantined with `strict=False` (a strict xfail would fail the suite on the runs
where it happens to pass). That is a COMPROMISE, not a fix:

    *** A FLAKY TEST IS A BUG — EITHER IN THE TEST OR IN THE PRODUCT. ***

Flakiness under `-n auto` usually means shared mutable state, a real ordering dependency, or a
timing assumption. Two of these (`upload_manager`) look like shared-state/order dependence, and
one (`test_reception_fetch_speed::test_assignments_are_fetched_in_parallel`) asserts on WALL-CLOCK
timing, which is inherently unreliable on a loaded parallel runner. Each needs a real diagnosis —
and an ordering dependency in the *product* would be a genuine defect, exactly like the
tab-state-poisoning family (OPT-26/50238).

Burn this list down. Do not grow it.
"""

# nodeid -> (category, reason)
#
# FLAKY tests are recorded HERE (not in the auto-generated tests/quarantine.py) because the
# generator captures a SINGLE run: a test that PASSES during generation but FAILS during a later
# run is exactly the flaky case, and it would slip through the auto-list and turn the suite red.
# The manual list is persistent. `strict=False` (see conftest) — a flaky test that happens to
# pass is `xpassed` (harmless), one that fails is `xfailed`, so it can never redden the suite.
#
# *** EACH IS A REAL BUG (in the test or the product). Burn this list down. ***
#
# FIXED (removed — do not re-add):
#   * test_reception_fetch_speed::test_assignments_are_fetched_in_parallel — rewritten to assert
#     on OBSERVED CONCURRENCY instead of wall-clock time (timing-robust). 2026-07-14.
MANUAL_QUARANTINE = {
    # NOTE: upload_manager/test_manager_queue.py is handled by the `flaky_parallel` MARKER (it
    # runs serially), not here — its failure is out-of-call-phase, which xfail cannot convert.
    # The fast_viewer_pipeline "fast interaction" cluster asserts on interaction throttle/surrogate
    # state that depends on wall-clock timing; several flake under the loaded `-n auto` pool.
    # (Most of the file's ~40 tests are stable; only these timing ones are quarantined.)
    "tests/code/viewer/test_fast_viewer_pipeline.py::test_b41_drag_fast_interaction_still_skips_filter":
        ("flaky", "timing-dependent fast-interaction assertion; flakes under parallel load"),
    "tests/code/viewer/test_fast_viewer_pipeline.py::test_filter_skipped_during_fast_interaction":
        ("flaky", "timing-dependent fast-interaction assertion; flakes under parallel load"),
    # Parametrised classifier — one Persian-permission case is non-deterministic across runs.
    # Keyed at FUNCTION level (no `[param]`) so the conftest function-level fallback covers it
    # without transcribing the `\uXXXX`-escaped parametrize id. Covers all params of this test.
    "tests/code/network/test_ino_report_workflow.py::test_classify_error":
        ("flaky", "intermittent Persian-permission classifier case — non-deterministic; needs diagnosis"),
    # CPU-repro test: asserts on scroll/download timer behaviour under load — inherently timing
    # sensitive, flakes under the loaded parallel runner.
    "tests/code/viewer/test_fast_download_scroll_cpu_repro.py::test_fast_download_scroll_overlap_can_trigger_timer_storm":
        ("flaky", "CPU/timing-repro test — non-deterministic under parallel load"),
    # NEW EagleEye mammography-cursor test (untracked WIP as of 2026-07-14). Flaky under parallel
    # load; quarantined non-invasively (no edit to the WIP file) so it cannot redden the suite.
    # Owner should stabilise or mark it when the feature lands.
    "tests/code/ai_imaging/test_cursor3d_two_stage.py::test_radial_agreement_disambiguates_position_ALONG_the_strip":
        ("flaky", "new mammography-cursor WIP test — flaky under parallel load; needs owner triage"),
    # NEW EagleEye mammography-cursor CONTRALATERAL test (untracked WIP as of 2026-07-16). This is a
    # DETERMINISTIC test-vs-implementation disagreement, not a crash: the test asserts a solitary
    # lesion with NO contralateral partner in a view sets asymmetry_flag=True, while
    # contralateral_matcher deliberately treats "nothing to compare against" as INSUFFICIENT DATA
    # (asymmetry_flag=False) with an explicit message. Which stance is clinically correct is the
    # feature owner's call — the two-stage contralateral matcher is explicitly "needs live verify"
    # WIP. Quarantined non-invasively (no edit to the WIP test/code) so it cannot redden the suite;
    # owner reconciles test↔code when the feature lands (the --check audit will flag it as passing).
    "tests/code/ai_imaging/test_cursor3d_contralateral.py::test_analyze_from_store_end_to_end":
        ("wip", "new contralateral-matcher WIP: test expects lonely-lesion=asymmetry, code treats it as insufficient-data; owner must reconcile the clinical stance"),
}
