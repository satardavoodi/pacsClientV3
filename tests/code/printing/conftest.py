"""Printing tests never access clinical storage or the live database."""
import sqlite3
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def isolated_printing_storage(monkeypatch, tmp_path):
    import PacsClient.utils.data_paths as paths
    from database import _pool
    monkeypatch.setattr(paths, "DATABASE_FILE", tmp_path / "printing.db")
    monkeypatch.setattr(paths, "DICOM_IMAGES_DIR", tmp_path / "dicom")
    monkeypatch.setattr(paths, "ATTACHMENTS_DIR", tmp_path / "attachments")
    with _pool._pool_lock:
        _pool._connection_pool.clear()
    connect = sqlite3.connect
    def isolated_connect(database, *args, **kwargs):
        if str(database) != ":memory:":
            assert Path(database).resolve().is_relative_to(tmp_path.resolve()), "Unexpected database access"
        return connect(database, *args, **kwargs)
    monkeypatch.setattr(sqlite3, "connect", isolated_connect)
    yield
    with _pool._pool_lock:
        _pool._connection_pool.clear()
