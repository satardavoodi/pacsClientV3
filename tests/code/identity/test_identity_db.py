"""Unit tests for database.identity_db using a temp SQLite (no live dicom.db).

Follows the project's DB test-isolation discipline: we never touch the real
connection pool — :func:`database.identity_db._db_conn` is monkeypatched to a temp
file connection.
"""

import contextlib
import sqlite3

import pytest

from database import identity_db
from modules.Identity.models import ExternalIdentity


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    db_file = tmp_path / "identity_test.db"

    @contextlib.contextmanager
    def _conn():
        con = sqlite3.connect(db_file)
        try:
            yield con
        finally:
            con.close()

    monkeypatch.setattr(identity_db, "_db_conn", _conn)
    monkeypatch.setattr(identity_db, "_schema_ready", False)
    return db_file


def _ident(user="drv", sub="sub1", name="A B"):
    return ExternalIdentity(
        provider="google",
        subject_id=sub,
        handle="a@b.com",
        display_name=name,
        capabilities=["profile", "cloud_storage"],
        aipacs_user=user,
        extra={"email_verified": True},
    )


def test_upsert_get_list_delete(temp_db):
    rid = identity_db.upsert_identity(_ident())
    assert rid > 0

    got = identity_db.get_identity("drv", "google", "sub1")
    assert got is not None
    assert got.handle == "a@b.com"
    assert got.capabilities == ["profile", "cloud_storage"]
    assert got.extra == {"email_verified": True}

    # Update path (same unique key) must not duplicate.
    identity_db.upsert_identity(_ident(name="Changed"))
    rows = identity_db.list_identities("drv")
    assert len(rows) == 1
    assert rows[0].display_name == "Changed"

    assert identity_db.delete_identity("drv", "google", "sub1") is True
    assert identity_db.get_identity("drv", "google", "sub1") is None


def test_scoped_by_user(temp_db):
    identity_db.upsert_identity(_ident(user="alice", sub="s"))
    identity_db.upsert_identity(_ident(user="bob", sub="s"))
    assert len(identity_db.list_identities("alice")) == 1
    assert len(identity_db.list_identities("bob")) == 1
    # One user's delete must not affect the other.
    identity_db.delete_identity("alice", "google", "s")
    assert len(identity_db.list_identities("alice")) == 0
    assert len(identity_db.list_identities("bob")) == 1
