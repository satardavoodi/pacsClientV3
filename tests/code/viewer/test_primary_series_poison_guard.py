"""Guard test — primary (plain-key) series must load from the tab's OWN study,
not a previous-exam study whose folder collides on the same series number.

Repro (patient 48912, previous exam 29694, 2026-07-04): after loading previous-exam
series 4 (offset key 1000004), dropping CURRENT-exam series 4 (plain key 4) re-displayed
the PREVIOUS exam's series 4. The log showed `[SERIES UNLOAD] rebind_to_series=1000004`
and `open_series path=<previous_study>/4`. Cause: `_resolve_plain_series_study_path`
re-resolves a poisoned tab study_path only via the series' `_server_series_info` entry
`series_path` — but on this tab only the SECONDARY entries had one, so the primary series
4 fell through to the "does study_path/4 exist?" check, which the poisoned previous-study
folder (also having a /4) satisfied → wrong study kept.

Fix: a plain (< 1_000_000) key always belongs to the tab's PRIMARY study_uid; on a
multi-study tab, if the passed study_path is not that study's own folder, re-resolve to
`SOURCE_PATH/<primary_study_uid>`. Kill switch AIPACS_PRIMARY_SERIES_POISON_GUARD=0.

Source-pins guard the real edit; a filesystem-backed mirror reproduces the decision
(constructing a real ViewerController needs Qt/VTK).
"""

from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
VCL = REPO / "PacsClient" / "pacs" / "patient_tab" / "ui" / "patient_ui" / "_vc_load.py"


def _src() -> str:
    return VCL.read_text(encoding="utf-8", errors="ignore")


# --- source-pins ---------------------------------------------------------------------

def test_flag_default_on():
    s = _src()
    assert 'AIPACS_PRIMARY_SERIES_POISON_GUARD' in s
    assert '_os.getenv("AIPACS_PRIMARY_SERIES_POISON_GUARD", "1")' in s


def test_guard_logic_present():
    s = _src()
    b = s[s.index("POISON GUARD"):s.index("POISON GUARD") + 2400]
    assert "_Path(study_path).name != primary_uid" in b, "must compare tab study folder to primary uid"
    assert "SOURCE_PATH as _SRC" in b, "re-resolves against SOURCE_PATH"
    assert "(_primary_path / str(series_key)).exists()" in b, "only when the primary really has the series"
    assert "_is_multistudy_hint" in b, "multi-study gated"


# --- filesystem-backed mirror of the resolution decision -----------------------------

def _resolve(series_key, study_path, *, entry_path, multistudy, primary_uid,
             source_path, flag=True):
    """Mirror of _resolve_plain_series_study_path incl. the poison guard."""
    sk = str(series_key)
    if entry_path:
        parent = Path(entry_path).parent
        if study_path and str(parent) == str(study_path):
            return None
        if parent.exists():
            return str(parent)
    # poison guard
    if (flag and multistudy and primary_uid and study_path
            and Path(study_path).name != primary_uid):
        pp = Path(source_path) / primary_uid
        if (pp / sk).exists():
            return str(pp)
    # legacy fallback: keep the tab path if it has the series
    if study_path and (Path(study_path) / sk).exists():
        return None
    return None


def _mk(src: Path, uid: str, series: str) -> Path:
    d = src / uid / series
    d.mkdir(parents=True, exist_ok=True)
    (d / "img.dcm").write_bytes(b"x")
    return src / uid


def test_poison_reresolves_to_primary(tmp_path):
    src = tmp_path / "dicom"
    cur = _mk(src, "CURRENT_UID", "4")          # current exam has series 4
    prev = _mk(src, "PREVIOUS_UID", "4")         # previous exam ALSO has series 4
    # study_path poisoned to the previous study after viewing it
    out = _resolve("4", str(prev), entry_path="", multistudy=True,
                   primary_uid="CURRENT_UID", source_path=str(src))
    assert out == str(cur), "must re-resolve the primary series to the CURRENT study"


def test_kill_switch_keeps_legacy_poison(tmp_path):
    src = tmp_path / "dicom"
    _mk(src, "CURRENT_UID", "4")
    prev = _mk(src, "PREVIOUS_UID", "4")
    out = _resolve("4", str(prev), entry_path="", multistudy=True,
                   primary_uid="CURRENT_UID", source_path=str(src), flag=False)
    assert out is None, "flag off -> legacy behaviour (keeps the poisoned tab path)"


def test_single_study_byte_identical(tmp_path):
    src = tmp_path / "dicom"
    cur = _mk(src, "CURRENT_UID", "4")
    out = _resolve("4", str(cur), entry_path="", multistudy=False,
                   primary_uid="CURRENT_UID", source_path=str(src))
    assert out is None, "single-study: keep the tab path (guard never fires)"


def test_correct_primary_path_unchanged(tmp_path):
    src = tmp_path / "dicom"
    cur = _mk(src, "CURRENT_UID", "4")
    # study_path already the primary study's folder -> name == primary_uid -> no change
    out = _resolve("4", str(cur), entry_path="", multistudy=True,
                   primary_uid="CURRENT_UID", source_path=str(src))
    assert out is None


def test_primary_series_absent_does_not_misresolve(tmp_path):
    src = tmp_path / "dicom"
    prev = _mk(src, "PREVIOUS_UID", "4")        # only the previous study has /4 on disk
    (src / "CURRENT_UID").mkdir(parents=True, exist_ok=True)  # current exists but no /4 yet
    out = _resolve("4", str(prev), entry_path="", multistudy=True,
                   primary_uid="CURRENT_UID", source_path=str(src))
    # primary /4 not on disk -> guard must NOT fire (falls through), never invents a path
    assert out is None
