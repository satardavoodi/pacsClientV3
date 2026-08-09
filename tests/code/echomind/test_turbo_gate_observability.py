"""Guard: the Turbo log tells the truth about the region gate (2026-08-09).

OBSERVED. Eleven live Turbo runs between 14:41 and 16:46 logged:

    [Turbo] prompt source=turbo len=35754 regions=['abdomen']
    [Turbo] prompt source=turbo len=35754 regions=['pelvis']
    [Turbo] prompt source=turbo len=35754 regions=['brain']
    ...

Every region different and correct; `len` identical every single time. 35754 is the
length of the UNGATED RADIOLOGY prompt — the one built with `profile=None`, carrying
all nineteen X-ray regions. A correctly gated single-region prompt is ~8,000. So the
gate contributed nothing to any of those reports, and every one of them was sent with
every region's rules attached.

The log could not show that, because it called `_build_gate_profile()` a SECOND time
purely to format the message. It printed the regions the run SHOULD have used, never
the ones it did. A dead gate and a live gate produced identical-looking log lines, and
the only reason we noticed was that `len` never varied.

Two things are fixed and guarded here:

  1. the profile is built ONCE and the prompt and the log share that object;
  2. the line reports the ARTIFACT (`ctx=`, a count of rendered region blocks) rather
     than restating the intent. ctx=0 beside a non-empty regions= is the bug above.

`ctx` is only honest while the string it counts is the one the renderer emits, so the
last test here pins those two together across every modality.
"""

import io
import os
import re
import sys

import pytest

_THIS = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.normpath(os.path.join(_THIS, "..", "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from modules.EchoMind.viewer_chat import turbo_prompt as tp                # noqa: E402

_PAGES = os.path.join(_ROOT, "modules", "EchoMind", "viewer_chat", "ai_chat_pages.py")

#: The literal the page counts. Kept here so a rename has to change both places.
MARKER = "# REPORTING CONTEXT"


def _src():
    return io.open(_PAGES, encoding="utf-8-sig").read()


def _work_block():
    """The `work()` closure inside the Turbo report handler."""
    s = _src()
    a = s.index("    def _on_hq_all_modality_clicked(self):")
    fn = s[a:s.index("\n    def ", a + 50)]
    b = fn.index("        def work():")
    return fn[b:fn.index("return _ai_module(backend).reporter(", b)]


# ── the profile is built once, and it is the one that gets logged ────────────

def test_the_gate_profile_is_built_exactly_once():
    """Two calls is how the log came loose from the prompt in the first place."""
    assert _work_block().count("self._build_gate_profile(") == 1


def test_the_prompt_and_the_log_share_that_one_profile():
    """2026-08-09: the call gained a `user_msg` argument when the dictation was
    allowed to narrow the gate. What matters here is unchanged — ONE call, and the
    object it returns is both passed to the builder and reported in the log."""
    w = _work_block()
    assert "_gate = self._build_gate_profile(user_msg)" in w
    assert "profile=_gate," in w
    assert '(_gate or {}).get("regions")' in w
    assert "(self._build_gate_profile(" not in w.replace("_gate = self._build_gate_profile(", ""), \
        "the log is rebuilding the profile again — that is the original bug"


# ── the line reports the artifact ────────────────────────────────────────────

def test_the_log_carries_the_context_indicator():
    w = _work_block()
    assert "[Turbo] prompt source=%s len=%s ctx=%d regions=%s" in w
    assert f'_turbo_sys.count("{MARKER}")' in w


def test_the_indicator_is_counted_from_the_prompt_that_was_actually_sent():
    w = _work_block()
    assert "_ctx = _turbo_sys.count(" in w
    # ...and it is the same object handed to reporter() as the override.
    assert "system_prompt_override=_turbo_sys" in _src()


def test_the_observed_failure_is_recorded_where_the_fix_lives():
    w = _work_block()
    assert "35754" in w and "2026-08-09" in w


# ── the indicator has to MEAN something ──────────────────────────────────────
# Everything above is source-reading. These are the ones that keep `ctx` honest:
# if the renderer's heading is ever renamed, `ctx` silently becomes always-0 and
# a dead gate would once again look exactly like a live one.

_GATED = [
    ("CT", "brain"),
    ("MRI", "brain"),
    ("RADIOLOGY", "brain"),
    ("SONOGRAPHY", "abdomen"),
    ("MAMOGRAPHY", "breast"),
]


@pytest.mark.parametrize("modality,region", _GATED)
def test_a_gated_prompt_renders_at_least_one_context_block(modality, region):
    got = tp.build_turbo_system_prompt(modality, "", profile={"regions": [region]})
    assert got, f"{modality}: no prompt at all"
    assert got.count(MARKER) >= 1, \
        f"{modality}/{region}: the gate rendered but {MARKER!r} is absent — ctx= is now a lie"


@pytest.mark.parametrize("modality,region", _GATED)
def test_an_ungated_prompt_renders_none(modality, region):
    """ctx=0 must be reachable, or the indicator can never report the failure."""
    got = tp.build_turbo_system_prompt(modality, "", profile=None)
    assert got, f"{modality}: no prompt at all"
    assert got.count(MARKER) == 0, \
        f"{modality}: the ungated prompt contains {MARKER!r} — ctx= can no longer detect a dead gate"


@pytest.mark.parametrize("modality,region",
                         [p for p in _GATED if p[0] != "MAMOGRAPHY"])
def test_gating_actually_shortens_the_prompt(modality, region):
    """The symptom that gave the bug away. Worth asserting directly.

    Mammography is excluded because it is a different architecture, not an exception
    to this one: its schema is regex-locked, so its gate contributes a PREFIX to the
    shared prompt instead of replacing it with a narrowed template. It legitimately
    gets LONGER, and `test_mammography_gains_coverage_not_brevity` below asserts that
    rather than this rule being loosened to cover both.
    """
    gated = tp.build_turbo_system_prompt(modality, "", profile={"regions": [region]})
    whole = tp.build_turbo_system_prompt(modality, "", profile=None)
    assert len(gated) < len(whole), \
        f"{modality}/{region}: gated ({len(gated)}) is not shorter than ungated ({len(whole)})"


def test_mammography_gains_coverage_not_brevity():
    """The prefix architecture's own trade, asserted where the shortening rule would
    otherwise be quietly weakened to accommodate it."""
    gated = tp.build_turbo_system_prompt("MAMOGRAPHY", "", profile={"regions": ["breast"]})
    whole = tp.build_turbo_system_prompt("MAMOGRAPHY", "", profile=None)
    assert len(gated) > len(whole), "mammography's prefix stopped being additive"
    # ...and `ctx=` still reports it honestly, which is all this file claims.
    assert gated.count(MARKER) == 1 and whole.count(MARKER) == 0


def test_the_marker_the_page_counts_is_the_marker_these_tests_check():
    """Pins the string in ai_chat_pages.py to MARKER above — no silent drift."""
    m = re.search(r'_ctx = _turbo_sys\.count\("([^"]+)"\)', _src())
    assert m, "the ctx= count is gone from the Turbo handler"
    assert m.group(1) == MARKER, (
        f"the page counts {m.group(1)!r} but these tests validate {MARKER!r}")


def test_the_full_production_profile_shape_still_gates():
    """`_build_gate_profile` returns seven keys, not just `regions`. The narrowing was
    only ever verified with the short shape."""
    full = {
        "regions": ["spine_thoracic"],
        "contrast": "", "procedure": "", "subtype": "",
        "patient": "", "service": "", "protocol": "",
    }
    gated = tp.build_turbo_system_prompt("RADIOLOGY", "", profile=full)
    whole = tp.build_turbo_system_prompt("RADIOLOGY", "", profile=None)
    assert gated.count(MARKER) >= 1 and len(gated) < len(whole)
