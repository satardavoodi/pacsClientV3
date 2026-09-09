"""Offline evidence identity checks use synthetic artifacts only."""

import json
import socket
from pathlib import Path

import pytest

from tools.eagle_eye_bench import bench


@pytest.fixture
def source(tmp_path, monkeypatch):
    def deny_network(*args, **kwargs):
        raise AssertionError("Snapshot operations must remain offline")
    monkeypatch.setattr(socket, "create_connection", deny_network)
    monkeypatch.setattr(socket.socket, "connect", deny_network)
    session = tmp_path / "source"
    session.mkdir()
    (session / "evidence").mkdir()
    (session / "evidence" / "one.png").write_bytes(b"synthetic-image-one")
    (session / "evidence" / "two.png").write_bytes(b"synthetic-image-two")
    request = {
        "model": "test-verifier", "backend": "test-bridge",
        "pipeline": {"version": "test-legacy"},
        "prompt": {"text": "Synthetic historical rubric", "temperature": 0.2},
        "sent": {"header": "Header", "context": "Frozen upstream context",
                 "image_count": 2, "images": [
                     {"file": "evidence/two.png", "caption": "Second slice first"},
                     {"file": "evidence/one.png", "caption": "First slice second"},
                 ]},
        "local_provenance": {"study_instance_uid": "synthetic-private-identity"},
    }
    (session / "llm_stage3_request.json").write_text(json.dumps(request), encoding="utf-8")
    (session / "llm_result.txt").write_text("Synthetic answer must not be copied", encoding="utf-8")
    return session


def test_snapshot_preserves_saved_input_order_bytes_and_legacy_prompt(source, tmp_path):
    from tools.eagle_eye_bench import frozen_input
    before = {p.relative_to(source): p.read_bytes() for p in source.rglob("*") if p.is_file()}
    target = tmp_path / "snapshot"
    snapshot_id = frozen_input.freeze(source, target)
    assert frozen_input.check(target, expected_id=snapshot_id) == snapshot_id
    actual = json.loads((target / "input.json").read_text(encoding="utf-8"))
    original = json.loads((source / "llm_stage3_request.json").read_text(encoding="utf-8"))
    assert actual == {k: original[k] for k in ("model", "backend", "pipeline", "prompt", "sent")}
    assert (target / "images/001.png").read_bytes() == b"synthetic-image-two"
    assert (target / "images/002.png").read_bytes() == b"synthetic-image-one"
    assert not (target / "llm_result.txt").exists()
    assert before == {p.relative_to(source): p.read_bytes() for p in source.rglob("*") if p.is_file()}


@pytest.mark.parametrize("entry", ["../outside.png", "C:/outside.png", "//host/share.png", "evidence/../one.png"])
def test_snapshot_rejects_unbound_image_paths_before_creating_output(source, tmp_path, entry):
    from tools.eagle_eye_bench import frozen_input
    request_file = source / "llm_stage3_request.json"
    request = json.loads(request_file.read_text(encoding="utf-8"))
    request["sent"]["images"][0]["file"] = entry
    request_file.write_text(json.dumps(request), encoding="utf-8")
    target = tmp_path / "rejected"
    with pytest.raises(frozen_input.SnapshotError):
        frozen_input.freeze(source, target)
    assert not target.exists()


@pytest.mark.parametrize("defect", ["count", "missing", "too_large", "bad_prompt"])
def test_invalid_or_incomplete_input_fails_before_output(source, tmp_path, monkeypatch, defect):
    from tools.eagle_eye_bench import frozen_input
    request_file = source / "llm_stage3_request.json"
    request = json.loads(request_file.read_text(encoding="utf-8"))
    if defect == "count":
        request["sent"]["image_count"] = 3
    elif defect == "missing":
        request["sent"]["images"][0]["file"] = "evidence/absent.png"
    elif defect == "too_large":
        monkeypatch.setattr(frozen_input, "MAX_IMAGE_BYTES", 2)
    else:
        request["prompt"].pop("text")
    request_file.write_text(json.dumps(request), encoding="utf-8")
    with pytest.raises(frozen_input.SnapshotError):
        frozen_input.freeze(source, tmp_path / "rejected")
    assert not (tmp_path / "rejected").exists()


def test_existing_or_nested_output_cannot_mutate_the_session(source, tmp_path):
    from tools.eagle_eye_bench import frozen_input
    for target in (source, source / "nested", tmp_path):
        with pytest.raises(frozen_input.SnapshotError):
            frozen_input.freeze(source, target)


@pytest.mark.parametrize("changed", ["input.json", "images/001.png", "manifest.json"])
def test_modification_is_detected(source, tmp_path, changed):
    from tools.eagle_eye_bench import frozen_input
    target = tmp_path / "snapshot"
    digest = frozen_input.freeze(source, target)
    path = target / changed
    path.write_bytes(path.read_bytes() + b"changed")
    with pytest.raises(frozen_input.SnapshotError):
        frozen_input.check(target, expected_id=digest)


def test_manifest_reordering_and_wrong_external_identity_are_detected(source, tmp_path):
    from tools.eagle_eye_bench import frozen_input
    target = tmp_path / "snapshot"
    digest = frozen_input.freeze(source, target)
    with pytest.raises(frozen_input.SnapshotError):
        frozen_input.check(target, expected_id="0" * 64)
    manifest_file = target / "manifest.json"
    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    manifest["files"].reverse()
    manifest_file.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(frozen_input.SnapshotError):
        frozen_input.check(target, expected_id=digest)


def test_cli_is_offline_and_reports_only_safe_identity(source, tmp_path, capsys):
    target = tmp_path / "snapshot"
    assert bench.main(["freeze", "--session", str(source), "--out", str(target)]) == 0
    output = capsys.readouterr().out
    assert "Frozen input:" in output
    assert "synthetic-private-identity" not in output
    assert bench.main(["check-frozen", "--snapshot", str(target)]) == 0
    (target / "images/001.png").write_bytes(b"changed")
    assert bench.main(["check-frozen", "--snapshot", str(target)]) == 1
    assert str(source) not in capsys.readouterr().out


def test_encoded_document_limit_is_checked_before_output(source, tmp_path, monkeypatch):
    from tools.eagle_eye_bench import frozen_input
    request_file = source / "llm_stage3_request.json"
    request = json.loads(request_file.read_text(encoding="utf-8"))
    request["sent"]["context"] = "\u00e9" * 3000
    request_file.write_text(json.dumps(request, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(frozen_input, "MAX_DOCUMENT_BYTES", request_file.stat().st_size + 1)
    with pytest.raises(frozen_input.SnapshotError):
        frozen_input.freeze(source, tmp_path / "rejected")
    assert not (tmp_path / "rejected").exists()


def test_linked_directory_is_not_followed(source, tmp_path, monkeypatch):
    from tools.eagle_eye_bench import frozen_input
    monkeypatch.setattr(Path, "is_junction", lambda p: p == source / "evidence")
    with pytest.raises(frozen_input.SnapshotError, match="Linked artifact"):
        frozen_input.freeze(source, tmp_path / "rejected")
    assert not (tmp_path / "rejected").exists()


def test_failed_write_has_no_completion_marker_and_cannot_be_reused(source, tmp_path, monkeypatch):
    from tools.eagle_eye_bench import frozen_input
    target = tmp_path / "partial"
    original_open = Path.open
    def fail_second_image(path, *args, **kwargs):
        if path == target / "images/002.png":
            raise OSError("Synthetic write failure")
        return original_open(path, *args, **kwargs)
    monkeypatch.setattr(Path, "open", fail_second_image)
    with pytest.raises(frozen_input.SnapshotError, match="write failed"):
        frozen_input.freeze(source, target)
    assert not (target / "manifest.json").exists()
    with pytest.raises(frozen_input.SnapshotError):
        frozen_input.check(target)
    with pytest.raises(frozen_input.SnapshotError):
        frozen_input.freeze(source, target)
