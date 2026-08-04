"""Synthetic benchmark for the Local patient list (OPT-50, 2026-08-03).

Populates a REAL ``PatientTableWidget`` with N synthetic studies, offscreen, and
reports what actually costs time when the local database is large:

  * first_paint_ms   — time to render the first progressive batch (20 rows)
  * full_load_ms     — time to render all N rows
  * db_calls         — per-row SQLite round-trips the render path issued
  * uid_scan_rows    — rows visited by the per-study dedup scan (the O(N^2) term)
  * aa_cells         — cells re-styled by the anti-aliasing passes
  * sorts            — whole-table sorts performed while loading

Run BOTH ways to get a before/after on the same machine:

    .venv\\Scripts\\python.exe tests\\bench\\bench_local_patient_list.py --rows 2000
    .venv\\Scripts\\python.exe tests\\bench\\bench_local_patient_list.py --rows 2000 --legacy

``--legacy`` sets every OPT-50 kill switch to 0, i.e. the exact pre-OPT-50 code
path. This is a standalone measurement tool, not a pytest gate — the filename
deliberately does not start with ``test_``.
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


_LEGACY_FLAGS = {
    "AIPACS_LIST_UID_INDEX": "0",
    "AIPACS_LIST_DB_PREFETCH": "0",
    "AIPACS_LIST_BATCH_FINALIZE": "0",
    "AIPACS_LIST_PATHS_OFFTHREAD": "0",
}

COUNTERS = {"db_calls": 0, "uid_scan_rows": 0, "aa_cells": 0, "sorts": 0}


def _parse_args():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--rows", type=int, default=2000, help="synthetic studies to render")
    ap.add_argument("--legacy", action="store_true",
                    help="run with every OPT-50 kill switch set to 0")
    ap.add_argument("--timeout", type=float, default=600.0)
    return ap.parse_args()


def _make_rows(n: int) -> list[dict]:
    """N synthetic studies across N//4 patients, newest first (display order)."""
    rows = []
    for i in range(n):
        rows.append({
            "patient_id": f"P{i // 4:06d}",
            "patient_name": f"SYNTH^PATIENT{i // 4:06d}",
            "study_date": f"2026{((i % 12) + 1):02d}{((i % 28) + 1):02d}",
            "study_time": f"{(i % 24):02d}{(i % 60):02d}00",
            "study_description": f"SYNTHETIC STUDY {i}",
            "modality": ["CT", "MR", "DX", "US"][i % 4],
            "study_uid": f"1.2.826.0.1.9999.{i}",
            "number_of_series": (i % 9) + 1,
            "number_of_instances": (i % 400) + 1,
            "body_part": ["HEAD", "CHEST", "ABDOMEN", "KNEE"][i % 4],
            "age": str(20 + (i % 60)),
        })
    return rows


def _instrument(widget_mod, table_widget):
    """Wrap the hot call sites with counters. Measurement only — no behaviour."""
    import PacsClient.utils.font_manager as fm
    from database import dicom_db

    # 1) per-row SQLite round-trips: the visited lookup + the Imported-On lookup.
    _orig_find = widget_mod.find_patient_pk

    def _counting_find(pid):
        COUNTERS["db_calls"] += 1
        return _orig_find(pid)

    widget_mod.find_patient_pk = _counting_find

    _orig_map = dicom_db.get_imported_at_map

    def _counting_map(uids):
        COUNTERS["db_calls"] += 1
        return _orig_map(uids)

    dicom_db.get_imported_at_map = _counting_map

    # 2) the dedup scan: count rows visited, which is the O(N^2) term itself.
    _orig_may = type(table_widget)._may_have_study_uid

    def _counting_may(self, uid):
        hit = _orig_may(self, uid)
        if hit:
            COUNTERS["uid_scan_rows"] += int(self.results_table.rowCount() or 0)
        return hit

    type(table_widget)._may_have_study_uid = _counting_may

    # 3) anti-aliasing cells touched (full-table pass vs incremental).
    _orig_aa_table = fm.apply_anti_aliasing_to_table

    def _counting_aa_table(tw):
        COUNTERS["aa_cells"] += int(tw.rowCount() or 0) * int(tw.columnCount() or 0)
        return _orig_aa_table(tw)

    fm.apply_anti_aliasing_to_table = _counting_aa_table
    widget_mod_fm = getattr(fm, "apply_anti_aliasing_to_rows", None)
    if widget_mod_fm is not None:
        def _counting_aa_rows(tw, a, b):
            COUNTERS["aa_cells"] += max(0, int(b) - int(a)) * int(tw.columnCount() or 0)
            return widget_mod_fm(tw, a, b)
        fm.apply_anti_aliasing_to_rows = _counting_aa_rows

    # 4) whole-table sorts performed during the load.
    _orig_sort = type(table_widget)._programmatic_sort

    def _counting_sort(self, col, order):
        COUNTERS["sorts"] += 1
        return _orig_sort(self, col, order)

    type(table_widget)._programmatic_sort = _counting_sort


def _seed_db(tmpdir: Path, rows: list[dict]) -> None:
    """Point the DB at a temp file and seed it with the same synthetic rows, so
    the prefetch / per-row queries do realistic work."""
    import PacsClient.utils.data_paths as dp
    dp.DATABASE_FILE = str(tmpdir / "bench_dicom.db")
    import database._pool as pool
    try:
        with pool._pool_lock:
            pool._connection_pool.clear()
    except Exception:
        pool._connection_pool.clear()

    from database import dicom_db
    dicom_db.init_database()
    with dicom_db.get_db_connection() as conn:
        cur = conn.cursor()
        seen = set()
        for r in rows:
            pid = r["patient_id"]
            if pid not in seen:
                seen.add(pid)
                cur.execute("INSERT OR IGNORE INTO patients (patient_id, patient_name) "
                            "VALUES (?,?)", (pid, r["patient_name"]))
        cur.execute("SELECT patient_id, patient_pk FROM patients")
        pks = dict(cur.fetchall())
        for r in rows:
            cur.execute(
                "INSERT OR IGNORE INTO studies (study_uid, patient_fk, study_date, "
                "study_time, modality, imported_at) VALUES (?,?,?,?,?,?)",
                (r["study_uid"], pks.get(r["patient_id"]), r["study_date"],
                 r["study_time"], r["modality"], "2026-08-01 10:00:00"),
            )
        conn.commit()


def main() -> int:
    args = _parse_args()
    if args.legacy:
        os.environ.update(_LEGACY_FLAGS)

    import tempfile
    tmpdir = Path(tempfile.mkdtemp(prefix="aipacs_bench_"))
    rows = _make_rows(args.rows)
    _seed_db(tmpdir, rows)

    # Redirect the widget's settings dir into the temp folder BEFORE the widget is
    # built: PatientTableWidget._load_sort_settings re-saves whatever it loads, so
    # an un-isolated bench run rewrites the user's real patient_table_sort.json.
    # The real file is COPIED in first, so the bench still measures the user's
    # actual sort configuration.
    import shutil
    import PacsClient.utils.config as _cfg
    _real_cfg = Path(str(_cfg.SOCKET_CONFIG_PATH))
    _bench_cfg = tmpdir / "config"
    _bench_cfg.mkdir(parents=True, exist_ok=True)
    for _name in ("patient_table_sort.json", "patient_table_columns.json"):
        try:
            if (_real_cfg / _name).exists():
                shutil.copy2(_real_cfg / _name, _bench_cfg / _name)
        except Exception:
            pass
    _cfg.SOCKET_CONFIG_PATH = _bench_cfg

    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])

    from PacsClient.pacs.workstation_ui.home_ui import patient_table_widget as ptw
    table = ptw.PatientTableWidget()
    _instrument(ptw, table)

    # Mirror what home_search_service.search_local does before rendering.
    if not args.legacy:
        from PacsClient.pacs.workstation_ui.home_ui.home_search_service import HomeSearchService
        pref = HomeSearchService._collect_list_prefetch(rows)
        table.prime_imported_on_cache(pref.get("uids"), pref.get("imported_at"))
        table.prime_visited_patient_ids(pref.get("known_patient_ids"))
        for r in rows:
            r["_aipacs_renderable"] = True   # resolved off-thread in the real path

    def render_one(patient):
        # Disk resolution is deliberately EXCLUDED from both arms so the two runs
        # compare the table-widget cost on equal terms (see module docstring).
        table.add_patient_data(
            patient_id=patient.get("patient_id"),
            patient_name=patient.get("patient_name"),
            study_date=patient.get("study_date"),
            study_time=patient.get("study_time"),
            description=patient.get("study_description"),
            modality=patient.get("modality"),
            study_uid=patient.get("study_uid"),
            series_count=patient.get("number_of_series"),
            images_count=patient.get("number_of_instances"),
            is_downloaded=True,
            body_part=patient.get("body_part"),
            age=patient.get("age"),
        )
        return True

    t0 = time.perf_counter()
    table.load_progressive(rows, render_one)
    first_paint_ms = (time.perf_counter() - t0) * 1000.0
    first_rows = table.results_table.rowCount()

    # Spin the event loop until the background stream has rendered everything,
    # sampling the longest single uninterrupted GUI-thread block on the way.
    deadline = time.time() + args.timeout
    worst_tick_ms = 0.0
    while table.results_table.rowCount() < len(rows) and time.time() < deadline:
        _t = time.perf_counter()
        app.processEvents()
        worst_tick_ms = max(worst_tick_ms, (time.perf_counter() - _t) * 1000.0)
        time.sleep(0.001)
    full_load_ms = (time.perf_counter() - t0) * 1000.0

    # Let the settle pass (if any) run, so its sort is included in the numbers.
    _settle_deadline = time.time() + 3.0
    while time.time() < _settle_deadline:
        _t = time.perf_counter()
        app.processEvents()
        worst_tick_ms = max(worst_tick_ms, (time.perf_counter() - _t) * 1000.0)
        time.sleep(0.005)

    mode = "LEGACY (pre-OPT-50)" if args.legacy else "OPT-50"
    print("")
    print(f"=== Local patient list bench — {mode} — {args.rows} studies ===")
    print(f"  rows rendered      : {table.results_table.rowCount()} "
          f"(first paint: {first_rows})")
    print(f"  first_paint_ms     : {first_paint_ms:10.1f}")
    print(f"  full_load_ms       : {full_load_ms:10.1f}")
    print(f"  worst_gui_block_ms : {worst_tick_ms:10.1f}")
    print(f"  db_calls           : {COUNTERS['db_calls']:10d}")
    print(f"  uid_scan_rows      : {COUNTERS['uid_scan_rows']:10d}")
    print(f"  aa_cells           : {COUNTERS['aa_cells']:10d}")
    print(f"  sorts              : {COUNTERS['sorts']:10d}")
    print(f"  active_sort_col    : {getattr(table, '_active_sort_col', None)}")
    print("")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
