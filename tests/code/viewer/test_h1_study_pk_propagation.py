"""Guard: H1 study_pk propagation for the DB-metadata primary path (2026-06-08).

`_VCLoadMixin._ensure_study_pk_for_db_metadata` makes the EXISTING DB-metadata
path reachable for single-study, server-opened studies by resolving study_pk from
study_uid and stamping metadata_fixed up front. These guards lock in the
conservative gates that keep it safe:
  * single-study only (multi-study keeps the disk path → never cross-study mix);
  * flag-gated (AIPACS_VIEWER_DB_METADATA=0 disables);
  * no-op if already set / no study_uid / study not in DB (→ disk fallback);
  * stamps the resolved pk only on success.
"""
import importlib
import logging
import types

import pytest


@pytest.fixture
def vcload():
    return importlib.import_module(
        "PacsClient.pacs.patient_tab.ui.patient_ui._vc_load"
    )


def _make_self(metadata_fixed=None, multistudy_hint=False, studies_series=None,
               study_uid="1.2.840.3"):
    pw = types.SimpleNamespace(
        metadata_fixed=(metadata_fixed if metadata_fixed is not None
                        else {"patient_id": "1", "study_uid": study_uid, "x": 1}),
        _is_multistudy_hint=multistudy_hint,
        _studies_series=(studies_series if studies_series is not None
                         else {study_uid: {}}),
        study_uid=study_uid,
    )
    return types.SimpleNamespace(parent_widget=pw, logger=logging.getLogger("h1test"))


def _run(vcload, self_obj, monkeypatch, returns=42, env="1"):
    import PacsClient.utils as _pu
    calls = []

    def fake_find(uid):
        calls.append(uid)
        return returns

    monkeypatch.setattr(_pu, "find_study_pk_with_study_uid", fake_find, raising=False)
    monkeypatch.setenv("AIPACS_VIEWER_DB_METADATA", env)
    vcload._VCLoadMixin._ensure_study_pk_for_db_metadata(self_obj)
    return calls


def test_single_study_stamps_study_pk(vcload, monkeypatch):
    s = _make_self()
    calls = _run(vcload, s, monkeypatch, returns=42)
    assert s.parent_widget.metadata_fixed.get("study_pk") == 42
    assert calls == ["1.2.840.3"]


def test_multistudy_hint_skips(vcload, monkeypatch):
    s = _make_self(multistudy_hint=True)
    calls = _run(vcload, s, monkeypatch, returns=42)
    assert "study_pk" not in s.parent_widget.metadata_fixed
    assert calls == []  # never even queries the DB for a multi-study patient


def test_studies_series_gt1_skips(vcload, monkeypatch):
    s = _make_self(studies_series={"a": {}, "b": {}})
    _run(vcload, s, monkeypatch, returns=42)
    assert "study_pk" not in s.parent_widget.metadata_fixed


def test_flag_off_skips(vcload, monkeypatch):
    s = _make_self()
    calls = _run(vcload, s, monkeypatch, returns=42, env="0")
    assert "study_pk" not in s.parent_widget.metadata_fixed
    assert calls == []


def test_already_set_is_noop(vcload, monkeypatch):
    s = _make_self(metadata_fixed={"study_pk": 7, "study_uid": "1.2.840.3", "x": 1})
    calls = _run(vcload, s, monkeypatch, returns=42)
    assert s.parent_widget.metadata_fixed["study_pk"] == 7  # unchanged
    assert calls == []  # short-circuits before the DB call


def test_no_study_uid_is_noop(vcload, monkeypatch):
    s = _make_self(study_uid="")
    _run(vcload, s, monkeypatch, returns=42)
    assert "study_pk" not in s.parent_widget.metadata_fixed


def test_study_not_in_db_falls_back(vcload, monkeypatch):
    # find_study_pk_with_study_uid returns 0/None → leave unset → disk fallback.
    s = _make_self()
    _run(vcload, s, monkeypatch, returns=0)
    assert not s.parent_widget.metadata_fixed.get("study_pk")


def test_default_is_off(vcload, monkeypatch):
    # With no env var set, H1 is dormant (default OFF, 2026-06-08) until the
    # series_pk<->instances linkage gap is fixed.
    import PacsClient.utils as _pu
    monkeypatch.delenv("AIPACS_VIEWER_DB_METADATA", raising=False)
    called = []
    monkeypatch.setattr(_pu, "find_study_pk_with_study_uid",
                        lambda uid: called.append(uid) or 42, raising=False)
    s = _make_self()
    vcload._VCLoadMixin._ensure_study_pk_for_db_metadata(s)
    assert "study_pk" not in s.parent_widget.metadata_fixed
    assert called == []  # short-circuits before touching the DB
