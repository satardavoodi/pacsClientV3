"""Server candidates must not freeze a service without its native Windows dependencies."""

from __future__ import annotations

import json
import sys

import pytest

from tools.build import build_local_candidate as candidate


def _asset_cache(root, *, include_pywin32: bool) -> None:
    root.mkdir()
    wheel = "build-wheels/pywin32-311-cp313-cp313-win_amd64.whl"
    (root / "manifest.json").write_text(json.dumps({
        "files": [{"path": wheel}] if include_pywin32 else [],
    }), encoding="utf-8")
    (root / "build-environment.lock").write_text(
        "pywin32==311\n" if include_pywin32 else "pywin32-ctypes==0.2.3\n",
        encoding="utf-8",
    )
    (root / "build-wheels-hashed.lock").write_text(
        "pywin32==311 --hash=sha256:" + "a" * 64 + "\n" if include_pywin32 else "",
        encoding="utf-8",
    )


def test_server_service_preflight_rejects_ctypes_substitute(monkeypatch, tmp_path):
    from importlib import metadata, util

    root = tmp_path / "assets"
    _asset_cache(root, include_pywin32=False)
    monkeypatch.setattr(metadata, "version", lambda name: "311")
    monkeypatch.setattr(util, "find_spec", lambda name: object())

    with pytest.raises(RuntimeError, match="pywin32 311 wheel"):
        candidate.preflight_server_service_dependencies(root)


def test_server_service_preflight_rejects_missing_native_import(monkeypatch, tmp_path):
    from importlib import metadata, util

    root = tmp_path / "assets"
    _asset_cache(root, include_pywin32=True)
    monkeypatch.setattr(metadata, "version", lambda name: "311")
    monkeypatch.setattr(util, "find_spec", lambda name: None if name == "servicemanager" else object())

    with pytest.raises(RuntimeError, match="servicemanager"):
        candidate.preflight_server_service_dependencies(root)


def test_server_service_preflight_accepts_complete_build_inputs(monkeypatch, tmp_path):
    from importlib import metadata, util

    root = tmp_path / "assets"
    _asset_cache(root, include_pywin32=True)
    monkeypatch.setattr(metadata, "version", lambda name: "311")
    monkeypatch.setattr(util, "find_spec", lambda name: object())

    candidate.preflight_server_service_dependencies(root)


def test_client_prepare_does_not_require_server_service_dependencies(monkeypatch, tmp_path):
    from builder import slicer_runtime_payload

    monkeypatch.setattr(candidate, "preflight_server_service_dependencies",
                        lambda *_: (_ for _ in ()).throw(AssertionError("Server dependency gate entered Client lane")))
    monkeypatch.setattr(slicer_runtime_payload, "verify_cache_matches_developer_runtime", lambda *_: None)
    monkeypatch.setattr(candidate, "create_snapshot", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(sys, "argv", ["build_local_candidate", "--local-install-qa",
                                     "--target", "client", "--prepare-only",
                                     "--workspace", str(tmp_path / "candidate")])

    assert candidate.main() == 0
