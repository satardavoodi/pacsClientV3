"""Guard: ONE modality list, Turbo diagnostics on the logger, no typist metaphor
(2026-08-06).

**The modality list is load-bearing.** The string the physician picks routes
`build_report_system_prompt` to a modality branch; a value with no matching
branch falls through to the GENERIC prompt and the study silently loses its
modality-specific reporting rules. It used to exist as THREE independent copies
(the report-send menu, the modality button menu, and the composer widget) — so a
future edit could desynchronise the entry points. One constant now.

**Audit finding recorded here as a test, not just a comment:** every value in
`REPORT_MODALITIES` must actually reach a real modality branch. This is what
caught that the dedicated OBSTETRIC branch is unreachable from this UI.

**Turbo diagnostics** were `print()`, so a Turbo run left nothing in app.log —
verifying the live run meant inferring the backend from the HTTP line plus the
token-usage record. They are logger calls now.

**"emulating a typist"** was removed from the X-ray Objective: a typist
transcribes, it does not reorganize findings into anatomical sections, so it
directly contradicted the REPORT ORGANIZATION rule.
"""

import ast
import os
import re
import typing

import pytest

_THIS = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.normpath(os.path.join(_THIS, "..", "..", ".."))


def _read(rel):
    with open(os.path.join(_ROOT, rel), encoding="utf-8") as fh:
        return fh.read()


_CONFIG = "modules/EchoMind/ai_chat_config.py"
_SHIM = "modules/EchoMind/viewer_chat/ai_chat_config.py"
_PAGES = "modules/EchoMind/viewer_chat/ai_chat_pages.py"
_WIDGETS = "modules/EchoMind/viewer_chat/ai_chat_widgets.py"
_REPORTER = "modules/EchoMind/viewer_chat/openai_reporter.py"

_HARDCODED = '["CT", "MRI", "SONOGRAPHY", "RADIOLOGY", "MAMOGRAPHY"]'


# ── one list ─────────────────────────────────────────────────────────────────

def test_the_constant_holds_the_offered_modalities():
    """The de-duplication itself must not have changed any value. The ONE
    deliberate change since is the obstetric entry the owner asked for
    (2026-08-06), which activates the dedicated ISUOG branch."""
    offered = _offered_modalities()
    assert offered == ["CT", "MRI", "SONOGRAPHY", "OBSTETRIC ULTRASOUND",
                       "RADIOLOGY", "MAMOGRAPHY"]
    # the five originals are all still present and unrenamed
    for original in ["CT", "MRI", "SONOGRAPHY", "RADIOLOGY", "MAMOGRAPHY"]:
        assert original in offered


def test_the_shim_reexports_it():
    assert "REPORT_MODALITIES," in _read(_SHIM), "viewer_chat imports go through the shim"


@pytest.mark.parametrize("rel", [_PAGES, _WIDGETS])
def test_no_module_keeps_its_own_copy(rel):
    src = _read(rel)
    live = [ln for ln in src.split("\n")
            if _HARDCODED in ln and not ln.lstrip().startswith("#")]
    assert not live, f"{rel}: a duplicate modality list came back: {live[:2]}"
    assert "REPORT_MODALITIES" in src, f"{rel}: must use the shared constant"


def test_all_three_use_sites_are_wired():
    src = _read(_PAGES)
    assert "modalities = list(REPORT_MODALITIES)" in src, "report-send menu"
    assert "for mod in REPORT_MODALITIES:" in src, "modality-button menu"
    assert "REPORT_MODALITIES" in _read(_WIDGETS), "composer widget"


# ── every offered modality must reach a real branch ──────────────────────────

def _prompt_fn():
    src = _read(_REPORTER)
    lines = src.split("\n")
    node = next(n for n in ast.parse(src).body
                if isinstance(n, ast.FunctionDef) and n.name == "build_report_system_prompt")
    body = "\n".join(lines[node.lineno - 1:node.end_lineno])
    ns = {"_to_str": lambda x: "" if x is None else str(x),
          "Optional": typing.Optional, "Dict": dict, "Any": object}
    exec(compile(body, _REPORTER, "exec"), ns)
    return ns["build_report_system_prompt"]


def _offered_modalities():
    src = _read(_CONFIG)
    m = re.search(r"REPORT_MODALITIES = (\[[^\]]*\])", src)
    return ast.literal_eval(m.group(1))


@pytest.mark.parametrize("modality", _offered_modalities())
def test_every_offered_modality_hits_a_real_branch(modality):
    """A value with no branch falls through to the GENERIC prompt — the study
    silently loses its modality rules. The generic fallback is much shorter and
    carries no modality-specific block, so length + a marker separate them."""
    prompt = _prompt_fn()
    sp = prompt(modality, "")
    generic = prompt("NoSuchModalityValue", "")
    assert sp != generic, f"{modality!r} falls through to the GENERIC prompt"
    assert len(sp) > len(generic), f"{modality!r} did not reach a modality branch"
    # and it carries the shared organization work
    assert "REPORT ORGANIZATION — group" in sp


def test_obstetric_is_now_an_offered_modality():
    """SUPERSEDED 2026-08-06 (same day): this previously pinned that the
    obstetric branch was DORMANT — present in `openai_reporter` but unreachable
    because no offered modality value routed to it. The owner then added it, so
    the guard flips to the opposite invariant: obstetric must now be offered AND
    must reach its dedicated ISUOG branch, not the sonography one."""
    assert "OBSTETRIC ULTRASOUND" in _offered_modalities()
    prompt = _prompt_fn()
    ob = prompt("OBSTETRIC ULTRASOUND", "")
    assert "JSON OUTPUT SCHEMA (ISUOG — STRICT)" in ob, "must reach the ISUOG branch"
    assert "REPORT ORGANIZATION (OBSTETRIC)" in ob
    assert ob != prompt("SONOGRAPHY", ""), "obstetric must NOT fall back to sonography"


def test_obstetric_validation_and_clamp_apply():
    """The obstetric aliases must stay in `_VALIDATED_MODALITIES`, or an
    obstetric report loses its temperature clamp and its output validation."""
    rep = _read("modules/EchoMind/viewer_chat/openai_reporter.py")
    assert '"obstetric ultrasound"' in rep
    assert "_OB_ULTRASOUND_REQUIRED_KEYS" in rep
    for key in ["Gestational Age & Dating", "Biometry", "Amniotic Fluid"]:
        assert key in rep, f"obstetric required key missing: {key}"


# ── Turbo diagnostics reach the log ──────────────────────────────────────────

def test_turbo_diagnostics_are_logged_not_printed():
    src = _read(_PAGES)
    assert not re.findall(r'print\(\s*f?"\[Turbo\]', src), "[Turbo] print() must not come back"
    # Scoped to the BLOCKED paths (2026-08-08). This counted every `[Turbo]` warning,
    # so adding a legitimate one — the own-prompt fallback — failed a guard about
    # something else entirely. A count-based guard that trips on correct additions
    # teaches the next person to delete it instead of reading it.
    # 2026-08-09: the count became a reason, per this block's own warning above. The
    # entitlement rework split "no company key" into two distinct refusals — not
    # entitled, and entitled but no centre key resolved — and the magic 3 failed on a
    # correct addition for the second time. Assert the PROPERTY instead: every blocked
    # path warns, and the named ones are all present.
    # Capture to the closing quote, not a character class — the reasons contain a
    # hyphen ("company-entitled") and an underscore ("page_mode"), and a tidy-looking
    # [a-z ]+ silently truncates both.
    blocked = re.findall(r'_log\.warning\("\[Turbo\] blocked: ([^"]+)"', src)
    assert len(blocked) >= 3, f"blocked paths must warn; found {blocked}"
    for reason in ("page_mode", "modality not selected"):
        assert any(reason in b for b in blocked), f"no warning for: {reason}"
    assert any("entitled" in b for b in blocked), \
        "the licensing refusal must be logged like the others"
    assert 'print("[Turbo] blocked' not in src
    assert '"[Turbo] sending backend=%s model=%s' in src, "the send path must log backend AND model"


def test_turbo_send_log_names_the_pinned_model():
    """Verifying the live run required reading the token-usage file to learn the
    model. The log line carries it now."""
    src = _read(_PAGES)
    i = src.index('"[Turbo] sending backend=%s model=%s')
    assert "company_direct.PRIMARY_REPORT_MODEL" in src[i:i + 400]


# ── the typist metaphor is gone ──────────────────────────────────────────────

def test_typist_metaphor_removed():
    src = _read(_REPORTER)
    assert "emulating a typist" not in src, (
        "a typist transcribes; it does not reorganize findings — this contradicted "
        "the REPORT ORGANIZATION rule"
    )


def test_the_objective_intent_is_preserved():
    prompt = _prompt_fn()
    xr = prompt("RADIOLOGY", "")
    assert "Transcribe and translate radiologic reports into English" in xr
    assert "formal, professional radiological register" in xr
    assert "REPORT ORGANIZATION — group" in xr


def test_only_the_xray_prompt_changed(monkeypatch):
    """The typist line lived only in the radiography branch."""
    prompt = _prompt_fn()
    for m in ["CT", "MRI", "SONOGRAPHY", "MAMOGRAPHY"]:
        assert "typist" not in prompt(m, "")
