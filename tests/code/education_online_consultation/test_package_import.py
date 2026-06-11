"""Guards for the one-click consultation package ingest (B4 / ADR-0003, 2026-06-10).

Qt-free. The import reuses the EXISTING offline-cloud engine; these tests stub
``PacsClient.utils.offline_cloud`` exactly like the export-staging guards do.
"""

import sys
import types

import pytest

from modules.education.online_consultation.package_import import (
    find_package_root,
    import_consultation_package,
)


def _stub_engine(monkeypatch, *, studies_by_root, sync_results, calls):
    mod = types.ModuleType("PacsClient.utils.offline_cloud")

    def fake_list(server, search_data=None):
        return list(studies_by_root.get(server.get("folder_path"), []))

    def fake_sync(server, study_uid, *, actor=None):
        calls.append({"root": server.get("folder_path"), "uid": study_uid, "actor": actor})
        return sync_results.get(study_uid, {"ok": True})

    mod.list_offline_cloud_studies = fake_list
    mod.sync_offline_cloud_study_to_local = fake_sync
    monkeypatch.setitem(sys.modules, "PacsClient.utils.offline_cloud", mod)


def test_find_package_root_direct_and_nested(monkeypatch, tmp_path):
    direct = tmp_path / "direct"
    direct.mkdir()
    nested_parent = tmp_path / "parent"
    (nested_parent / "pkg").mkdir(parents=True)

    _stub_engine(
        monkeypatch,
        studies_by_root={
            str(direct): [{"study_uid": "1.2.3"}],
            str(nested_parent / "pkg"): [{"study_uid": "4.5.6"}],
        },
        sync_results={},
        calls=[],
    )
    assert find_package_root(str(direct)) == str(direct)
    assert find_package_root(str(nested_parent)) == str(nested_parent / "pkg")
    assert find_package_root(str(tmp_path / "missing")) is None


def test_import_all_studies(monkeypatch, tmp_path):
    root = tmp_path / "pkg"
    root.mkdir()
    calls = []
    _stub_engine(
        monkeypatch,
        studies_by_root={str(root): [{"study_uid": "1.2.3"}, {"study_uid": "4.5.6"}]},
        sync_results={"1.2.3": {"ok": True}, "4.5.6": {"ok": True}},
        calls=calls,
    )
    res = import_consultation_package(str(root), actor={"email": "a@x.com"})
    assert res["ok"] is True
    assert res["imported"] == ["1.2.3", "4.5.6"]
    assert res["errors"] == []
    assert [c["uid"] for c in calls] == ["1.2.3", "4.5.6"]
    assert calls[0]["actor"] == {"email": "a@x.com"}


def test_partial_failure_reported_not_raised(monkeypatch, tmp_path):
    root = tmp_path / "pkg"
    root.mkdir()
    _stub_engine(
        monkeypatch,
        studies_by_root={str(root): [{"study_uid": "1.2.3"}, {"study_uid": "4.5.6"}]},
        sync_results={
            "1.2.3": {"ok": True},
            "4.5.6": {"ok": False, "error": "package.db missing"},
        },
        calls=[],
    )
    res = import_consultation_package(str(root))
    assert res["ok"] is False
    assert res["imported"] == ["1.2.3"]
    assert res["errors"] and "package.db missing" in res["errors"][0]


def test_no_package_found_raises(monkeypatch, tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    _stub_engine(monkeypatch, studies_by_root={}, sync_results={}, calls=[])
    with pytest.raises(RuntimeError, match="No importable study package"):
        import_consultation_package(str(empty))
