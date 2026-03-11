from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Optional, Tuple

import numpy as np
import vtk
from vtkmodules.util import numpy_support

from PacsClient.utils.data_paths import ZETA_BOOST_CACHE_DIR


class ZetaBoostDiskCache:
    """Persistent L2 cache for ZetaBoost (filesystem payload + SQLite manifest)."""

    def __init__(
        self,
        *,
        root_dir: Optional[str] = None,
        max_bytes: int = 20 * 1024 * 1024 * 1024,
        max_entries: int = 600,
        logger=None,
    ):
        self._logger = logger
        self._max_bytes = max(1, int(max_bytes or 1))
        self._max_entries = max(1, int(max_entries or 1))

        if root_dir:
            self._root = Path(root_dir)
        else:
            self._root = ZETA_BOOST_CACHE_DIR

        self._root.mkdir(parents=True, exist_ok=True)
        self._db_path = self._root / "manifest.db"
        self._lock = threading.RLock()
        self._init_schema()

    # ------------------------- logging -------------------------
    def _log(self, msg: str):
        try:
            print(f"[ZetaBoostDisk] {msg}")
        except Exception:
            pass
        try:
            if self._logger is not None:
                self._logger.info(f"[ZetaBoostDisk] {msg}")
        except Exception:
            pass

    # ------------------------- db -------------------------
    def _conn(self):
        conn = sqlite3.connect(str(self._db_path), timeout=30)
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA synchronous = NORMAL;")
        conn.execute("PRAGMA busy_timeout = 10000;")
        return conn

    def _init_schema(self):
        with self._lock:
            conn = self._conn()
            cur = conn.cursor()
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS entries (
                    tab_key TEXT NOT NULL,
                    series_number TEXT NOT NULL,
                    file_path TEXT NOT NULL,
                    meta_path TEXT NOT NULL,
                    bytes_size INTEGER DEFAULT 0,
                    created_at REAL NOT NULL,
                    last_access REAL NOT NULL,
                    access_count INTEGER DEFAULT 0,
                    PRIMARY KEY(tab_key, series_number)
                )
                """
            )
            cur.execute("CREATE INDEX IF NOT EXISTS idx_entries_last_access ON entries(last_access)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_entries_tab ON entries(tab_key)")
            conn.commit()
            conn.close()

    # ------------------------- serialization -------------------------
    def _sanitize(self, text: str) -> str:
        s = "".join(ch if ch.isalnum() or ch in ("-", "_", ".") else "_" for ch in str(text))
        return s[:180] if len(s) > 180 else s

    def _paths_for(self, tab_key: str, series_number: str) -> Tuple[Path, Path]:
        tab_dir = self._root / self._sanitize(tab_key)
        tab_dir.mkdir(parents=True, exist_ok=True)
        stem = self._sanitize(series_number)
        return tab_dir / f"{stem}.npz", tab_dir / f"{stem}.meta.json"

    def _write_payload(self, file_path: Path, meta_path: Path, vtk_image_data, metadata):
        if vtk_image_data is None:
            raise ValueError("vtk_image_data is None")

        dims = tuple(int(v) for v in vtk_image_data.GetDimensions())
        spacing = tuple(float(v) for v in vtk_image_data.GetSpacing())
        origin = tuple(float(v) for v in vtk_image_data.GetOrigin())

        if len(dims) != 3 or min(dims) <= 0:
            raise ValueError(f"Invalid dimensions for disk cache: {dims}")

        pd = vtk_image_data.GetPointData() if vtk_image_data is not None else None
        scalars = pd.GetScalars() if pd is not None else None
        if scalars is None:
            raise ValueError("No scalar data in vtk_image_data")

        np_scalars = numpy_support.vtk_to_numpy(scalars)
        n_components = int(vtk_image_data.GetNumberOfScalarComponents() or 1)
        vtk_scalar_type = int(scalars.GetDataType())
        scalar_dtype = str(np_scalars.dtype)
        if n_components > 1 and np_scalars.ndim == 1:
            np_scalars = np_scalars.reshape((-1, n_components))

        # Preserve critical field data for orientation/sync correctness.
        fd = vtk_image_data.GetFieldData()
        field_dict = {}
        if fd is not None:
            for name in ("DirectionMatrix", "ITKOrigin", "ITKSpacing", "ITKDimensions"):
                arr = fd.GetArray(name)
                if arr is None:
                    continue
                try:
                    vals = numpy_support.vtk_to_numpy(arr)
                    field_dict[name] = vals.tolist()
                except Exception:
                    pass

        # Use uncompressed npz for fastest possible reads.
        # Compressed npz (zlib) saved ~50% disk space but caused 1.5-4s
        # decompression latency per series during warmup.  Uncompressed
        # reads are limited only by SSD bandwidth (~0.2-0.5s for 100MB).
        np.savez(
            str(file_path),
            scalars=np_scalars,
            dims=np.asarray(dims, dtype=np.int32),
            spacing=np.asarray(spacing, dtype=np.float64),
            origin=np.asarray(origin, dtype=np.float64),
            n_components=np.asarray([n_components], dtype=np.int16),
            vtk_scalar_type=np.asarray([vtk_scalar_type], dtype=np.int16),
            scalar_dtype=np.asarray([scalar_dtype]),
        )

        with open(meta_path, "w", encoding="utf-8") as f:
            payload_meta = {
                "metadata": metadata if isinstance(metadata, dict) else {},
                "field_data": field_dict,
            }
            json.dump(payload_meta, f, ensure_ascii=False, default=str)

    def _read_payload(self, file_path: Path, meta_path: Path):
        if not file_path.exists() or not meta_path.exists():
            return None

        # Use context manager to guarantee the npz file handle is closed.
        # Without this, NpzFile keeps the underlying zip open until GC,
        # causing ResourceWarning and potential file-descriptor exhaustion.
        with np.load(str(file_path), allow_pickle=False) as data:
            np_scalars = np.array(data["scalars"])  # copy into standalone array
            dims = tuple(int(v) for v in data["dims"].tolist())
            spacing = tuple(float(v) for v in data["spacing"].tolist())
            origin = tuple(float(v) for v in data["origin"].tolist())
            n_components = int(data["n_components"][0]) if "n_components" in data else 1
            vtk_scalar_type = int(data["vtk_scalar_type"][0]) if "vtk_scalar_type" in data else None
            scalar_dtype = str(data["scalar_dtype"][0]) if "scalar_dtype" in data else None

        vtk_image = vtk.vtkImageData()
        vtk_image.SetDimensions(*dims)
        vtk_image.SetSpacing(*spacing)
        vtk_image.SetOrigin(*origin)
        vtk_image.SetExtent(0, dims[0] - 1, 0, dims[1] - 1, 0, dims[2] - 1)

        if n_components > 1:
            flat = np_scalars.reshape((-1, n_components))
        else:
            flat = np_scalars.reshape(-1)

        try:
            if scalar_dtype:
                flat = flat.astype(np.dtype(scalar_dtype), copy=False)
        except Exception:
            pass

        if vtk_scalar_type is not None:
            vtk_arr = numpy_support.numpy_to_vtk(flat, deep=True, array_type=vtk_scalar_type)
        else:
            vtk_arr = numpy_support.numpy_to_vtk(flat, deep=True)
        vtk_arr.SetNumberOfComponents(max(1, n_components))
        vtk_image.GetPointData().SetScalars(vtk_arr)

        with open(meta_path, "r", encoding="utf-8") as f:
            raw_meta = json.load(f)

        if isinstance(raw_meta, dict) and "metadata" in raw_meta:
            metadata = raw_meta.get("metadata", {})
            field_data = raw_meta.get("field_data", {}) or {}
        else:
            metadata = raw_meta if isinstance(raw_meta, dict) else {}
            field_data = {}

        # Restore critical field data arrays if present.
        if field_data:
            fd = vtk_image.GetFieldData()
            for name, vals in field_data.items():
                try:
                    np_vals = np.asarray(vals, dtype=np.float64).reshape(-1)
                    vtk_fd_arr = vtk.vtkDoubleArray()
                    vtk_fd_arr.SetName(str(name))
                    vtk_fd_arr.SetNumberOfTuples(int(np_vals.size))
                    for i, v in enumerate(np_vals.tolist()):
                        vtk_fd_arr.SetValue(i, float(v))
                    fd.AddArray(vtk_fd_arr)
                except Exception:
                    pass

        return vtk_image, metadata

    # ------------------------- public API -------------------------
    def has(self, tab_key: str, series_number: str) -> bool:
        """Cheap manifest-only existence check (no payload deserialize, no touch)."""
        tab_key = str(tab_key)
        series_number = str(series_number)
        with self._lock:
            conn = self._conn()
            cur = conn.cursor()
            cur.execute(
                "SELECT 1 FROM entries WHERE tab_key=? AND series_number=? LIMIT 1",
                (tab_key, series_number),
            )
            row = cur.fetchone()
            conn.close()
            return row is not None

    def get(self, tab_key: str, series_number: str):
        tab_key = str(tab_key)
        series_number = str(series_number)
        now = time.time()

        # Step 1 — manifest lookup (fast, under lock).
        with self._lock:
            conn = self._conn()
            cur = conn.cursor()
            cur.execute(
                "SELECT file_path, meta_path FROM entries WHERE tab_key=? AND series_number=?",
                (tab_key, series_number),
            )
            row = cur.fetchone()
            conn.close()

        if not row:
            return None

        file_path = Path(row[0])
        meta_path = Path(row[1])

        # Step 2 — heavy file I/O (numpy decompression + VTK reconstruction)
        # performed WITHOUT the lock so other threads are not blocked.
        payload = self._read_payload(file_path, meta_path)
        if payload is None:
            self.delete_entry(tab_key, series_number)
            return None

        # Step 3 — access-stats update (fast, under lock).
        with self._lock:
            try:
                conn = self._conn()
                cur = conn.cursor()
                cur.execute(
                    """
                    UPDATE entries
                    SET last_access=?, access_count=COALESCE(access_count,0)+1
                    WHERE tab_key=? AND series_number=?
                    """,
                    (now, tab_key, series_number),
                )
                conn.commit()
                conn.close()
            except Exception:
                pass
        return payload

    def put(self, tab_key: str, series_number: str, vtk_image_data, metadata):
        tab_key = str(tab_key)
        series_number = str(series_number)
        now = time.time()

        with self._lock:
            file_path, meta_path = self._paths_for(tab_key, series_number)
            try:
                self._write_payload(file_path, meta_path, vtk_image_data, metadata)
                size = int((file_path.stat().st_size if file_path.exists() else 0) + (meta_path.stat().st_size if meta_path.exists() else 0))

                conn = self._conn()
                cur = conn.cursor()
                cur.execute(
                    """
                    INSERT INTO entries(tab_key, series_number, file_path, meta_path, bytes_size, created_at, last_access, access_count)
                    VALUES(?,?,?,?,?,?,?,?)
                    ON CONFLICT(tab_key, series_number) DO UPDATE SET
                        file_path=excluded.file_path,
                        meta_path=excluded.meta_path,
                        bytes_size=excluded.bytes_size,
                        last_access=excluded.last_access
                    """,
                    (tab_key, series_number, str(file_path), str(meta_path), size, now, now, 0),
                )
                conn.commit()
                conn.close()

                self.prune()
            except Exception as e:
                # Fail-safe rollback for repeatability: remove partial files and stale DB rows.
                try:
                    conn = self._conn()
                    cur = conn.cursor()
                    cur.execute("DELETE FROM entries WHERE tab_key=? AND series_number=?", (tab_key, series_number))
                    conn.commit()
                    conn.close()
                except Exception:
                    pass
                for p in (file_path, meta_path):
                    try:
                        if p.exists():
                            p.unlink()
                    except Exception:
                        pass
                self._log(f"PUT_ROLLBACK tab={tab_key} series={series_number} error={e}")
                raise

    def delete_entry(self, tab_key: str, series_number: str):
        tab_key = str(tab_key)
        series_number = str(series_number)

        with self._lock:
            conn = self._conn()
            cur = conn.cursor()
            cur.execute(
                "SELECT file_path, meta_path FROM entries WHERE tab_key=? AND series_number=?",
                (tab_key, series_number),
            )
            row = cur.fetchone()
            cur.execute("DELETE FROM entries WHERE tab_key=? AND series_number=?", (tab_key, series_number))
            conn.commit()
            conn.close()

            if row:
                for p in (Path(row[0]), Path(row[1])):
                    try:
                        if p.exists():
                            p.unlink()
                    except Exception:
                        pass

    def clear_tab(self, tab_key: str):
        tab_key = str(tab_key)
        with self._lock:
            conn = self._conn()
            cur = conn.cursor()
            cur.execute("SELECT file_path, meta_path FROM entries WHERE tab_key=?", (tab_key,))
            rows = cur.fetchall() or []
            cur.execute("DELETE FROM entries WHERE tab_key=?", (tab_key,))
            conn.commit()
            conn.close()

            for fp, mp in rows:
                for p in (Path(fp), Path(mp)):
                    try:
                        if p.exists():
                            p.unlink()
                    except Exception:
                        pass
            self._log(f"CLEAR_TAB tab={tab_key} removed={len(rows)}")

    def prune(self):
        """Global LRU prune by total bytes and entry count."""
        with self._lock:
            conn = self._conn()
            cur = conn.cursor()

            cur.execute("SELECT COALESCE(SUM(bytes_size),0), COUNT(*) FROM entries")
            total_bytes, total_entries = cur.fetchone() or (0, 0)
            total_bytes = int(total_bytes or 0)
            total_entries = int(total_entries or 0)

            if total_bytes <= self._max_bytes and total_entries <= self._max_entries:
                conn.close()
                return

            cur.execute(
                """
                SELECT tab_key, series_number, file_path, meta_path, bytes_size
                FROM entries
                ORDER BY last_access ASC, created_at ASC
                """
            )
            rows = cur.fetchall() or []

            removed = 0
            for tab_key, series_number, fp, mp, bsz in rows:
                if total_bytes <= self._max_bytes and total_entries <= self._max_entries:
                    break
                try:
                    p1 = Path(fp)
                    p2 = Path(mp)
                    if p1.exists():
                        p1.unlink()
                    if p2.exists():
                        p2.unlink()
                except Exception:
                    pass

                cur.execute("DELETE FROM entries WHERE tab_key=? AND series_number=?", (tab_key, series_number))
                total_bytes = max(0, total_bytes - int(bsz or 0))
                total_entries = max(0, total_entries - 1)
                removed += 1

            conn.commit()
            conn.close()

            if removed:
                self._log(f"PRUNE removed={removed} bytes_now={total_bytes} entries_now={total_entries}")