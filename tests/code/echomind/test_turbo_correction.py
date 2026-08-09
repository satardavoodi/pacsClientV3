"""Guard: Turbo in the Correction tab EDITS the selected report (2026-08-09).

OBSERVED. With the Correction tab active, Turbo fell through to the report branch of
`_on_hq_all_modality_clicked`, took the correction INSTRUCTION as if it were a dictation,
and called `reporter()`. The physician got a brand-new report generated from his own edit
note, and the report he had selected was never sent at all.
"""

import inspect
import io
import os
import sys

import pytest

_THIS = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.normpath(os.path.join(_THIS, "..", "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from modules.EchoMind.viewer_chat import openai_parallel_backend as ob    # noqa: E402
from modules.EchoMind.viewer_chat import openai_reporter as cb            # noqa: E402
from modules.EchoMind.viewer_chat import turbo_prompt as tp               # noqa: E402

_PAGES = os.path.join(_ROOT, "modules", "EchoMind", "viewer_chat", "ai_chat_pages.py")


def _src():
    return io.open(_PAGES, encoding="utf-8-sig").read()


def _turbo_fn():
    s = _src()
    a = s.index("    def _on_hq_all_modality_clicked(self):")
    return s[a:s.index("\n    def ", a + 50)]


# ── the branch that was missing ──────────────────────────────────────────────

def test_turbo_routes_the_correction_tab_to_the_correction_path():
    fn = _turbo_fn()
    assert '_tab == "correction"' in fn, "Turbo has no correction branch"
    assert "self._turbo_correction(" in fn


def test_the_correction_branch_runs_before_the_report_text_is_chosen():
    """It fell through to the `else` branch and used the edit note as a dictation."""
    fn = _turbo_fn()
    assert fn.index('_tab == "correction"') < fn.index("std_text, tr_text = self.composer.get_tab_texts()")


def test_turbo_correction_never_calls_the_report_generator():
    s = _src()
    a = s.index("    def _turbo_correction(")
    body = s[a:s.index("\n    def ", a + 50)]
    assert ".reporter(" not in body, "Turbo correction is still generating a report"
    assert "_send_report_correction(" in body


def test_turbo_correction_reuses_the_existing_sender_rather_than_duplicating_it():
    """The sender already owns the report lookup, both guards, the correction-history
    bookkeeping and the rendering. A second copy would drift from it."""
    s = _src()
    a = s.index("    def _turbo_correction(")
    body = s[a:s.index("\n    def ", a + 50)]
    for owned in ("get_selected_correction_report_text", "_pending_report_kind",
                  "ApiWorker", "_resolve_corrected_msg_id"):
        assert owned not in body, f"{owned} was duplicated into the Turbo handler"


def test_turbo_correction_is_pinned_to_the_company_backend():
    """The llm_backend setting switches Send, not Turbo — the scoping leak that was
    fixed for reports must not reappear on the correction path."""
    s = _src()
    a = s.index("    def _turbo_correction(")
    body = s[a:s.index("\n    def ", a + 50)]
    assert "force_backend=backend" in body
    fn = _turbo_fn()
    assert "backend = TURBO_BACKEND" in fn


# ── the dedicated correction prompt ──────────────────────────────────────────

def test_the_correction_frame_exists_and_is_an_editing_instruction():
    frame = tp.build_turbo_correction_prefix()
    assert frame and "EDIT, DO NOT GENERATE" in frame
    low = frame.lower()
    for rule in ("do not generate a new report from scratch",
                 "do not regenerate normal findings",
                 "complete corrected report"):
        assert rule in low, f"missing: {rule}"


@pytest.mark.parametrize("probe", [
    "measurement", "laterality", "anatomical location", "diagnosis",
    "Impression", "Recommendation",
])
def test_the_frame_protects_what_a_correction_must_not_silently_change(probe):
    assert probe.lower() in tp.build_turbo_correction_prefix().lower()


def test_the_frame_is_a_prefix_and_not_an_override():
    """A correction response is parsed, and the shared correction prompt carries a
    contract that was hard to get right — a mammography report has eleven keys, not
    five. An override that forgot one would return a report the app cannot read."""
    frame = tp.build_turbo_correction_prefix()
    assert "json" not in frame.lower(), "the frame is redefining the output contract"
    assert '"Report Title"' not in frame
    src = io.open(os.path.join(_ROOT, "modules", "EchoMind", "viewer_chat",
                               "turbo_prompt.py"), encoding="utf-8-sig").read()
    assert "PREFIX, not an override" in src


def test_the_kill_switch_reaches_the_correction_frame(monkeypatch):
    monkeypatch.setenv("AIPACS_TURBO_PROMPT", "0")
    assert tp.build_turbo_correction_prefix() is None


# ── the plumbing ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("mod", [cb, ob])
def test_both_backends_accept_the_prefix(mod):
    """`_ai_module` promises the two backends expose the same names AND signatures."""
    assert "system_prompt_prefix" in inspect.signature(mod.correction).parameters


@pytest.mark.parametrize("mod", [cb, ob])
def test_an_empty_prefix_leaves_the_shared_prompt_byte_identical(mod):
    src = io.open(mod.__file__, encoding="utf-8-sig").read()
    assert 'if str(system_prompt_prefix or "").strip() else system_prompt' in src \
        or 'if str(system_prompt_prefix or "").strip() else system_msg' in src


def test_the_sender_passes_the_prefix_through():
    s = _src()
    a = s.index("    def _send_report_correction(")
    body = s[a:s.index("\n    def ", a + 50)]
    assert "system_prompt_prefix=system_prompt_prefix" in body
    assert "force_backend" in body and "turbo" in body


def test_send_correction_is_unchanged_by_default():
    """The Send path must keep today's behaviour: no prefix, no forced backend."""
    s = _src()
    a = s.index("    def _send_report_correction(")
    head = s[a:s.index("):", a)]
    for param, default in (("system_prompt_prefix", '""'), ("force_backend", '""'),
                           ("turbo", "False")):
        assert f"{param}: " in head or f"{param}:" in head, param
        assert default in head


def test_the_observed_failure_is_recorded_where_the_fix_lives():
    s = _src()
    a = s.index("    def _turbo_correction(")
    body = s[a:s.index("\n    def ", a + 50)]
    assert "2026-08-09" in body and "never sent" in body
