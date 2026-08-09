"""Guard: the study-type gate is actually wired (2026-08-09).

OBSERVED. Patient 53626, a hysterosalpingogram booked «رادیوگرافی هیستروسالپنگوگرافی»,
came back with the plain abdominal radiograph normal template — "Bowel gas pattern is
nonobstructive", "No gross free intraperitoneal air", "Visualised renal, hepatic and
splenic outlines". Nothing about the uterine cavity, the tubes, or peritoneal spill.

`XR_SUBTYPE_PACKAGES['xr_hsg']` had existed since the radiography library was written.
It had never been sent once. `_build_gate_profile` reads `case.subtype`; nothing wrote
it — `session_metadata.py` contained zero occurrences of the word. All 27 study-type
packages (18 radiography, 9 obstetric) were unreachable: built, tested, mirrored, dead.

Exactly the shape of the region-gate failure earlier the same day — a field the prompt
builder consumes that no producer fills, falling back to something plausible-looking.

The counting test below is the one that matters: it fails the moment a package is
added without a way to select it, so this cannot silently happen again.
"""

import os
import sys

import pytest

_THIS = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.normpath(os.path.join(_THIS, "..", "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from modules.EchoMind import session_metadata as sm                     # noqa: E402
from modules.EchoMind.viewer_chat import turbo_modules as tm            # noqa: E402
from modules.EchoMind.viewer_chat import turbo_prompt as tp             # noqa: E402

SERVICE_53626 = "رادیوگرافی هیستروسالپنگوگرافی"


def _package_keys():
    keys = set()
    for mod in ("RADIOLOGY", "SONOGRAPHY"):
        keys |= set(tm.known_subtypes(mod))
    return keys


# ── the observed case ────────────────────────────────────────────────────────

def test_the_53626_booking_selects_hysterosalpingography():
    assert sm.detect_subtypes_from_text(SERVICE_53626) == ("xr_hsg",)


def test_the_package_reaches_the_rendered_prompt():
    """It never had. This is the whole bug."""
    got = tp.build_turbo_system_prompt(
        "RADIOLOGY", "", profile={"regions": ["abdomen"], "subtype": ["xr_hsg"]})
    assert "# STUDY TYPE" in got
    assert "## Hysterosalpingography" in got
    assert "uterine cavity contour" in got


def test_something_populates_case_subtype_at_all():
    """The single line whose absence made 27 packages dead."""
    src = open(os.path.join(_ROOT, "modules", "EchoMind", "session_metadata.py"),
               encoding="utf-8-sig").read()
    assert 'rec["case"]["subtype"]' in src, "nothing writes case.subtype"
    assert "detect_subtypes_from_text(rec[\"reception\"].get(\"service\"))" in src


# ── the invariant that stops it recurring ────────────────────────────────────

def test_every_package_is_selectable():
    """A study-type package with no way to name it can never be sent. This is the
    test that would have caught the original bug on the day it was written."""
    reachable = {k for _p, k in sm._TEXT_SUBTYPE_PATTERNS}
    missing = sorted(_package_keys() - reachable)
    assert not missing, f"packages that can never be selected: {missing}"


def test_every_pattern_points_at_a_real_package():
    reachable = {k for _p, k in sm._TEXT_SUBTYPE_PATTERNS}
    extra = sorted(reachable - _package_keys())
    assert not extra, f"patterns selecting nothing: {extra}"


def test_no_pattern_is_shadowed():
    """Same claimed-span matching as the regions, so a pattern containing an earlier
    one is unreachable — 'cystourethrograph' sat behind 'urethrograph'."""
    pats = [p for p, _k in sm._TEXT_SUBTYPE_PATTERNS]
    for j, later in enumerate(pats):
        for earlier in pats[:j]:
            assert earlier not in later, (
                f"{later!r} can never match: {earlier!r} is listed before it")


# ── the vocabulary ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("text,expected", [
    ("رادیوگرافی هیستروسالپنگوگرافی", ("xr_hsg",)),
    ("HSG", ("xr_hsg",)),
    ("IVP", ("xr_ivp",)),
    ("اوروگرافی ترشحی", ("xr_ivp",)),
    ("باریم انما", ("xr_barium_enema",)),
    ("بلع باریم", ("xr_barium_swallow",)),
    ("ترانزیت کولون", ("xr_colon_transit",)),
    ("فیستولوگرافی", ("xr_fistulography",)),
    ("سن استخوانی", ("xr_bone_age",)),
    ("سروی اسکلتی", ("xr_skeletal_survey",)),
    ("سونوگرافی آنومالی", ("ob_anomaly",)),
    ("بیوفیزیکال پروفایل", ("ob_bpp",)),
    ("حاملگی خارج رحمی", ("ob_ectopic",)),
])
def test_the_booking_vocabulary(text, expected):
    assert sm.detect_subtypes_from_text(text) == expected


@pytest.mark.parametrize("text", [
    "رادیوگرافی قفسه سینه", "سی تی اسکن مغز", "MRI knee", "", None, "   ",
])
def test_an_ordinary_study_selects_no_type(text):
    """Most studies have no subtype and must render no STUDY TYPE block."""
    assert sm.detect_subtypes_from_text(text) == ()


def test_arabic_script_matches():
    assert sm.detect_subtypes_from_text("راديوگرافي هيستروسالپنگوگرافي") == ("xr_hsg",)


def test_a_wrong_modality_drops_the_selection_harmlessly():
    """Detection runs at seed time, when the modality may still be UNKNOWN.
    `subtypes_for` filters, so a stray key costs nothing."""
    got = tp.build_turbo_system_prompt(
        "CT", "", profile={"regions": ["abdomen"], "subtype": ["xr_hsg"]})
    assert "# STUDY TYPE" not in got


def test_the_kill_switch_covers_it(monkeypatch):
    monkeypatch.setenv("AIPACS_REGION_FROM_TEXT", "0")
    assert sm.region_text_enabled() is False
    src = open(os.path.join(_ROOT, "modules", "EchoMind", "session_metadata.py"),
               encoding="utf-8-sig").read()
    seg = src[src.index("# ── study type (2026-08-09)"):src.index("# ── contrast (2026-08-09)")]
    assert "region_text_enabled()" in seg


def test_the_observed_case_is_recorded_where_the_fix_lives():
    src = open(os.path.join(_ROOT, "modules", "EchoMind", "session_metadata.py"),
               encoding="utf-8-sig").read()
    assert "53626" in src


# ── the gap this patch does NOT close ────────────────────────────────────────

def test_the_subtype_renderer_still_has_no_normal_findings():
    """Recorded deliberately, so nobody reads the fix above as complete.

    `render_subtype_context` emits technique / must_report / pathology only. A NORMAL
    hysterosalpingogram therefore still takes its normal findings from the REGION
    block — bowel gas pattern, free intraperitoneal air, organ outlines — which is a
    plain abdominal film, not an HSG. Closing that means authoring a normal-findings
    reference for each study type, which is clinical content and needs review.

    When that lands, this test should be replaced by one asserting the opposite.
    """
    from modules.EchoMind.viewer_chat import turbo_template as tt
    src = tt.render_subtype_context.__doc__ or ""
    body = open(os.path.join(_ROOT, "modules", "EchoMind", "viewer_chat",
                             "turbo_template.py"), encoding="utf-8-sig").read()
    seg = body[body.index("def render_subtype_context"):body.index("def render(*")]
    assert '"normal"' not in seg and "'normal'" not in seg, (
        "render_subtype_context now renders normals — update this guard and the "
        "docs, the HSG gap is closed")
