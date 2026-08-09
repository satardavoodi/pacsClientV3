"""Guard: CT is complete for Turbo — the gaps are filled and the gate is actually wired.

Two things landed together and each has a failure mode worth pinning.

THE NEW REGIONS. Measured against the 1405 tariff, three CT regions had real bookable
volume and no block at all: temporal bone (11 service codes), orbit (9), maxillofacial /
dental / TMJ (8). A temporal bone CT was being sent nineteen region blocks, none of which
described a temporal bone. The authored blocks live in `turbo_regions_extra.py`, apart
from the generated library, so regenerating one can never clobber the other.

THE WIRING. Until now nothing built a profile, so Turbo still sent the full prompt in
production — the machinery was proven and idle. `_build_gate_profile` reads the chat's
own metadata, which means the gate acts on exactly what the physician can see and
correct on the card.
"""

import ast
import io
import os
import sys

import pytest

_THIS = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.normpath(os.path.join(_THIS, "..", "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

_PAGES = os.path.join(_ROOT, "modules", "EchoMind", "viewer_chat", "ai_chat_pages.py")

from modules.EchoMind.session_metadata import REGION_KEYS, normalize_region  # noqa: E402
from modules.EchoMind.viewer_chat import turbo_prompt as tp                  # noqa: E402
from modules.EchoMind.viewer_chat import turbo_regions as tr                 # noqa: E402
from modules.EchoMind.viewer_chat import turbo_regions_extra as tx           # noqa: E402

@pytest.fixture(autouse=True)
def _v2_off(monkeypatch):
    """This file tests the NARROWING path, which only runs when the template is off.

    The template became the default on 2026-08-09; before that these tests got the
    narrowing path for free. Pinning it here keeps them testing what they were written
    to test, rather than silently becoming template tests.
    """
    monkeypatch.setenv("AIPACS_TURBO_PROMPT_V2", "0")

NEW = ("temporal_bone", "orbit", "dental_maxillofacial")


def _read(p):
    with io.open(p, encoding="utf-8-sig") as fh:
        return fh.read()


def _fn_src(path, name):
    src = _read(path)
    lines = src.split("\n")
    node = next(n for n in ast.walk(ast.parse(src))
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                and n.name == name)
    return "\n".join(lines[node.lineno - 1:node.end_lineno])


# ── 1. the new regions are real, reachable and detectable ────────────────────

def test_the_new_region_keys_are_canonical():
    """A key outside REGION_KEYS can never be detected, so its block would be dead
    content that still looks present."""
    for k in NEW:
        assert k in REGION_KEYS, f"{k!r} is not a canonical region key"
    for k in tx.EXTRA_REGION_TO_BLOCKS:
        assert k in REGION_KEYS


def test_dicom_tags_reach_the_new_regions():
    for tag, want in (("IAC", "temporal_bone"), ("MASTOID", "temporal_bone"),
                      ("PETROUS", "temporal_bone"), ("ORBIT", "orbit"),
                      ("EYE", "orbit"), ("TMJ", "dental_maxillofacial"),
                      ("MANDIBLE", "dental_maxillofacial"),
                      ("MAXILLA", "dental_maxillofacial")):
        assert want in normalize_region(tag), f"DICOM {tag} does not reach {want}"


def test_every_authored_block_is_reachable():
    reachable = {b for v in tx.EXTRA_REGION_TO_BLOCKS.values() for b in v}
    orphans = [n for n, _t in tx.CT_EXTRA_BLOCKS if n not in reachable]
    assert not orphans, f"unreachable authored blocks: {orphans}"


def test_authored_and_generated_libraries_stay_separate():
    """`turbo_regions.py` is machine-generated and must never be hand-edited; the
    authored blocks must never be inside it, or regeneration deletes clinical content."""
    generated = {n for n, _t in tr.CT_BLOCKS}
    for n, _t in tx.CT_EXTRA_BLOCKS:
        assert n not in generated, f"{n} is in the GENERATED library — it will be lost"
    assert "CT_EXTRA_BLOCKS" not in _read(
        os.path.join(_ROOT, "modules", "EchoMind", "viewer_chat", "turbo_regions.py"))


def test_authored_blocks_match_the_prompt_outline_exactly():
    """24 spaces before the heading, 28 before each bullet. Wrong indentation reads as
    a different level of the prompt's outline."""
    for name, text in tx.CT_EXTRA_BLOCKS:
        lines = [ln for ln in text.split("\n") if ln.strip()]
        head = lines[0]
        assert head.startswith(" " * 24 + "– "), f"{name}: bad heading indent"
        assert not head.startswith(" " * 25), f"{name}: heading over-indented"
        assert head.rstrip().endswith(":"), f"{name}: heading must end with a colon"
        for ln in lines[1:]:
            assert ln.startswith(" " * 28 + "• "), f"{name}: bad bullet indent: {ln[:40]!r}"
        assert text.endswith("\n\n"), f"{name}: must end with one blank line"


def test_authored_blocks_have_real_content():
    """Depth, and the house convention for naming the structure a line is about.

    MEASURED against the nineteen generated blocks: 123 of 163 bullets (75%) carry a
    `Structure: findings` label, and the rest are legitimate summary negatives like
    "No pneumoperitoneum or intraperitoneal free fluid." An every-bullet rule would be
    stricter than the content a radiologist actually wrote, so the floor is the
    convention, not perfection. The authored blocks sit at 92%.
    """
    for name, text in tx.CT_EXTRA_BLOCKS:
        bullets = [ln.strip() for ln in text.split("\n") if ln.strip().startswith("•")]
        assert len(bullets) >= 8, f"{name} has only {len(bullets)} structures"
        named = [b for b in bullets if ":" in b]
        assert len(named) / len(bullets) >= 0.70, (
            f"{name}: only {len(named)}/{len(bullets)} bullets name the structure they "
            "describe; the generated blocks average 75%"
        )


def test_the_new_regions_reach_the_prompt():
    for region, marker, probe in (
            ("temporal_bone", "– TEMPORAL BONE CT:", "Ossicular chain"),
            ("orbit", "– ORBIT CT:", "Optic nerve"),
            ("dental_maxillofacial", "– MAXILLOFACIAL AND DENTAL CT:", "Temporomandibular")):
        got = tp.build_turbo_system_prompt("CT", "", profile={"regions": [region]})
        assert marker in got, f"{region} did not reach the prompt"
        assert probe in got
        assert "ABDOMEN CT" not in got, f"{region} still carries the abdomen block"
        assert "OUTPUT FORMAT (STRICT)" in got


def test_a_new_region_still_narrows():
    base = tp.build_turbo_system_prompt("CT", "")
    got = tp.build_turbo_system_prompt("CT", "", profile={"regions": ["temporal_bone"]})
    assert len(got) < len(base) * 0.75


def test_the_tariff_supported_ct_regions_are_all_covered():
    """Measured from the 117 CT service codes in the 1405 catalogue. If a region on
    this list has no mapping, studies booked under those codes get no guidance."""
    tariff_ct_regions = [
        "abdomen", "brain", "temporal_bone", "head_neck", "chest", "orbit",
        "extremity", "dental_maxillofacial", "pelvis", "paranasal_sinuses",
        "spine_thoracic", "spine", "spine_cervical", "spine_lumbar",
    ]
    mapped = set(tr.REGION_TO_BLOCKS) | set(tx.EXTRA_REGION_TO_BLOCKS)
    missing = [r for r in tariff_ct_regions if r not in mapped]
    assert not missing, f"CT regions with tariff volume and no block: {missing}"


# ── 2. the gate is actually wired ────────────────────────────────────────────

def test_the_turbo_call_site_passes_a_profile():
    """Without this the whole library is idle and Turbo sends the full prompt.

    2026-08-09: the profile is now built ONCE into `_gate` and that object is both
    passed to the builder and reported in the log line. It used to be an inline
    `profile=self._build_gate_profile()` with a SECOND independent call formatting
    the log, which is how a dead gate managed to log healthy-looking regions for a
    whole afternoon. The assertion moved with the code; the requirement did not.
    """
    turbo = _fn_src(_PAGES, "_on_hq_all_modality_clicked")
    assert "_gate = self._build_gate_profile(user_msg)" in turbo, \
        "Turbo no longer builds a gate profile"
    assert "profile=_gate," in turbo, \
        "the gate profile is built but never handed to the prompt builder"
    assert turbo.count("self._build_gate_profile(") == 1, \
        "built more than once — the prompt and the log can disagree again"
    # 2026-08-09: the transcript reaches the profile so the dictation can narrow the
    # region set. Passing it is the whole mechanism; a bare call silently disables it.
    assert "self._build_gate_profile()" not in turbo, \
        "the transcript is no longer reaching the gate — dictation narrowing is dead"


def test_the_profile_comes_from_the_chat_metadata():
    """It must read the same record the metadata card shows, so a physician's
    correction to the region is what the gate acts on."""
    body = _fn_src(_PAGES, "_build_gate_profile")
    assert "session_metadata" in body
    assert "current_session_id" in body
    assert '"regions"' in body or "'regions'" in body


def test_the_profile_builder_is_swallowed_and_defaults_to_none():
    body = _fn_src(_PAGES, "_build_gate_profile")
    assert "try:" in body and "except Exception" in body
    assert body.count("return None") >= 3, (
        "no chat, no record and no regions must each return None — which the prompt "
        "builder reads as 'send the full prompt'"
    )


def test_the_send_path_still_passes_no_profile():
    send = _fn_src(_PAGES, "_on_send_chatgpt")
    assert "_build_gate_profile" not in send
    assert "system_prompt_override" not in send


def test_the_gate_decision_is_logged():
    """A narrowed prompt that produces a bad report has to be traceable to the regions
    it narrowed on."""
    turbo = _fn_src(_PAGES, "_on_hq_all_modality_clicked")
    assert "regions=%s" in turbo


# ── 3. nothing about the safety posture changed ──────────────────────────────

@pytest.mark.parametrize("profile", [
    None, {}, {"regions": []}, {"regions": ["not_a_region"]},
])
def test_uncertainty_still_sends_everything(profile):
    base = tp.build_turbo_system_prompt("CT", "")
    assert tp.build_turbo_system_prompt("CT", "", profile=profile) == base


def test_the_reassembly_proof_survived_the_additions():
    """Adding authored blocks must not disturb the generated library's byte-for-byte
    correspondence with the live prompt."""
    base = tp.build_turbo_system_prompt("CT", "")
    a, b = tp._locate_ct_section(base)
    assert base[a:b] == tr.full_section()
