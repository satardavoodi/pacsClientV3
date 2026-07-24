"""Dedicated regression guard: re-synchronising a study that GREW on the server.

Scenario reported from the field (vahid, 2026-07-23) and modelled end-to-end here
against the REAL disk-vs-server read-model ``modules.storage.sync_manifest.evaluate_sync``
(the same decision the open-viewer back-fill uses in
``_hp_patient_open._enqueue_missing_series_for_open_study`` to download ONLY what is
missing):

    1. A study is first downloaded/opened locally (series count confirmed).
    2. The modality later sends MORE series / images to the SAME study on the server.
    3. On re-sync the workstation MUST detect the delta (new + grown series).
    4. ONLY the missing data is (would be) fetched — already-local series are untouched.
    5. After the fetch the study reads up-to-date with NO duplication / count inflation.
    6. Interrupted (`.part`) writes never count as present.
    7. A series with pixels on disk but no thumbnail png is reported for thumbnail refresh.

This pins the delta CONTRACT so a future refactor (e.g. the offset-key / disk-count
family — 48476, OPT-35/36/39) cannot silently reintroduce "server grew but the
workstation didn't notice."  It is pure/headless: no DB, no server, no Qt.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from modules.storage import sync_manifest
from modules.storage.sync_manifest import evaluate_sync

STUDY = "1.2.826.0.1.3680043.8.498.resync.grow.0001"


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

@pytest.fixture()
def synthetic_store(tmp_path, monkeypatch):
    """Point the read-model at a temp SOURCE/THUMBNAIL root, disable the verdict
    cache (so each phase re-scans deterministically) and the pixel-stub probe (so
    a plain ``.dcm`` file counts as one finished instance without needing real
    DICOM bytes)."""
    source = tmp_path / "source"
    thumbs = tmp_path / "thumbnails"
    source.mkdir()
    thumbs.mkdir()
    monkeypatch.setattr(sync_manifest, "SOURCE_PATH", source)
    monkeypatch.setattr(sync_manifest, "THUMBNAIL_PATH", thumbs)
    monkeypatch.setattr(sync_manifest, "_MANIFEST_CACHE_ENABLED", False)
    monkeypatch.setattr(sync_manifest, "_SYNC_VERIFY_OBSERVE", False)
    monkeypatch.setattr(sync_manifest, "_SYNC_VERIFY_ENFORCE", False)
    return source, thumbs


def _write_instances(source: Path, series_number: str, n: int, *, ext: str = ".dcm") -> None:
    """Create/extend a series folder with ``n`` finished instances."""
    sd = source / STUDY / str(series_number)
    sd.mkdir(parents=True, exist_ok=True)
    existing = len(list(sd.glob("*.dcm")))
    for i in range(existing, existing + n):
        (sd / f"{i:04d}{ext}").write_bytes(b"DICM-stub")


def _write_partial(source: Path, series_number: str, name: str = "9999.dcm.part") -> None:
    sd = source / STUDY / str(series_number)
    sd.mkdir(parents=True, exist_ok=True)
    (sd / name).write_bytes(b"partial-download")


def _write_thumb(thumbs: Path, series_number: str) -> None:
    td = thumbs / STUDY
    td.mkdir(parents=True, exist_ok=True)
    (td / f"{series_number}.png").write_bytes(b"\x89PNG")


def _server(*pairs) -> list[dict]:
    """Build a server study-info series list from (series_number, image_count) pairs."""
    return [{"series_number": sn, "image_count": ic} for sn, ic in pairs]


def _db(*pairs) -> dict:
    return {str(sn): {"image_count": ic, "thumbnail_path": ""} for sn, ic in pairs}


def _disk_count(dec: dict, sn: str) -> int:
    info = dec["manifest"]["series"].get(sn)
    return int(info["disk_instance_count"]) if info else 0


# ---------------------------------------------------------------------------
# The end-to-end re-sync-grow story
# ---------------------------------------------------------------------------

def test_initial_study_is_up_to_date(synthetic_store):
    """Step 1-2: freshly downloaded study (series 1=3 img, 2=2 img) reads complete."""
    source, thumbs = synthetic_store
    _write_instances(source, "1", 3)
    _write_instances(source, "2", 2)
    _write_thumb(thumbs, "1")
    _write_thumb(thumbs, "2")

    dec = evaluate_sync(STUDY, _server(("1", 3), ("2", 2)),
                        db_number_of_series=2, db_series=_db(("1", 3), ("2", 2)))

    assert dec["missing_series"] == []
    assert dec["partial_series"] == []
    assert dec["missing_thumbnails"] == []
    assert dec["up_to_date"] is True
    assert dec["state"] == sync_manifest.STATE_DOWNLOADED


def test_server_grows_delta_is_detected(synthetic_store):
    """Step 3 (the reported bug): server adds a NEW series (3) and GROWS an
    existing one (2: 2->4). Re-sync MUST flag series 3 missing and series 2 partial."""
    source, thumbs = synthetic_store
    _write_instances(source, "1", 3)
    _write_instances(source, "2", 2)

    grown_server = _server(("1", 3), ("2", 4), ("3", 5))
    dec = evaluate_sync(STUDY, grown_server,
                        db_number_of_series=3, db_series=_db(("1", 3), ("2", 4), ("3", 5)))

    assert dec["missing_series"] == ["3"], "new server series not detected as missing"
    assert dec["partial_series"] == ["2"], "grown server series not detected as partial"
    assert dec["up_to_date"] is False
    assert dec["state"] == sync_manifest.STATE_PARTIAL


def test_only_missing_is_filled_then_up_to_date_without_duplication(synthetic_store):
    """Steps 4-8: after fetching ONLY the missing data (2 more images for series 2,
    the 5 images for the new series 3) the study reads complete, series 1 is
    untouched, and counts equal the server exactly (no duplication / inflation)."""
    source, thumbs = synthetic_store
    _write_instances(source, "1", 3)
    _write_instances(source, "2", 2)
    grown_server = _server(("1", 3), ("2", 4), ("3", 5))
    grown_db = _db(("1", 3), ("2", 4), ("3", 5))

    # --- simulate the resync downloading ONLY the delta -------------------
    _write_instances(source, "2", 2)   # 2 -> 4  (append, not re-download)
    _write_instances(source, "3", 5)   # brand new series
    _write_thumb(thumbs, "1")
    _write_thumb(thumbs, "2")
    _write_thumb(thumbs, "3")

    dec = evaluate_sync(STUDY, grown_server, db_number_of_series=3, db_series=grown_db)

    assert dec["missing_series"] == []
    assert dec["partial_series"] == []
    assert dec["up_to_date"] is True
    # exact counts — series 1 must NOT have been re-fetched / duplicated
    assert _disk_count(dec, "1") == 3
    assert _disk_count(dec, "2") == 4
    assert _disk_count(dec, "3") == 5

    # idempotent: a second resync sees nothing to do and does not inflate counts
    dec2 = evaluate_sync(STUDY, grown_server, db_number_of_series=3, db_series=grown_db)
    assert dec2["up_to_date"] is True
    assert dec2["missing_series"] == [] and dec2["partial_series"] == []
    assert _disk_count(dec2, "1") == 3
    assert _disk_count(dec2, "2") == 4
    assert _disk_count(dec2, "3") == 5


def test_interrupted_download_part_file_counts_as_missing(synthetic_store):
    """Step 6: an interrupted write (`.dcm.part`) must NEVER be counted as a
    finished instance — the series stays 'missing' so resync re-fetches it."""
    source, _ = synthetic_store
    _write_instances(source, "1", 3)
    _write_partial(source, "4")  # only a partial for series 4

    dec = evaluate_sync(STUDY, _server(("1", 3), ("4", 2)),
                        db_number_of_series=2, db_series=_db(("1", 3), ("4", 2)))

    assert "4" in dec["missing_series"], ".part-only series must read as missing"
    assert _disk_count(dec, "4") == 0
    assert dec["up_to_date"] is False


def test_missing_thumbnail_is_reported_even_when_pixels_complete(synthetic_store):
    """Step 7: series with DICOM on disk but no thumbnail png is surfaced for a
    thumbnail refresh (so the sidebar/thumbnail strip updates on resync)."""
    source, thumbs = synthetic_store
    _write_instances(source, "1", 3)
    _write_thumb(thumbs, "1")
    _write_instances(source, "2", 2)  # pixels present, NO thumbnail written

    dec = evaluate_sync(STUDY, _server(("1", 3), ("2", 2)),
                        db_number_of_series=2, db_series=_db(("1", 3), ("2", 2)))

    assert dec["missing_series"] == [] and dec["partial_series"] == []
    assert dec["missing_thumbnails"] == ["2"]
    assert dec["up_to_date"] is False  # a missing thumbnail keeps it "not settled"


def test_decision_contract_keys_are_stable(synthetic_store):
    """Pin the public decision shape the callers rely on (open back-fill / resync)."""
    source, _ = synthetic_store
    _write_instances(source, "1", 1)
    dec = evaluate_sync(STUDY, _server(("1", 1)), db_number_of_series=1,
                        db_series=_db(("1", 1)))
    for key in ("study_uid", "state", "manifest", "checked_server",
                "missing_series", "partial_series", "missing_thumbnails", "up_to_date"):
        assert key in dec, f"resync decision lost contract key: {key}"
    assert dec["checked_server"] is True
