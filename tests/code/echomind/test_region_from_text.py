"""Guard: the booking and the dictation decide the region, not DICOM (2026-08-09).

OWNER DECISION, in his words: "Dictation and service are the most reliable."

OBSERVED. Patient 52230, MRI. DICOM carried `BodyPartExamined = ABDOMEN,
ABDOMENPELVIS`, so the gate sent abdomen + pelvis and the model generated a full
pelvic normal survey — urinary bladder, rectum and sigmoid colon, pelvic bones, pelvic
sidewalls and obturator spaces, pelvic cavity, pelvic floor and perineal soft tissues,
sacrum/SI joints/femoral heads. Seven structures asserted as examined and normal.

None of it was dictated. The booking said «MRI ... شکم بدون مواد حاجب» and the
physician opened «ام آر آی از ناحیه شکم به صورت تری فازیک». Both said abdomen.

The two directions are deliberately NOT symmetric:

  * the SERVICE replaces the region set — it is what a human filled in;
  * the DICTATION may only NARROW. Widening is already the prompt's job, and the
    transcript arrives through an STT known to mangle Persian. A narrowing that would
    empty the gate, or that shares nothing with what was booked and scanned, is
    refused and the gate is left alone.
"""

import io
import os
import sys

import pytest

_THIS = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.normpath(os.path.join(_THIS, "..", "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from modules.EchoMind import session_metadata as sm                     # noqa: E402

_PAGES = os.path.join(_ROOT, "modules", "EchoMind", "viewer_chat", "ai_chat_pages.py")

SERVICE_52230 = ("MRI دینامیک هر قسمت بدن بجز قلب / "
                 "MRI (به عنوان مثال proton) شکم بدون مواد حاجب")
DICTATION_52230 = "ام آر آی از ناحیه شکم به صورت تری فازیک شماره ۱ بنویس"


# ── the observed case ────────────────────────────────────────────────────────

def test_the_52230_booking_names_the_abdomen_alone():
    assert sm.detect_regions_from_text(SERVICE_52230) == ("abdomen",)


def test_the_52230_dictation_names_the_abdomen_alone():
    assert sm.detect_regions_from_text(DICTATION_52230) == ("abdomen",)


# ── the vocabulary ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("text,expected", [
    ("سی تی اسکن اسپیرال مغز بدون تزریق", ("brain",)),
    ("MRI شکم و لگن", ("abdomen", "pelvis")),
    ("سی تی اسکن قفسه سینه", ("chest",)),
    ("ام آر آی ستون فقرات کمری", ("spine_lumbar",)),
    ("ام آر آی ستون فقرات گردنی", ("spine_cervical",)),
    ("ام آر آی ستون فقرات", ("spine",)),
    ("رادیوگرافی مچ دست", ("wrist_hand",)),
    ("رادیوگرافی مچ پا", ("ankle_foot",)),
    ("سی تی سینوس های پارانازال", ("paranasal_sinuses",)),
    ("سونوگرافی بارداری", ("obstetric",)),
    ("ماموگرافی دو طرفه", ("breast",)),
    ("سنجش تراکم استخوان", ("bone_density",)),
    ("سونوگرافی تیروئید", ("thyroid",)),
    ("ام آر آی پروستات", ("prostate",)),
    ("MRI knee", ("knee",)),
    ("CT chest", ("chest",)),
])
def test_the_booking_vocabulary(text, expected):
    assert sm.detect_regions_from_text(text) == expected


def test_arabic_script_matches_too():
    assert sm.detect_regions_from_text("سي تي اسكن مغز") == ("brain",)


@pytest.mark.parametrize("text", ["خدمات عمومی", "", None, "   ", "MRI", "proton"])
def test_text_that_names_nothing_yields_nothing(text):
    """A missed region falls back to the wider DICOM set. A guessed one silently
    deletes the correct reporting rules."""
    assert sm.detect_regions_from_text(text) == ()


# ── the traps that make ordered consumption necessary ────────────────────────

def test_a_qualified_phrase_does_not_also_satisfy_the_bare_one():
    """«ستون فقرات گردنی» contains «گردن». Without consuming the match, every
    cervical-spine booking would also gate head_neck."""
    assert sm.detect_regions_from_text("ستون فقرات گردنی") == ("spine_cervical",)


def test_a_region_word_inside_an_ordinary_word_is_not_a_region():
    """«ایران» contains «ران». Short bare words are excluded for exactly this."""
    assert sm.detect_regions_from_text("بیمار از ایران") == ()
    assert sm.detect_regions_from_text("تهران") == ()


def test_the_compound_yields_both_halves():
    assert sm.detect_regions_from_text("ام آر آی شکم و لگن") == ("abdomen", "pelvis")


# ── order follows the text, not the pattern list ─────────────────────────

SERVICE_52057 = "MRI مغز با و بدون ماده حاجب / MRI سرویکال با و بدون ماده حاجب"
DICTATION_52057 = ("ام آر آی مغز کد مغز رو ام‌اس بیار بعد بنویس که دبلیو آیش "
                   "طبیعی باشد بعد مهره‌های گردنی هم داره مهره‌های گردنیش رو "
                   "بنویس که ضایعه ماده سفید در نخاع گردنی مشهود است")


def test_the_order_follows_the_text_not_the_pattern_list():
    """OBSERVED, patient 52057. The booking reads brain first and the physician
    dictated the brain first — «ام آر آی مغز ... بعد مهره‌های گردنیش رو بنویس».
    Detection returned ('spine_cervical', 'brain') anyway, because the spine block is
    listed above the head block in _TEXT_REGION_PATTERNS. Region blocks render in gate
    order, so the report led with the cervical spine under a title that said
    "brain and cervical spine"."""
    assert sm.detect_regions_from_text(SERVICE_52057) == ("brain", "spine_cervical")
    assert sm.detect_regions_from_text(DICTATION_52057) == ("brain", "spine_cervical")


def test_the_reverse_order_is_reported_in_reverse():
    """Proves it reads the text rather than carrying a new hard-coded preference."""
    assert sm.detect_regions_from_text("MRI سرویکال و مغز") == ("spine_cervical", "brain")
    assert sm.detect_regions_from_text("MRI مغز و سرویکال") == ("brain", "spine_cervical")


def test_a_repeated_phrase_does_not_leak_a_third_region():
    """52057 said «مهره‌های گردنی» twice. Claiming only the first occurrence left
    the second for the bare «گردن», which added head_neck to a brain-and-cervical
    study. Every occurrence is claimed."""
    got = sm.detect_regions_from_text(DICTATION_52057)
    assert "head_neck" not in got, got


def test_the_rendered_region_blocks_follow_that_order():
    from modules.EchoMind.viewer_chat import turbo_prompt as tp
    regions = list(sm.detect_regions_from_text(SERVICE_52057))
    got = tp.build_turbo_system_prompt("MRI", "", profile={"regions": regions})
    blocks = [l.strip() for l in got.splitlines() if l.startswith("## ")]
    assert blocks[0] == "## Brain", blocks


def test_sinus_is_not_brain():
    assert sm.detect_regions_from_text("سی تی سینوس") == ("paranasal_sinuses",)


def test_every_emitted_region_is_canonical():
    """A key outside REGION_KEYS can never be gated on, so emitting one is a silent
    fallback to the full prompt."""
    for _pattern, regions in sm._TEXT_REGION_PATTERNS:
        for r in regions:
            assert r in sm.REGION_KEYS, f"{r!r} is not a canonical region key"


def test_the_patterns_are_ordered_specific_first():
    """Any pattern that CONTAINS an earlier one would be unreachable, because the
    earlier match consumes the text first."""
    seen = []
    for pattern, _r in sm._TEXT_REGION_PATTERNS:
        for earlier in seen:
            assert earlier not in pattern, (
                f"{pattern!r} can never match: {earlier!r} is listed before it "
                f"and consumes the text")
        seen.append(pattern)


# ── the booking outranks DICOM ───────────────────────────────────────────────

def test_the_booking_replaces_the_dicom_region_set():
    src = io.open(os.path.join(_ROOT, "modules", "EchoMind", "session_metadata.py"),
                  encoding="utf-8-sig").read()
    body = src[src.index("_region_source = \"dicom\""):src.index('rec["provenance"] = prov')]
    assert "detect_regions_from_text(rec[\"reception\"].get(\"service\"))" in body
    assert '_region_source = "service_text"' in body
    assert "region_text_enabled()" in body


def test_a_booking_that_shares_nothing_with_dicom_keeps_both():
    """No overlap means the booking and the scanner describe different studies. That
    is a data problem, not a refinement — dropping either side would lose real
    coverage on a case nobody has looked at yet."""
    src = io.open(os.path.join(_ROOT, "modules", "EchoMind", "session_metadata.py"),
                  encoding="utf-8-sig").read()
    body = src[src.index("_region_source = \"dicom\""):src.index('rec["provenance"] = prov')]
    assert "keeping the union" in body
    assert "dicom+service_conflict" in body


def test_the_change_is_logged_when_it_changes_something():
    src = io.open(os.path.join(_ROOT, "modules", "EchoMind", "session_metadata.py"),
                  encoding="utf-8-sig").read()
    assert "reception booking \"\n                                \"outranks DICOM" in src \
        or "outranks DICOM" in src


# ── the dictation narrows, and only narrows ──────────────────────────────────

def _profile_fn():
    s = io.open(_PAGES, encoding="utf-8-sig").read()
    a = s.index("    def _build_gate_profile(self")
    return s[a:s.index("\n    def ", a + 50)]


def test_the_profile_builder_accepts_the_transcript():
    assert "def _build_gate_profile(self, transcript" in _profile_fn()


def test_the_call_site_hands_the_transcript_over():
    s = io.open(_PAGES, encoding="utf-8-sig").read()
    assert "self._build_gate_profile(user_msg)" in s


def test_the_dictation_can_only_shrink_the_set():
    fn = _profile_fn()
    assert "if r in regions" in fn, "the spoken regions are not intersected"
    assert "len(spoken) < len(regions)" in fn, "a same-size or larger set must be ignored"


def test_an_empty_narrowing_is_refused():
    """`if spoken and ...` — a dictation naming nothing recognisable leaves the gate
    exactly as the booking set it."""
    assert "if spoken and len(spoken) < len(regions):" in _profile_fn()


def test_the_narrowing_is_logged():
    assert "narrowed by the dictation" in _profile_fn()


def test_the_kill_switch_reaches_both_paths(monkeypatch):
    assert sm.region_text_enabled() is True
    monkeypatch.setenv("AIPACS_REGION_FROM_TEXT", "0")
    assert sm.region_text_enabled() is False
    assert "_meta.region_text_enabled()" in _profile_fn()


def test_the_observed_case_is_recorded_where_the_fix_lives():
    src = io.open(os.path.join(_ROOT, "modules", "EchoMind", "session_metadata.py"),
                  encoding="utf-8-sig").read()
    assert "52230" in src
