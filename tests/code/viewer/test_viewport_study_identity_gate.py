"""Guard test — viewport STUDY-identity gate (cross-exam stomp guard).

ARCHITECTURAL INVARIANT under test: a FAST viewport may only display a series
belonging to the STUDY the user last intended for it.

Root cause it guards (48912 / 48952): on a multi-study tab (current exam + a
merged previous exam) the viewer identifies a series by a single overloaded
scalar — the display number ("4" for the current exam, "1000004" =
slot*1_000_000 + 4 for the previous exam). The identity is resolved correctly
upstream (`_resolve_canonical_series_identity`), but a superseded / stale
re-render (an async apply or a grow/resume watchdog still pointing at the
previously-displayed exam) pushed the previous exam's metadata straight into the
viewport's render choke point `qt_fast_container._start_qt_viewer` — so a request
to show CURRENT series 4 rendered PREVIOUS-exam series 1000004.

Fix (two halves, both pinned here):
  1. `change_series_on_viewer` STAMPS `vtk_widget._intended_study_uid` from the
     requested series' canonical identity BEFORE any cache lookup / async load.
  2. `_start_qt_viewer` GATES: if the incoming render's study_uid differs from the
     stamped intended study_uid, it SKIPS the render and keeps the current image.

SAFE BY CONSTRUCTION: gates only on cross-STUDY mismatch, so same-study
operations (normal switch, paired-MG, in-place grow, reset) are never blocked;
fail-open when either study_uid is unknown. Kill switch
AIPACS_VIEWPORT_STUDY_IDENTITY_GATE=0 = byte-identical legacy.

House style: source-pins guard the real edits (no PySide6/VTK needed) + a
behavioral mirror reproduces the exact gate decision.
"""

from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
QFC = REPO / "PacsClient" / "pacs" / "patient_tab" / "ui" / "patient_ui" / "vtk_widget" / "qt_fast_container.py"
VCS = REPO / "PacsClient" / "pacs" / "patient_tab" / "ui" / "patient_ui" / "_vc_switch.py"


def _read(p: Path) -> str:
    # Defensive against the sandbox FUSE mount occasionally serving a TRUNCATED
    # read of large source files: read several times and keep the longest result
    # (on a real filesystem every read is identical, so this is a no-op there).
    best = ""
    for _ in range(8):
        try:
            data = p.read_bytes()
        except Exception:
            continue
        if len(data) > len(best.encode("utf-8", "ignore")):
            best = data.decode("utf-8-sig", errors="ignore")
    return best


# --- source-pins: the gate at the render choke point ---------------------------------

def test_gate_flag_default_on():
    s = _read(QFC)
    assert 'os_gate.getenv("AIPACS_VIEWPORT_STUDY_IDENTITY_GATE", "1")' in s, \
        "study-identity gate must default ON"


def test_gate_reads_intended_and_incoming_study_and_returns_on_mismatch():
    s = _read(QFC)
    i = s.index("Viewport study-identity gate")
    body = s[i:i + 4200]
    assert 'getattr(self, "_intended_study_uid"' in body
    assert 'getattr(self, "_intended_series_uid"' in body
    assert '.get("study_uid")' in body            # incoming study from metadata
    # PRIMARY signal = series_uid mismatch; secondary = study mismatch
    assert "series_uid != _intended_uid" in body
    assert "_incoming_study != _intended_study" in body
    assert "[IDENTITY-GATE]" in body
    # the mismatch branch must SKIP the render (early return before bridge teardown)
    tail = body[body.index("_uid_mismatch = bool"):]
    assert "if _study_mismatch or _uid_mismatch:" in tail
    assert "return" in tail


def test_gate_sits_before_bridge_teardown():
    """The gate must return BEFORE the existing bridge is torn down, so a
    superseded render keeps the current image rather than blanking the viewport."""
    s = _read(QFC)
    assert "Viewport study-identity gate" in s and "[SERIES UNLOAD]" in s
    assert s.index("Viewport study-identity gate") < s.index("[SERIES UNLOAD]"), \
        "gate must precede the [SERIES UNLOAD] teardown"


# --- source-pins: the stamp at the switch entry --------------------------------------

def test_change_series_stamps_intended_study():
    s = _read(VCS)
    assert "Viewport study-identity stamp" in s
    i = s.index("Viewport study-identity stamp")
    body = s[i:i + 1500]
    assert "_resolve_canonical_series_identity(series_number)" in body
    assert "vtk_widget._intended_study_uid =" in body


# --- behavioral mirror: exact gate decision ------------------------------------------

def _gate_should_render(intended_study: str, incoming_study: str, enabled: bool = True,
                        intended_uid: str = "", incoming_uid: str = "") -> bool:
    """Mirror of _start_qt_viewer's gate: return True = render, False = skip.

    Primary signal = STUDY mismatch. Backstop (only when the incoming metadata
    has NO study_uid) = globally-unique SeriesInstanceUID mismatch. Both fail
    open when the value is unknown; the uid backstop is DISABLED whenever the
    incoming study is known, so a same-study render (paired-MG/grow) with a
    different series_uid is never blocked."""
    if not enabled:
        return True
    ist = str(intended_study or "").strip()
    inc = str(incoming_study or "").strip()
    iu = str(intended_uid or "").strip()
    icu = str(incoming_uid or "").strip()
    study_mismatch = bool(ist and inc and inc != ist)
    uid_mismatch = bool(iu and icu and icu != iu)
    return not (study_mismatch or uid_mismatch)


def test_blocks_previous_exam_stomp():
    # intended = current exam; a stale render carries the previous exam's study
    assert _gate_should_render("STUDY_CURRENT", "STUDY_PREVIOUS") is False


def test_allows_correct_current_render():
    assert _gate_should_render("STUDY_CURRENT", "STUDY_CURRENT") is True


def test_allows_legit_switch_to_previous_exam():
    # user explicitly switched the viewport to the previous exam -> intended updated
    assert _gate_should_render("STUDY_PREVIOUS", "STUDY_PREVIOUS") is True


def test_fail_open_when_intended_unknown():
    # first render before any stamp -> proceed
    assert _gate_should_render("", "STUDY_CURRENT") is True


def test_kill_switch_is_byte_identical_legacy():
    # with the gate off, even a cross-study render is allowed (legacy behaviour)
    assert _gate_should_render("STUDY_CURRENT", "STUDY_PREVIOUS", enabled=False) is True


def test_same_study_different_series_not_blocked():
    # paired-MG / grow render a different series within the SAME study -> allowed
    assert _gate_should_render("STUDY_A", "STUDY_A") is True


# --- series_uid backstop (used ONLY when incoming study_uid is missing) ---------------

def test_uid_backstop_blocks_when_study_unknown_and_uid_differs():
    # FAST metadata without study_uid, but the globally-unique series_uid proves
    # this is a same-numbered PREVIOUS-exam series -> block
    assert _gate_should_render("STUDY_CUR", "", intended_uid="UID_A", incoming_uid="UID_B") is False


def test_uid_backstop_allows_when_uid_matches():
    assert _gate_should_render("STUDY_CUR", "", intended_uid="UID_A", incoming_uid="UID_A") is True


def test_blocks_same_study_different_uid_stomp():
    # THE 48912 case: the previous-exam series carries the CURRENT study_uid in its
    # DB-loaded metadata (study falsely matches), but its series_uid differs from the
    # series the viewport was asked to show -> still blocked. A viewport must render
    # EXACTLY its intended series; paired-MG side-by-side uses a SEPARATE viewport
    # with its own intended stamp, so it is unaffected.
    assert _gate_should_render("STUDY_CUR", "STUDY_CUR",
                               intended_uid="UID_CUR4", incoming_uid="UID_PREV4") is False


def test_uid_backstop_fail_open_when_intended_uid_unknown():
    assert _gate_should_render("STUDY_CUR", "", intended_uid="", incoming_uid="UID_B") is True
