"""Guard test for OPT-06 — study-scoped (study_uid + series_number) grow-lane fallback bind.

The download->viewer grow lane re-keys a DM download event to the awaiting viewport by
matching the event's globally-unique ``series_uid`` against the ``series_uid`` stored in
this patient's ``_server_series_info[display_key]``. For a PREVIOUS-EXAM / secondary study
whose offset-key entry carries a stale/degenerate ``series_uid``, that match fails, so the
event is dropped or mis-resolved to a bare number and the awaiting viewport never grows —
the "series N shows in current AND previous exam" / "needs a second drag" class
(OPT-03/06/20).

The fix (flag ``AIPACS_GROW_LANE_STUDY_NUMBER_BIND``, DEFAULT OFF): when — and only when —
the ``series_uid`` match already failed AND the caller passes the DM event's own
``(study_uid, series_number)``, the lane also binds by the CANONICAL
``(study_uid, series_number)``. STRICTLY study-scoped (both must equal the event's own
study+number), so it can never cross-study collide; it never overrides a ``series_uid``
match; default OFF is byte-identical legacy.

This file has two halves:
  * source-pins that catch a stale/missing fix in the build (run anywhere), and
  * a pure mirror of the matcher logic exercising the safety-critical scenarios headless
    (the real method needs the PySide6 viewer stack; the pure logic is the invariant).
"""

from __future__ import annotations

from pathlib import Path

_REPO = Path(__file__).resolve().parents[3]
_HOME = _REPO / "PacsClient" / "pacs" / "workstation_ui" / "home_ui" / "home_download_service.py"
_VCP = _REPO / "PacsClient" / "pacs" / "patient_tab" / "ui" / "patient_ui" / "_vc_progressive.py"


def _src(p: Path) -> str:
    # Robust against a truncated/short read (large files under some mounts): take the
    # longest of a few reads. On the Windows source build this is a single clean read.
    best = ""
    for _ in range(8):
        try:
            b = p.read_bytes()
        except Exception:
            continue
        s = b.decode("utf-8-sig", errors="ignore")
        if len(s) > len(best):
            best = s
    return best


# ── source-pins ──────────────────────────────────────────────────────────────────────

def test_flag_default_off_kill_switch():
    s = _src(_HOME)
    # DEFAULT OFF pending live source-build validation on 48912 / a previous-exam patient.
    assert '"AIPACS_GROW_LANE_STUDY_NUMBER_BIND", "0"' in s, "OPT-06 flag must default OFF"
    assert "_GROW_LANE_STUDY_NUMBER_BIND" in s


def test_home_computes_event_number_and_threads_identity():
    s = _src(_HOME)
    # authoritative number resolver from the DM task series_list (not the stale uid->number map)
    assert "def _dm_event_series_number(uid, series_uid):" in s
    # number computed only when the flag is on (zero cost otherwise)
    assert "_dm_event_series_number(uid, series_uid) if _GROW_LANE_STUDY_NUMBER_BIND else None" in s
    # the DM event's own study (uid) + number are threaded to the viewer matcher
    assert "event_study_uid=uid, event_series_number=_ev_num" in s
    # flag-off path calls the legacy single-arg matcher verbatim (byte-identical)
    assert "return vc.display_key_for_active_series_uid(series_uid)" in s


def test_viewer_matcher_has_studyscoped_fallback():
    s = _src(_VCP)
    # new kwargs on the matcher
    assert "event_study_uid=None, event_series_number=None" in s
    # study-scoped compare: BOTH study_uid AND series_number must equal the event's own
    assert 'str(_r_study or "").strip() == ev_study' in s
    assert 'str(_r_series or "").strip() == ev_num' in s
    # success marker for the live verify
    assert "[GROW-LANE-STUDYNUM-BIND]" in s
    # the primary series_uid loop still exists and runs first
    assert "exact globally-unique series_uid match" in s


# ── pure mirror of display_key_for_active_series_uid (the invariant) ───────────────────

class _VW:
    def __init__(self, awaiting=None, progressive=None):
        self._awaiting_series_number = awaiting
        self._progressive_series_number = progressive


class _Node:
    def __init__(self, vtk_w):
        self.vtk_widget = vtk_w


class _Ctrl:
    """Mirror of the matcher: exact series_uid first (never cross-study), then the
    OPT-06 study-scoped (study_uid, series_number) fallback."""

    def __init__(self, nodes, ssi, canon):
        self.lst_nodes_viewer = nodes
        self._ssi = ssi
        self._canon = canon

    def _resolve_canonical_series_identity(self, key):
        return self._canon.get(str(key), ("", str(key), None))

    def match(self, series_uid, *, event_study_uid=None, event_series_number=None):
        su = str(series_uid or "").strip()
        if not su and not (event_study_uid and event_series_number):
            return None
        ssi = self._ssi

        def _uid_for_key(key):
            if not key:
                return ""
            info = ssi.get(key) or ssi.get(str(key))
            if isinstance(info, dict):
                u = str(info.get("series_uid") or info.get("series_instance_uid") or "").strip()
                if u:
                    return u
            _rs, _rn, _ru = self._resolve_canonical_series_identity(key)
            return str(_ru or "").strip()

        if su:
            for node in self.lst_nodes_viewer or []:
                vtk_w = getattr(node, "vtk_widget", None)
                if vtk_w is None:
                    continue
                for key in (getattr(vtk_w, "_awaiting_series_number", None),
                            getattr(vtk_w, "_progressive_series_number", None)):
                    key = str(key) if key else None
                    if key and _uid_for_key(key) == su:
                        return key
        ev_study = str(event_study_uid or "").strip()
        ev_num = str(event_series_number or "").strip()
        if ev_study and ev_num:
            for node in self.lst_nodes_viewer or []:
                vtk_w = getattr(node, "vtk_widget", None)
                if vtk_w is None:
                    continue
                for key in (getattr(vtk_w, "_awaiting_series_number", None),
                            getattr(vtk_w, "_progressive_series_number", None)):
                    key = str(key) if key else None
                    if not key:
                        continue
                    _r_study, _r_series, _ = self._resolve_canonical_series_identity(key)
                    if (str(_r_study or "").strip() == ev_study
                            and str(_r_series or "").strip() == ev_num):
                        return key
        return None


def _prev_exam_ctrl():
    # Viewport awaits offset key '1000004' (prev-exam study Q, series 4) whose STORED
    # series_uid is stale; its canonical identity is (Q, '4', real uid). The DM reports the
    # prev-exam series 4 under a series_uid that does NOT equal the stale stored one.
    ssi = {"1000004": {"series_uid": "STALE"}}
    canon = {"1000004": ("Q", "4", "REALUID_Q4")}
    nodes = [_Node(_VW(awaiting="1000004"))]
    return _Ctrl(nodes, ssi, canon)


def test_legacy_series_uid_path_misses_on_stale_uid():
    c = _prev_exam_ctrl()
    # Without the DM identity, the stale stored uid means no match — the pre-fix behaviour.
    assert c.match("DMUID_Q4") is None


def test_studyscoped_fallback_binds_previous_exam():
    c = _prev_exam_ctrl()
    assert c.match("DMUID_Q4", event_study_uid="Q", event_series_number="4") == "1000004"


def test_never_binds_across_studies():
    c = _prev_exam_ctrl()
    # same series number 4 but a DIFFERENT study P must NEVER bind (cross-study isolation).
    assert c.match("DMUID_Q4", event_study_uid="P", event_series_number="4") is None


def test_number_mismatch_in_same_study_does_not_bind():
    c = _prev_exam_ctrl()
    assert c.match("DMUID_Q4", event_study_uid="Q", event_series_number="9") is None


def test_series_uid_match_takes_precedence_over_fallback():
    # Stored uid actually matches on '1000004'; another awaiting key '5' also resolves to
    # (Q,4). The exact series_uid match must win — the fallback must not steal it.
    ssi = {"1000004": {"series_uid": "DMUID_Q4"}, "5": {"series_uid": "other"}}
    canon = {"1000004": ("Q", "4", "DMUID_Q4"), "5": ("Q", "4", "other")}
    nodes = [_Node(_VW(awaiting="1000004")), _Node(_VW(progressive="5"))]
    c = _Ctrl(nodes, ssi, canon)
    assert c.match("DMUID_Q4", event_study_uid="Q", event_series_number="4") == "1000004"


def test_no_kwargs_is_byte_identical_legacy():
    # A single-study / primary series with a good stored uid still resolves; and a stale one
    # still returns None when called the legacy way (no DM identity) — i.e. default-off safe.
    c = _prev_exam_ctrl()
    assert c.match("DMUID_Q4") is None
    ssi = {"3": {"series_uid": "U3"}}
    canon = {"3": ("P", "3", "U3")}
    c2 = _Ctrl([_Node(_VW(awaiting="3"))], ssi, canon)
    assert c2.match("U3") == "3"
