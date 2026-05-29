from pathlib import Path
import base64
import pytest

import PacsClient.utils.config as config_mod
from modules.network import attachment_pending_sync as pending_mod
from modules.network import upload_download_attchments as upload_mod


class _FakeClient:
    def __init__(self, response=None, exc=None):
        self._response = response
        self._exc = exc
        self.calls = 0

    def send_request(self, endpoint, params):
        self.calls += 1
        if self._exc is not None:
            raise self._exc
        return self._response


def _setup_study_attachment(tmp_path, study_uid, file_name="note.txt"):
    study_dir = Path(tmp_path) / study_uid
    study_dir.mkdir(parents=True, exist_ok=True)
    file_path = study_dir / file_name
    file_path.write_text("demo", encoding="utf-8")
    return file_path


def test_upload_success_clears_pending_manifest(tmp_path, monkeypatch):
    study_uid = "study-success"
    file_path = _setup_study_attachment(tmp_path, study_uid)

    monkeypatch.setattr(config_mod, "ATTACHMENT_PATH", Path(tmp_path))
    monkeypatch.setattr(upload_mod, "ATTACHMENT_PATH", Path(tmp_path))
    monkeypatch.setattr(upload_mod, "list_files_in_folder", lambda _p: [str(file_path)])
    monkeypatch.setattr(upload_mod, "append_attachments_uploaded", lambda **_kwargs: True)

    client = _FakeClient(response={"status": "success"})
    summary = upload_mod.upload_attachments_for_study(
        study_uid,
        "",
        client=client,
        verbose=False,
    )

    assert summary["success"] == 1
    assert summary["failed"] == 0
    assert client.calls == 1
    assert pending_mod.get_pending_files(study_uid) == []


def test_upload_failure_marks_pending_and_attempts(tmp_path, monkeypatch):
    study_uid = "study-failure"
    file_name = "voice.wav"
    file_path = _setup_study_attachment(tmp_path, study_uid, file_name=file_name)

    monkeypatch.setattr(config_mod, "ATTACHMENT_PATH", Path(tmp_path))
    monkeypatch.setattr(upload_mod, "ATTACHMENT_PATH", Path(tmp_path))
    monkeypatch.setattr(upload_mod, "list_files_in_folder", lambda _p: [str(file_path)])
    monkeypatch.setattr(upload_mod, "append_attachments_uploaded", lambda **_kwargs: True)

    client = _FakeClient(exc=RuntimeError("network fail"))
    summary = upload_mod.upload_attachments_for_study(
        study_uid,
        "",
        client=client,
        verbose=False,
    )

    assert summary["success"] == 0
    assert summary["failed"] == 1
    assert client.calls == upload_mod._UPLOAD_REQUEST_MAX_ATTEMPTS

    pending_info = pending_mod.get_pending_info(study_uid)
    assert file_name in pending_info
    assert pending_info[file_name]["attempts"] == upload_mod._UPLOAD_REQUEST_MAX_ATTEMPTS
    assert pending_info[file_name]["last_attempt"] is not None


def test_upload_no_files_returns_without_socket_connect(tmp_path, monkeypatch):
    study_uid = "study-empty"

    monkeypatch.setattr(config_mod, "ATTACHMENT_PATH", Path(tmp_path))
    monkeypatch.setattr(upload_mod, "ATTACHMENT_PATH", Path(tmp_path))
    monkeypatch.setattr(upload_mod, "list_files_in_folder", lambda _p: [])

    class _FailConnectClient:
        def connect(self):
            raise AssertionError("connect should not be called when there are no files")

        def disconnect(self):
            raise AssertionError("disconnect should not be called when there are no files")

    monkeypatch.setattr(upload_mod, "SocketClient", _FailConnectClient)

    summary = upload_mod.upload_attachments_for_study(
        study_uid,
        "",
        verbose=False,
    )

    assert summary["total"] == 0
    assert summary["success"] == 0
    assert summary["failed"] == 0
    assert summary["results"] == []


def test_upload_transient_failure_then_success_counts_attempts(tmp_path, monkeypatch):
    study_uid = "study-transient"
    file_name = "transient.txt"
    file_path = _setup_study_attachment(tmp_path, study_uid, file_name=file_name)

    monkeypatch.setattr(config_mod, "ATTACHMENT_PATH", Path(tmp_path))
    monkeypatch.setattr(upload_mod, "ATTACHMENT_PATH", Path(tmp_path))
    monkeypatch.setattr(upload_mod, "list_files_in_folder", lambda _p: [str(file_path)])
    monkeypatch.setattr(upload_mod, "append_attachments_uploaded", lambda **_kwargs: True)

    class _TransientClient:
        def __init__(self):
            self.calls = 0

        def send_request(self, endpoint, params):
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("temporary network glitch")
            return {"status": "success"}

    client = _TransientClient()
    summary = upload_mod.upload_attachments_for_study(
        study_uid,
        "",
        client=client,
        verbose=False,
    )

    assert summary["success"] == 1
    assert summary["failed"] == 0
    assert client.calls == 2

    pending_info = pending_mod.get_pending_info(study_uid)
    assert file_name not in pending_info


def test_upload_stop_on_error_halts_after_first_failed_file(tmp_path, monkeypatch):
    study_uid = "study-stop-on-error"
    first_file = _setup_study_attachment(tmp_path, study_uid, file_name="first.txt")
    second_file = _setup_study_attachment(tmp_path, study_uid, file_name="second.txt")

    monkeypatch.setattr(config_mod, "ATTACHMENT_PATH", Path(tmp_path))
    monkeypatch.setattr(upload_mod, "ATTACHMENT_PATH", Path(tmp_path))
    monkeypatch.setattr(
        upload_mod,
        "list_files_in_folder",
        lambda _p: [str(first_file), str(second_file)],
    )
    monkeypatch.setattr(upload_mod, "append_attachments_uploaded", lambda **_kwargs: True)

    class _AlwaysFailClient:
        def __init__(self):
            self.calls = 0

        def send_request(self, endpoint, params):
            self.calls += 1
            raise RuntimeError("terminal upload error")

    client = _AlwaysFailClient()
    summary = upload_mod.upload_attachments_for_study(
        study_uid,
        "",
        client=client,
        stop_on_error=True,
        verbose=False,
    )

    assert summary["total"] == 2
    assert summary["success"] == 0
    assert summary["failed"] == 1
    assert len(summary["results"]) == 1
    assert summary["results"][0]["file"].endswith("first.txt")

    # first file should consume retry attempts; second file should never be attempted
    assert client.calls == upload_mod._UPLOAD_REQUEST_MAX_ATTEMPTS

    pending_info = pending_mod.get_pending_info(study_uid)
    assert "first.txt" in pending_info
    assert "second.txt" not in pending_info


def test_upload_broadcast_response_is_error_and_stays_pending(tmp_path, monkeypatch):
    study_uid = "study-broadcast"
    file_name = "broadcast.txt"
    file_path = _setup_study_attachment(tmp_path, study_uid, file_name=file_name)

    monkeypatch.setattr(config_mod, "ATTACHMENT_PATH", Path(tmp_path))
    monkeypatch.setattr(upload_mod, "ATTACHMENT_PATH", Path(tmp_path))
    monkeypatch.setattr(upload_mod, "list_files_in_folder", lambda _p: [str(file_path)])
    monkeypatch.setattr(upload_mod, "append_attachments_uploaded", lambda **_kwargs: True)

    client = _FakeClient(response={"type": "broadcast", "status": "success"})
    summary = upload_mod.upload_attachments_for_study(
        study_uid,
        "",
        client=client,
        verbose=False,
    )

    assert summary["total"] == 1
    assert summary["success"] == 0
    assert summary["failed"] == 1
    assert len(summary["results"]) == 1
    assert summary["results"][0]["status"] == "error"
    assert "broadcast" in summary["results"][0]["error"].lower()

    pending_info = pending_mod.get_pending_info(study_uid)
    assert file_name in pending_info


def test_download_mixed_statuses_and_append_calls(tmp_path, monkeypatch):
    study_uid = "study-download"
    out_dir = Path(tmp_path) / study_uid
    out_dir.mkdir(parents=True, exist_ok=True)

    # Existing file should be skipped when overwrite=False
    skipped_path = out_dir / "skip.txt"
    skipped_path.write_bytes(b"existing")

    good_payload = base64.b64encode(b"new-content").decode("utf-8")
    skip_payload = base64.b64encode(b"remote-ignored").decode("utf-8")

    client = _FakeClient(
        response={
            "status": "success",
            "data": {
                "attachments": [
                    {
                        "file_name": "new.txt",
                        "attachment_type": "document",
                        "file_format": "txt",
                        "file_size": 11,
                        "file_exists": True,
                        "attachment_data": good_payload,
                    },
                    {
                        "file_name": "skip.txt",
                        "attachment_type": "document",
                        "file_format": "txt",
                        "file_size": 13,
                        "file_exists": True,
                        "attachment_data": skip_payload,
                    },
                    {
                        "file_name": "missing.wav",
                        "attachment_type": "audio",
                        "file_format": "wav",
                        "file_size": 0,
                        "file_exists": False,
                        "attachment_data": "",
                    },
                    {
                        "file_name": "bad.bin",
                        "attachment_type": "document",
                        "file_format": "bin",
                        "file_size": 9,
                        "file_exists": True,
                        "attachment_data": "!!!not-base64!!!",
                    },
                ]
            },
        }
    )

    monkeypatch.setattr(config_mod, "ATTACHMENT_PATH", Path(tmp_path))
    monkeypatch.setattr(upload_mod, "ATTACHMENT_PATH", Path(tmp_path))
    appended = []
    monkeypatch.setattr(
        upload_mod,
        "append_attachments_uploaded",
        lambda **kwargs: appended.append(kwargs["value"]) or True,
    )

    summary = upload_mod.download_attachments_for_study(
        study_uid,
        client=client,
        overwrite=False,
        verbose=False,
    )

    assert client.calls == 1
    assert summary["total"] == 4
    assert summary["saved"] == 1
    assert summary["skipped"] == 1
    assert summary["failed"] == 2

    by_name = {r["file_name"]: r for r in summary["results"]}
    assert by_name["new.txt"]["status"] == "saved"
    assert by_name["skip.txt"]["status"] == "skipped"
    assert by_name["missing.wav"]["status"] == "error"
    assert by_name["bad.bin"]["status"] == "error"

    assert (out_dir / "new.txt").read_bytes() == b"new-content"
    assert skipped_path.read_bytes() == b"existing"
    assert len(appended) == 2
    assert str(out_dir / "new.txt") in appended
    assert str(skipped_path) in appended


def test_download_raises_on_server_failure(tmp_path, monkeypatch):
    study_uid = "study-download-failed"

    monkeypatch.setattr(config_mod, "ATTACHMENT_PATH", Path(tmp_path))
    monkeypatch.setattr(upload_mod, "ATTACHMENT_PATH", Path(tmp_path))

    client = _FakeClient(response={"status": "error", "error": "boom"})
    with pytest.raises(RuntimeError, match="GetStudyAttachments failed|boom"):
        upload_mod.download_attachments_for_study(
            study_uid,
            client=client,
            verbose=False,
        )


def test_download_names_filter_saves_only_requested_files(tmp_path, monkeypatch):
    study_uid = "study-names-filter"
    out_dir = Path(tmp_path) / study_uid
    out_dir.mkdir(parents=True, exist_ok=True)

    keep_payload = base64.b64encode(b"keep-me").decode("utf-8")
    drop_payload = base64.b64encode(b"drop-me").decode("utf-8")

    client = _FakeClient(
        response={
            "status": "success",
            "data": {
                "attachments": [
                    {
                        "file_name": "keep.txt",
                        "attachment_type": "document",
                        "file_format": "txt",
                        "file_size": 7,
                        "file_exists": True,
                        "attachment_data": keep_payload,
                    },
                    {
                        "file_name": "drop.txt",
                        "attachment_type": "document",
                        "file_format": "txt",
                        "file_size": 7,
                        "file_exists": True,
                        "attachment_data": drop_payload,
                    },
                ]
            },
        }
    )

    monkeypatch.setattr(config_mod, "ATTACHMENT_PATH", Path(tmp_path))
    monkeypatch.setattr(upload_mod, "ATTACHMENT_PATH", Path(tmp_path))
    appended = []
    monkeypatch.setattr(
        upload_mod,
        "append_attachments_uploaded",
        lambda **kwargs: appended.append(kwargs["value"]) or True,
    )

    summary = upload_mod.download_attachments_for_study(
        study_uid,
        client=client,
        names=["keep.txt"],
        overwrite=False,
        verbose=False,
    )

    assert client.calls == 1
    assert summary["total"] == 1
    assert summary["saved"] == 1
    assert summary["skipped"] == 0
    assert summary["failed"] == 0

    assert (out_dir / "keep.txt").read_bytes() == b"keep-me"
    assert not (out_dir / "drop.txt").exists()
    assert appended == [str(out_dir / "keep.txt")]


def test_download_single_attachment_respects_out_path_and_overwrite(tmp_path, monkeypatch):
    study_uid = "study-single-outpath"
    source_dir = Path(tmp_path) / "source"
    source_dir.mkdir(parents=True, exist_ok=True)

    src_file = source_dir / "one.txt"
    src_file.write_bytes(b"v1")

    target_path = Path(tmp_path) / "final" / "one.txt"
    target_path.parent.mkdir(parents=True, exist_ok=True)

    # Simulate internal helper returning a saved file under a different path.
    monkeypatch.setattr(
        upload_mod,
        "download_attachments_for_study",
        lambda *args, **kwargs: {
            "results": [
                {
                    "file_name": "one.txt",
                    "status": "saved",
                    "saved_path": str(src_file),
                }
            ]
        },
    )

    out = upload_mod.download_single_attachment(
        study_uid,
        "one.txt",
        out_path=target_path,
        overwrite=True,
        verbose=False,
    )
    assert out == target_path
    assert target_path.read_bytes() == b"v1"
    assert not src_file.exists()

    # Existing target + overwrite=False should preserve current target content.
    src_file2 = source_dir / "one.txt"
    src_file2.write_bytes(b"v2")
    target_path.write_bytes(b"existing")
    monkeypatch.setattr(
        upload_mod,
        "download_attachments_for_study",
        lambda *args, **kwargs: {
            "results": [
                {
                    "file_name": "one.txt",
                    "status": "saved",
                    "saved_path": str(src_file2),
                }
            ]
        },
    )

    out2 = upload_mod.download_single_attachment(
        study_uid,
        "one.txt",
        out_path=target_path,
        overwrite=False,
        verbose=False,
    )
    assert out2 == target_path
    assert target_path.read_bytes() == b"existing"
    assert src_file2.exists()