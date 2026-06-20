"""Guard: deleting a study's local DICOM must NEVER delete an approved,
not-yet-synced attachment (e.g. a voice recording).  (Root cause of the 47183
"approved voice gone after reopen" report, 2026-06-20.)

The main-page Delete button (`_on_delete_clicked` -> `_delete_local_studies`)
used to `shutil.rmtree(ATTACHMENT_PATH/<study_uid>)` unconditionally, wiping the
just-recorded local-only voice along with the (re-downloadable) DICOM.  The fix
deletes ONLY attachments the server already has (recorded in
`studies.attachments_uploaded`) and KEEPS everything else.

These tests pin the pure decision helpers and the actual on-disk behaviour, plus
a source-pin so a future refactor can't silently restore the blanket delete.
"""
import inspect
import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# Module-level pure helpers — no QApplication needed to import or call them.
import PacsClient.pacs.workstation_ui.home_ui.patient_table_widget as ptw  # noqa: E402


# ----------------------------------------------------- partition (pure) ----

def test_partition_keeps_unsynced_and_deletes_only_confirmed():
    synced = Path("/data/att/STUDY/uploaded.wav")
    unsynced = Path("/data/att/STUDY/REC_20260620_115837.wav")  # the 47183 file
    confirmed = {str(synced)}
    deletable, kept = ptw._partition_attachments_for_delete(
        [synced, unsynced], confirmed
    )
    assert deletable == [synced]
    assert kept == [unsynced], "an unsynced approved recording must be kept"


def test_partition_empty_confirmed_keeps_everything():
    # Server confirms nothing (offline / never uploaded) -> nothing is deletable.
    files = [Path("/a/REC_1.wav"), Path("/a/REC_2.wav")]
    deletable, kept = ptw._partition_attachments_for_delete(files, set())
    assert deletable == []
    assert kept == files


# ------------------------------------------- on-disk delete behaviour ----

def _make(d: Path, name: str) -> Path:
    p = d / name
    p.write_bytes(b"x")
    return p


def test_delete_keeps_unsynced_voice_on_disk(tmp_path, monkeypatch):
    study = tmp_path / "STUDY_UID"
    study.mkdir()
    synced = _make(study, "uploaded_report.pdf")
    voice = _make(study, "REC_20260620_115837.wav")  # approved, never synced

    monkeypatch.setattr(
        ptw, "_server_confirmed_attachment_paths",
        lambda uid: {str(synced.resolve())},
    )

    deleted, kept = ptw._delete_synced_attachments_only("STUDY_UID", study)

    assert deleted == 1 and kept == 1
    assert not synced.exists(), "server-confirmed attachment should be removed"
    assert voice.exists(), "approved unsynced voice must survive local delete"
    assert study.exists(), "folder must remain while it still holds a kept file"


def test_delete_all_unsynced_keeps_folder_and_files(tmp_path, monkeypatch):
    # Exact 47183 scenario: only a fresh local voice, nothing on the server.
    study = tmp_path / "STUDY_UID"
    study.mkdir()
    voice = _make(study, "REC_20260620_115837.wav")
    monkeypatch.setattr(ptw, "_server_confirmed_attachment_paths", lambda uid: set())

    deleted, kept = ptw._delete_synced_attachments_only("STUDY_UID", study)

    assert deleted == 0 and kept == 1
    assert voice.exists(), "the only (unsynced) recording must NOT be deleted"
    assert study.exists()


def test_delete_all_synced_removes_folder(tmp_path, monkeypatch):
    study = tmp_path / "STUDY_UID"
    study.mkdir()
    a = _make(study, "a.pdf")
    b = _make(study, "b.png")
    monkeypatch.setattr(
        ptw, "_server_confirmed_attachment_paths",
        lambda uid: {str(a.resolve()), str(b.resolve())},
    )

    deleted, kept = ptw._delete_synced_attachments_only("STUDY_UID", study)

    assert deleted == 2 and kept == 0
    assert not study.exists(), "folder is removed only when nothing needs keeping"


# --------------------------------------------------------- source pins ----

def test_delete_local_studies_is_gated_not_blanket():
    src = inspect.getsource(ptw.PatientTableWidget._delete_local_studies)
    # The protective path must be present...
    assert "_delete_synced_attachments_only" in src, (
        "local-study delete must route attachments through the keep-unsynced path"
    )
    assert "AIPACS_DELETE_KEEPS_UNSYNCED_ATTACHMENTS" in src, (
        "the keep-unsynced behaviour must be the (default-on) gated path"
    )
    # ...and the only rmtree(attachment_path) must sit behind the disabled flag,
    # never as the default. The attachment rmtree appears once, in the
    # `if not keep_unsynced:` branch.
    assert src.count("shutil.rmtree(attachment_path)") <= 1
