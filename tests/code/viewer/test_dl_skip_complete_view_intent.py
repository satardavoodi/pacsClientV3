"""Guard: a view-intent does NOT re-download a series already complete on disk
(48272 series 302, 2026-06-28).

Switching to series 302 (94/94 .dcm on disk, 0 .part) re-issued a DM
priority/download intent (`request_critical_series` storm + `restart_after_done`
94/94 -> 42/94), re-fetching the finished series and thrashing the single download
slot. Fix: `_VCLoadMixin._coalesce_dm_view_intent` skips the whole DM intent when
`_view_intent_series_complete_on_disk` confirms the series is complete.

DATA-SAFE by construction: the expected count is resolved through the ONE shared
viewer resolver `_resolve_series_expected_count(..., include_disk=False)` (server
info + thumbnail metadata + persisted DB image_count — NEVER the on-disk file
count), and the guard returns False — i.e. proceeds with the download — on any
uncertainty (unknown count, missing folder, or disk < expected). The viewer LOAD
path is untouched, so a complete series still displays from disk. Flag
`AIPACS_DL_SKIP_COMPLETE_VIEW_INTENT` (default ON; `=0` legacy).

Source-pins + a behavioral test of the completeness check against a real temp folder.
"""
import types
from pathlib import Path

import pytest


def _repo_root() -> Path:
    p = Path(__file__).resolve()
    for anc in p.parents:
        if (anc / "PacsClient").is_dir() and (anc / "modules").is_dir():
            return anc
    raise RuntimeError("repo root not found from %s" % __file__)


def _src() -> str:
    return (
        _repo_root() / "PacsClient" / "pacs" / "patient_tab" / "ui" / "patient_ui" / "_vc_load.py"
    ).read_text(encoding="utf-8")


def test_flag_default_on():
    src = _src()
    assert 'os.getenv("AIPACS_DL_SKIP_COMPLETE_VIEW_INTENT", "1")' in src
    blk = src[src.find("_DL_SKIP_COMPLETE_VIEW_INTENT = "):src.find("_DL_SKIP_COMPLETE_VIEW_INTENT = ") + 160]
    assert '.strip() != "0"' in blk


def test_completeness_check_is_data_safe():
    src = _src()
    fn = src.find("def _view_intent_series_complete_on_disk(")
    assert fn != -1
    body = src[fn:src.find("def _coalesce_dm_view_intent(")]
    # expected comes from the ONE shared viewer resolver with include_disk=False —
    # so the on-disk file count is NEVER treated as 'expected' (data-safety), and
    # the guard bails (proceeds to download) on unknown/zero.
    assert "self._resolve_series_expected_count(display_key, include_disk=False)" in body
    assert "if expected <= 0 or not study_uid:" in body
    assert "return False" in body
    # counts only finished .dcm (not .part)
    assert ".endswith('.dcm')" in body
    # "complete" is decided by the ONE shared completeness authority, not a bespoke compare
    assert "build_series_completeness_snapshot(" in body
    assert "snap.has_expected_count and snap.is_disk_complete" in body


def test_guard_wired_into_coalesce_dm_view_intent():
    src = _src()
    fn = src.find("def _coalesce_dm_view_intent(")
    assert fn != -1
    body = src[fn:fn + 2200]
    assert "_DL_SKIP_COMPLETE_VIEW_INTENT" in body
    assert "self._view_intent_series_complete_on_disk(series_number)" in body
    assert "[DL-SKIP-COMPLETE]" in body


def test_complete_on_disk_behavioral(tmp_path, monkeypatch):
    pytest.importorskip("PySide6")
    try:
        from PacsClient.pacs.patient_tab.ui.patient_ui import _vc_load as VC
        import PacsClient.utils.config as cfg
    except Exception as exc:  # pragma: no cover - heavy import env dependent
        pytest.skip(f"_vc_load import unavailable: {exc}")

    # Skip the canonical-identity resolver in the helper (use study_uid + key directly).
    monkeypatch.setattr(VC, "_DM_CANON_IDENTITY", False, raising=False)
    # Point SOURCE_PATH at the temp tree (the helper imports it inside the function).
    monkeypatch.setattr(cfg, "SOURCE_PATH", str(tmp_path), raising=False)

    study, sn, total = "STUDYUID.1", "302", 94
    series_dir = tmp_path / study / sn
    series_dir.mkdir(parents=True)
    for i in range(total):
        (series_dir / f"Instance_{i:04d}.dcm").write_bytes(b"x")

    fake = types.SimpleNamespace(
        parent_widget=types.SimpleNamespace(
            study_uid=study,
            _server_series_info={sn: {"image_count": total}},
        ),
    )

    # The guard now resolves the expected count through the ONE shared viewer
    # wrapper (_resolve_series_expected_count). Stub it to mirror the shared
    # resolver's server-info tier from _server_series_info, so this test still
    # exercises the guard's DISK-completeness decision (the point of the test).
    def _fake_resolve(series_number, *, include_disk=True):
        info = (fake.parent_widget._server_series_info or {}).get(str(series_number)) or {}
        return types.SimpleNamespace(expected_count=int(info.get("image_count") or 0))
    fake._resolve_series_expected_count = _fake_resolve

    check = VC._VCLoadMixin._view_intent_series_complete_on_disk.__get__(fake)

    # 94 on disk, server says 94 -> COMPLETE -> True (the intent would be skipped).
    assert check(sn) is True

    # 93 on disk (one missing) -> partial -> False (download proceeds).
    next(series_dir.glob("*.dcm")).unlink()
    assert check(sn) is False

    # Restore completeness, but a .part is NOT counted as a finished image.
    (series_dir / "Instance_9999.part").write_bytes(b"x")
    assert check(sn) is False  # still 93 .dcm < 94

    # Unknown server count -> never skip (data-safe), even if the folder is full.
    for i in range(total):
        (series_dir / f"Instance_{i:04d}.dcm").write_bytes(b"x")
    fake.parent_widget._server_series_info = {}
    assert check(sn) is False

    # Folder missing entirely -> False.
    fake.parent_widget._server_series_info = {sn: {"image_count": total}}
    fake.parent_widget.study_uid = "OTHER.STUDY"
    assert check(sn) is False
