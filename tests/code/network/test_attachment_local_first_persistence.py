"""Regression guards for local-first attachment persistence.

Core rule under test: an approved patient attachment (voice / screenshot / AI
output / note) is saved locally first and is NEVER lost because the server is
unavailable, the upload fails, a batch only partially uploaded, or a re-download
hiccups. Server sync is a later, retryable step that must never delete local
files.

Root cause this protects against (fixed 2026-06-16): the patient sync worker
used to ``shutil.rmtree`` the whole local attachment folder after a sync and
re-download from the server; a partial upload or a failed re-download then lost
the local copies permanently.
"""
from pathlib import Path

import PacsClient.utils.config as config_mod
from modules.network import attachment_pending_sync as pending_mod
from modules.network import upload_download_attchments as upload_mod


def _setup_study_attachment(tmp_path, study_uid, file_name="note.txt"):
    study_dir = Path(tmp_path) / study_uid
    study_dir.mkdir(parents=True, exist_ok=True)
    file_path = study_dir / file_name
    file_path.write_text("demo", encoding="utf-8")
    return file_path


# ─────────────────────────────────────────────────────────────────────────
# 1. Offline / server-down upload keeps the local file and marks it pending
# ─────────────────────────────────────────────────────────────────────────
def test_offline_upload_keeps_files_and_marks_pending(tmp_path, monkeypatch):
    study_uid = "study-offline"
    file_path = _setup_study_attachment(tmp_path, study_uid, file_name="REC_offline.wav")

    monkeypatch.setattr(config_mod, "ATTACHMENT_PATH", Path(tmp_path))
    monkeypatch.setattr(upload_mod, "ATTACHMENT_PATH", Path(tmp_path))
    monkeypatch.setattr(upload_mod, "list_files_in_folder", lambda _p: [str(file_path)])
    monkeypatch.setattr(upload_mod, "append_attachments_uploaded", lambda **_k: True)

    class _DeadSocket:
        def connect(self):
            raise OSError("connection refused")

        def disconnect(self):
            raise AssertionError("must not disconnect a socket that never connected")

    monkeypatch.setattr(upload_mod, "SocketClient", _DeadSocket)

    summary = upload_mod.upload_attachments_for_study(study_uid, "", verbose=False)

    # Returns a structured failure instead of raising...
    assert summary["success"] == 0
    assert summary["failed"] == 1
    # ...the local file is untouched...
    assert file_path.exists()
    # ...and it is recorded PendingSync (LocalOnly: saved, never sent) for retry.
    assert "REC_offline.wav" in pending_mod.get_pending_files(study_uid)
    assert pending_mod.get_status(study_uid, "REC_offline.wav") == pending_mod.STATUS_LOCAL_ONLY


# ─────────────────────────────────────────────────────────────────────────
# 2. Partial-success batch: the failed file stays local + pending
# ─────────────────────────────────────────────────────────────────────────
def test_partial_batch_keeps_failed_file_local(tmp_path, monkeypatch):
    study_uid = "study-partial"
    f_ok = _setup_study_attachment(tmp_path, study_uid, file_name="ok.txt")
    f_fail = _setup_study_attachment(tmp_path, study_uid, file_name="REC_fail.wav")

    monkeypatch.setattr(config_mod, "ATTACHMENT_PATH", Path(tmp_path))
    monkeypatch.setattr(upload_mod, "ATTACHMENT_PATH", Path(tmp_path))
    monkeypatch.setattr(upload_mod, "list_files_in_folder", lambda _p: [str(f_ok), str(f_fail)])
    monkeypatch.setattr(upload_mod, "append_attachments_uploaded", lambda **_k: True)

    class _MixedClient:
        def __init__(self):
            self.calls = 0

        def send_request(self, endpoint, params):
            self.calls += 1
            if params.get("file_name") == "ok.txt":
                return {"status": "success"}
            return {"status": "error", "error": "file too large"}

    summary = upload_mod.upload_attachments_for_study(
        study_uid, "", client=_MixedClient(), verbose=False
    )

    assert summary["success"] == 1
    assert summary["failed"] == 1
    # Neither file is ever deleted by the upload step.
    assert f_ok.exists() and f_fail.exists()
    pending = pending_mod.get_pending_files(study_uid)
    assert "REC_fail.wav" in pending      # failed file kept pending for next sync
    assert "ok.txt" not in pending        # confirmed upload cleared from pending


# ─────────────────────────────────────────────────────────────────────────
# 3. Reconcile is non-destructive and survives a server failure
# ─────────────────────────────────────────────────────────────────────────
def test_reconcile_pulls_missing_only_and_never_overwrites(tmp_path, monkeypatch):
    from PacsClient.pacs.patient_tab.utils import patient_sync_service as sync_mod

    study_uid = "study-reconcile"
    study_dir = Path(tmp_path) / study_uid
    study_dir.mkdir(parents=True, exist_ok=True)
    voice = study_dir / "REC_1.wav"; voice.write_bytes(b"audio")
    note = study_dir / "note.txt"; note.write_text("hi", encoding="utf-8")

    monkeypatch.setattr(config_mod, "ATTACHMENT_PATH", Path(tmp_path))
    monkeypatch.setattr(upload_mod, "ATTACHMENT_PATH", Path(tmp_path))

    seen = {}

    def fake_download(uid, *, overwrite=False, verbose=True, **_kw):
        seen["overwrite"] = overwrite
        seen["uid"] = uid
        return {"saved": 0, "skipped": 2, "failed": 0}

    monkeypatch.setattr(upload_mod, "download_attachments_for_study", fake_download)

    sync_mod.reconcile_attachments_from_server(study_uid, verbose=False)

    assert seen["uid"] == study_uid
    assert seen["overwrite"] is False        # existing local files must never be overwritten
    assert voice.exists() and note.exists()  # nothing deleted


def test_reconcile_keeps_local_when_server_fails(tmp_path, monkeypatch):
    from PacsClient.pacs.patient_tab.utils import patient_sync_service as sync_mod

    study_uid = "study-reconcile-fail"
    study_dir = Path(tmp_path) / study_uid
    study_dir.mkdir(parents=True, exist_ok=True)
    voice = study_dir / "REC_1.wav"; voice.write_bytes(b"audio")

    monkeypatch.setattr(config_mod, "ATTACHMENT_PATH", Path(tmp_path))
    monkeypatch.setattr(upload_mod, "ATTACHMENT_PATH", Path(tmp_path))

    def boom(*_a, **_k):
        raise RuntimeError("server down")

    monkeypatch.setattr(upload_mod, "download_attachments_for_study", boom)

    out = sync_mod.reconcile_attachments_from_server(study_uid)

    assert out == {}            # failure is swallowed, not raised
    assert voice.exists()       # a failed reconcile must NOT delete local data


# ─────────────────────────────────────────────────────────────────────────
# 4. The destructive rmtree must never come back to the sync service
# ─────────────────────────────────────────────────────────────────────────
def test_sync_service_never_rmtrees_local_attachments():
    import inspect
    from PacsClient.pacs.patient_tab.utils import patient_sync_service as sync_mod

    src = inspect.getsource(sync_mod)
    assert "rmtree" not in src, (
        "patient_sync_service must never delete the local attachment folder — "
        "local attachments must survive a failed/partial sync"
    )


# ─────────────────────────────────────────────────────────────────────────
# 5. Status lifecycle derives correctly from the manifest
# ─────────────────────────────────────────────────────────────────────────
def test_get_status_lifecycle_transitions(tmp_path, monkeypatch):
    monkeypatch.setattr(config_mod, "ATTACHMENT_PATH", Path(tmp_path))

    study_uid = "study-status"
    fn = "voice.wav"

    # Unknown / never-tracked file reads as Synced (nothing pending).
    assert pending_mod.get_status(study_uid, fn) == pending_mod.STATUS_SYNCED

    pending_mod.mark_pending(study_uid, fn)
    assert pending_mod.get_status(study_uid, fn) == pending_mod.STATUS_LOCAL_ONLY

    pending_mod.record_attempt(study_uid, fn)
    assert pending_mod.get_status(study_uid, fn) == pending_mod.STATUS_PENDING_SYNC

    pending_mod.mark_synced(study_uid, fn)
    assert pending_mod.get_status(study_uid, fn) == pending_mod.STATUS_SYNCED
