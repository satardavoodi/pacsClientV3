"""Complete-on-disk view-intent guard resolves the expected count through the ONE
shared authority — DB is a DEFINED shared tier, not a guard-local side path
(52931 series 602, 2026-08-02; unified-path alignment 2026-08-02).

Dragging a fully-on-disk series into a layout re-triggered a download on EVERY
drop because the guard read the expected image count ONLY from the in-memory
`_server_series_info[key].image_count`, which is not populated on some open paths
(single-study fast-cache-hit opens) → expected=0 → guard proceeded to download.

Fix (unified): the shared resolver `series_facts.resolve_series_expected_count`
gained a DEFINED, injected DB tier (`db_count_getter`), ordered AFTER the
in-memory server/thumbnail tiers and BEFORE the disk fallback. The ONE viewer
wrapper `_vc_backend._resolve_series_expected_count(..., include_disk=…)` injects
both the DB getter (→ `dicom_db.get_series_image_count`, canonical reader) and the
existing disk getter, so every viewer site shares the same source hierarchy. The
guard calls that wrapper with `include_disk=False` (data-safety: never treat the
on-disk file count as 'expected'). No guard-local read path remains.
"""
from pathlib import Path

import pytest


def _repo_root() -> Path:
    p = Path(__file__).resolve()
    for anc in p.parents:
        if (anc / "PacsClient").is_dir() and (anc / "modules").is_dir():
            return anc
    raise RuntimeError("repo root not found")


# ── behavioural: the shared resolver's DB tier (pure, no Qt/DB) ───────────────

def test_resolver_db_tier_order_and_data_safety():
    from PacsClient.utils.series_facts import resolve_series_expected_count as r
    # in-memory empty, DB getter known -> DB tier fires (NOT disk)
    res = r("602", series_info_map={}, thumbnail_items=[],
            db_count_getter=lambda k: 530, disk_count_getter=lambda k: 999)
    assert res.expected_count == 530 and res.source == "db.image_count"
    # live server info wins over DB (defined order: in-memory before DB)
    res2 = r("602", series_info_map={"602": {"image_count": 500}},
             db_count_getter=lambda k: 530)
    assert res2.expected_count == 500 and res2.source == "series_info.image_count"
    # DB wins over disk (DB before disk)
    res3 = r("602", series_info_map={}, db_count_getter=lambda k: 530,
             disk_count_getter=lambda k: 42)
    assert res3.expected_count == 530 and res3.source == "db.image_count"
    # nothing known + no getters -> unknown (guard then proceeds -> data-safe)
    res4 = r("602", series_info_map={})
    assert res4.expected_count == 0


def test_series_facts_has_db_getter_tier():
    src = (_repo_root() / "PacsClient" / "utils" / "series_facts.py").read_text(encoding="utf-8")
    assert "db_count_getter" in src
    assert 'source="db.image_count"' in src
    # DB tier must come BEFORE the disk fallback (authoritative before heuristic)
    assert src.index('source="db.image_count"') < src.index('source="disk_count_fallback"')


# ── behavioural: the canonical DB reader ─────────────────────────────────────

def _reset_pool():
    import database._pool as pool
    with pool._pool_lock:
        pool._connection_pool.clear()


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    pytest.importorskip("PacsClient.utils.data_paths")
    import PacsClient.utils.data_paths as dp
    db = tmp_path / "dicom.db"
    monkeypatch.setattr(dp, "DATABASE_FILE", str(db), raising=False)
    _reset_pool()
    from database.dicom_db import init_database, get_db_connection
    init_database()
    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("INSERT INTO patients (patient_id, patient_name) VALUES ('52931','t')")
        ppk = cur.execute("SELECT patient_pk FROM patients WHERE patient_id='52931'").fetchone()[0]
        cur.execute("INSERT INTO studies (study_uid, patient_fk) VALUES (?,?)", ("STUDY-602-UID", ppk))
        spk = cur.execute("SELECT study_pk FROM studies WHERE study_uid='STUDY-602-UID'").fetchone()[0]
        cur.execute(
            "INSERT INTO series (series_uid, study_fk, series_number, image_count) VALUES (?,?,?,?)",
            ("SERIES-602-UID", spk, 602, 530),
        )
        conn.commit()
    try:
        yield
    finally:
        _reset_pool()


def test_get_series_image_count_reads_persisted_count(temp_db):
    from database.dicom_db import get_series_image_count
    assert get_series_image_count("STUDY-602-UID", "602") == 530  # int-stored matches str key
    assert get_series_image_count("STUDY-602-UID", 602) == 530
    assert get_series_image_count("STUDY-602-UID", "999") == 0
    assert get_series_image_count("NO-SUCH-STUDY", "602") == 0


def test_get_series_image_count_never_raises(temp_db, monkeypatch):
    from database import dicom_db
    monkeypatch.setattr(dicom_db, "get_db_connection",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("db down")), raising=True)
    assert dicom_db.get_series_image_count("STUDY-602-UID", "602") == 0


# ── source-pins: ONE shared wrapper injects the DB tier; guard routes through it ──

def _vcb_src() -> str:
    return (_repo_root() / "PacsClient" / "pacs" / "patient_tab" / "ui" / "patient_ui"
            / "_vc_backend.py").read_text(encoding="utf-8")


def _vcl_src() -> str:
    return (_repo_root() / "PacsClient" / "pacs" / "patient_tab" / "ui" / "patient_ui"
            / "_vc_load.py").read_text(encoding="utf-8")


def test_shared_wrapper_injects_db_and_disk_getters():
    src = _vcb_src()
    w = src[src.find("def _resolve_series_expected_count"):]
    w = w[:w.find("\n    def ", 10)]
    assert "include_disk: bool = True" in w
    assert "def _db_count_getter(" in w
    assert "from database.dicom_db import get_series_image_count" in w
    assert "_resolve_canonical_series_identity(series_key)" in w   # multi-study safe
    assert "db_count_getter=_db_count_getter" in w
    assert "disk_count_getter=(_disk_count_fallback if include_disk else None)" in w
    assert 'os.getenv("AIPACS_DL_COMPLETE_DB_COUNT"' in w          # kill switch here
    assert "_series_expected_db_cache" in w                        # cached


def test_guard_routes_through_shared_wrapper_no_local_path():
    src = _vcl_src()
    g = src[src.find("def _view_intent_series_complete_on_disk"):]
    g = g[:g.find("def _coalesce_dm_view_intent")]
    # uses the ONE shared wrapper, disk excluded for data-safety
    assert "self._resolve_series_expected_count(display_key, include_disk=False)" in g
    assert "build_series_completeness_snapshot" in g
    # the guard-local DB helper is GONE, and the guard no longer imports/calls the
    # module-level resolver directly (it goes through the shared self. wrapper)
    assert "_db_series_expected_count" not in src
    assert "from PacsClient.utils.series_facts import resolve_series_expected_count" not in g
