"""Guard S1 — skip the redundant re-download when the server confirms a study is
already complete on disk (sync/download lifecycle review, 2026-06-15).

On an explicit open the server series-info is always re-fetched (the lightweight
metadata check), but a full CRITICAL priority re-download was then started even for
a complete study, spawning a subprocess that contends disk I/O with the viewer
reading the same files (patient 46370). S1 skips that re-download when the manifest
model, fed the FRESH server list, reports no missing/partial series — any error or
doubt falls through to the normal download.

The skip lives inside the async open coroutine, so this is a static source guard on
the decision + a behavioural test of the underlying decision function
(`sync_manifest.evaluate_sync`, already covered by test_sync_manifest.py).
"""
from __future__ import annotations

import ast
from pathlib import Path

from modules.storage import sync_manifest as sm

_REPO = Path(__file__).resolve().parents[3]
_OPEN = _REPO / "PacsClient" / "pacs" / "workstation_ui" / "home_ui" / "home_panel" / "_hp_patient_open.py"


def _open_async_src():
    src = _OPEN.read_text(encoding="utf-8-sig")
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "_on_patient_double_clicked_async":
            return ast.get_source_segment(src, node) or ""
    return ""


def test_open_gates_download_skip_on_flag_and_manifest():
    src = _OPEN.read_text(encoding="utf-8-sig")
    # The flag exists and is overridable.
    assert "_OPEN_SKIP_DOWNLOAD_WHEN_COMPLETE" in src
    assert "AIPACS_OPEN_SKIP_DOWNLOAD_WHEN_COMPLETE" in src

    body = _open_async_src()
    assert body, "could not find _on_patient_double_clicked_async"
    # Decision uses the manifest model on the fresh server series list.
    assert "evaluate_sync" in body
    assert "_OPEN_SKIP_DOWNLOAD_WHEN_COMPLETE" in body
    # Skip ONLY when nothing is missing or partial.
    assert "missing_series" in body and "partial_series" in body
    # And only when the server was actually reached (study_info present).
    assert "and study_info" in body
    # S6: when SOME series are missing, queue ONLY the missing/partial ones
    # (not the whole study) — the 46640 "all of them start downloading" fix.
    assert "download_only_missing" in body
    assert "series_number" in body  # filters the server list by series number
    assert "_download_series_list" in body
    # 46640 stale-COMPLETED unblock: when downloading missing series, a terminal
    # DM state is reset so R17 ("already exists / completed") can't block the new
    # series. Only terminal states (COMPLETED/CANCELLED) are touched.
    assert "_OPEN_RESET_STALE_COMPLETE" in src
    assert "AIPACS_OPEN_RESET_STALE_COMPLETE" in src
    assert "download_reset_stale_complete" in body
    assert "state_store" in body and ".reset(" in body
    assert "COMPLETED" in body and "CANCELLED" in body


def test_resync_is_disk_aware():
    """46533 follow-up: the resync growth check must ALSO consult the disk (via the
    manifest), so a study whose DB rows exist but whose FILES are missing is still
    flagged for download instead of reporting 'current'."""
    hp_series = (
        _REPO / "PacsClient" / "pacs" / "workstation_ui" / "home_ui" / "home_panel" / "_hp_series.py"
    )
    src = hp_series.read_text(encoding="utf-8-sig")
    assert "_RESYNC_DISK_AWARE" in src and "AIPACS_RESYNC_DISK_AWARE" in src
    assert "evaluate_sync" in src              # uses the manifest (disk vs server)
    assert "disk_missing" in src
    # The sync decision is grew OR disk-missing (not DB growth alone).
    assert "needs_sync = grew or bool(disk_missing)" in src
    assert "if not needs_sync:" in src


def test_reopen_already_open_refreshes_from_server():
    """46533: re-opening an already-open patient must NOT just focus the tab and
    return — it must also fire a forced server check (to download series added
    while the tab was open) and refresh the open viewer's series sidebar."""
    src = _OPEN.read_text(encoding="utf-8-sig")
    assert "_OPEN_REFRESH_ALREADY_OPEN" in src
    assert "AIPACS_OPEN_REFRESH_ALREADY_OPEN" in src
    body = _open_async_src()
    # The already-open focus path now does a forced resync + a viewer refresh.
    assert "existing_tab_focused" in body
    assert "existing_tab_series_refreshed" in body
    assert "_resync_patient_studies_from_server" in body
    assert "force=True" in body
    assert "set_server_series_info" in body
    # The refresh must sit in the already-open branch (before that early return),
    # i.e. between the focus log and the download-wiring section.
    i_focus = body.find("existing_tab_focused")
    i_refresh = body.find("existing_tab_series_refreshed")
    assert 0 < i_focus < i_refresh


def test_resync_resets_stale_complete_before_enqueue():
    """The resync growth path (study grew while viewing) must also clear a stale
    terminal DM state before enqueueing the new series, or the queue de-dup blocks
    them — the same 46640 bug, reached via the background resync instead of open."""
    hp_series = (
        _REPO / "PacsClient" / "pacs" / "workstation_ui" / "home_ui" / "home_panel" / "_hp_series.py"
    )
    src = hp_series.read_text(encoding="utf-8-sig")
    # Shares the open path's flag so one switch governs both paths.
    assert "_RESYNC_RESET_STALE_COMPLETE" in src
    assert "AIPACS_OPEN_RESET_STALE_COMPLETE" in src
    assert "resync_reset_stale_complete" in src
    assert ".reset(study_uid)" in src
    assert "COMPLETED" in src and "CANCELLED" in src
    # The reset must come BEFORE the add_downloads enqueue (so it isn't blocked).
    i_reset = src.find("resync_reset_stale_complete")
    i_enqueue = src.find("dm.add_downloads")
    assert 0 < i_reset < i_enqueue, "reset must precede the resync add_downloads enqueue"


def test_skip_decision_complete_study():
    """If the server list matches disk (no missing/partial), the decision says skip."""
    # Inject DB facts + simulate disk via the manifest's own logic by monkeypatching
    # is unnecessary here: evaluate_sync with server == db and disk present is tested
    # in test_sync_manifest; this asserts the *decision shape* S1 relies on.
    decision = sm.evaluate_sync(
        "1.2.s1",
        server_series=[{"series_number": 1, "image_count": 3}],
        db_number_of_series=1,
        db_series={"1": {"image_count": 3}},
    )
    # With no disk files present (tmp not set up here) the study is NOT complete,
    # so S1 must NOT skip — proving the guard is real, not vacuous.
    assert decision["missing_series"] == ["1"]
    would_skip = not decision["missing_series"] and not decision["partial_series"]
    assert would_skip is False


def test_skip_decision_falls_through_on_partial(tmp_path, monkeypatch):
    """A partial study (disk < server) must NOT be skipped."""
    src = tmp_path / "patients"
    src.mkdir()
    study = src / "1.2.partial"
    (study / "1").mkdir(parents=True)
    (study / "1" / "a.dcm").write_bytes(b"x" * 200)  # 1 of 3
    monkeypatch.setattr(sm, "SOURCE_PATH", src)
    monkeypatch.setattr(sm, "THUMBNAIL_PATH", tmp_path / "thumbs")
    (tmp_path / "thumbs").mkdir()
    decision = sm.evaluate_sync(
        "1.2.partial",
        server_series=[{"series_number": 1, "image_count": 3}],
        db_number_of_series=1, db_series={"1": {"image_count": 3}},
    )
    would_skip = not decision["missing_series"] and not decision["partial_series"]
    assert would_skip is False  # partial -> download proceeds


def test_skip_decision_skips_complete(tmp_path, monkeypatch):
    """A complete study (disk >= server for every series) IS skippable."""
    src = tmp_path / "patients"
    src.mkdir()
    study = src / "1.2.complete"
    (study / "1").mkdir(parents=True)
    for i in range(3):
        (study / "1" / f"{i}.dcm").write_bytes(b"x" * 200)  # 3 of 3
    monkeypatch.setattr(sm, "SOURCE_PATH", src)
    monkeypatch.setattr(sm, "THUMBNAIL_PATH", tmp_path / "thumbs")
    (tmp_path / "thumbs").mkdir()
    decision = sm.evaluate_sync(
        "1.2.complete",
        server_series=[{"series_number": 1, "image_count": 3}],
        db_number_of_series=1, db_series={"1": {"image_count": 3}},
    )
    would_skip = not decision["missing_series"] and not decision["partial_series"]
    assert would_skip is True  # complete -> redundant download skipped
