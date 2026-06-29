"""Guard: a multi-study SECONDARY series loads with ITS OWN study_pk, not the primary's
(48101 Study 3, 2026-06-29).

Study 3 (a previous exam) resolved its disk path correctly, but `_load_single_series_on_demand`
passed `study_pk=_effective_study_pk` which DEFAULTS to the PRIMARY study's pk. With a series
number that collides across studies (both Study 1 and Study 3 have a "series 1"),
`load_single_series_by_number(study_pk=<primary>, series_number=1)` fetched the PRIMARY study's
series 1 from the DB → the viewer displayed a Study-1 series instead of Study 3
(live: `FAST:series_selected ... study_uid=<primary>`).

Fix: when the load resolved to a non-primary study (`_ms_study_uid != tab.study_uid`), set
`_effective_study_pk` to THAT series' own study_pk (or None → read headers from the resolved
disk path), never the primary's. The primary series (slot 0) is untouched. Flag
AIPACS_MULTISTUDY_PER_SERIES_STUDY_PK (default on).

Source-pins (the load path is deep + DB/Qt-bound; behavior is live-verified on 48101).
"""
from pathlib import Path


def _repo_root() -> Path:
    p = Path(__file__).resolve()
    for anc in p.parents:
        if (anc / "PacsClient").is_dir() and (anc / "modules").is_dir():
            return anc
    raise RuntimeError("repo root not found from %s" % __file__)


def _src() -> str:
    return (
        _repo_root() / "PacsClient" / "pacs" / "patient_tab" / "ui" / "patient_ui"
        / "_vc_load.py"
    ).read_text(encoding="utf-8")


def test_per_series_study_pk_override_present():
    src = _src()
    assert 'os.getenv("AIPACS_MULTISTUDY_PER_SERIES_STUDY_PK"' in src
    # gated on a resolved SECONDARY study (different from the tab primary)
    assert "if (_ms_resolved and _ms_study_uid" in src
    assert "str(_ms_study_uid) != _primary_uid_pk" in src
    # the override sets the per-series study_pk (its own pk or None), never the primary's
    assert "_effective_study_pk = _sec_pk" in src
    assert "find_study_pk_with_study_uid(_ms_study_uid)" in src


def test_override_runs_after_the_primary_default():
    src = _src()
    # the default (primary pk) is assigned BEFORE our secondary override, so the override
    # has the last word for a secondary series.
    i_default = src.find("_effective_study_pk = self.parent_widget.metadata_fixed.get('study_pk', None)")
    i_override = src.find("_effective_study_pk = _sec_pk")
    assert i_default != -1 and i_override != -1 and i_default < i_override


def test_h7p4_disk_count_uses_disk_series_number():
    src = _src()
    # the H7-P4 diagnostic must count the series' OWN folder (orig series number), not the
    # offset display key (which is never a disk folder).
    assert "_h7_sp = Path(study_path) / str(ms_disk_series_number)" in src
    assert "_h7_sp = Path(study_path) / _h7_sn" not in src
