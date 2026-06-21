"""Regression guards for local↔server voice/attachment de-duplication.

Root cause (fixed 2026-06-21): the upload server stores each uploaded file
under a unique 8-hex-char id prefix ("<id>_<original>", e.g.
``0c634fb7_REC_20260621_145327.wav``). On patient reopen,
``download_attachments_for_study`` fetched the server copy; because its name
differs from the local original (``REC_20260621_145327.wav``) the exact-name
skip missed and a SECOND file was written — so one synced voice showed up twice
(two -> four). These guards lock in the dedup that recognises
``"<id>_<original>"`` and ``"<original>"`` as the SAME logical attachment, and
the non-destructive UI collapse that hides any already-duplicated file.

The fix is flag-gated (``AIPACS_ATTACHMENT_DEDUP``, default ON) and must never
delete a local file (offline-first / unsynced voices are preserved).
"""
import base64
from pathlib import Path

import PacsClient.utils.config as config_mod
from modules.network import attachment_pending_sync as pend
from modules.network import upload_download_attchments as upload_mod

_ROOT = Path(__file__).resolve().parents[3]
_DROPDOWN = (_ROOT / "PacsClient" / "pacs" / "patient_tab" / "ui" / "patient_ui"
             / "patient_toolbar" / "attachments_dropdown.py")


# ─────────────────────────── pure matching helpers ───────────────────────────
def test_strip_server_id_prefix():
    assert pend.strip_server_id_prefix("0c634fb7_REC_20260621_145327.wav") == "REC_20260621_145327.wav"
    # no prefix -> unchanged; idempotent
    assert pend.strip_server_id_prefix("REC_20260621_145327.wav") == "REC_20260621_145327.wav"
    # not an 8-hex token -> not stripped (don't over-strip real names)
    assert pend.strip_server_id_prefix("report_final.png") == "report_final.png"
    assert pend.strip_server_id_prefix("12345_x.wav") == "12345_x.wav"   # 5 chars
    assert pend.strip_server_id_prefix("zzzzzzzz_x.wav") == "zzzzzzzz_x.wav"  # not hex


def test_identity_key_matches_across_prefix():
    a = pend.attachment_identity_key("REC_20260621_145327.wav")
    b = pend.attachment_identity_key("0c634fb7_REC_20260621_145327.wav")
    assert a == b                          # same logical attachment
    assert a != pend.attachment_identity_key("REC_20260621_145631.wav")  # different recording


def test_find_local_duplicate_precedence():
    local = ["REC_20260621_145327.wav", "note.txt"]
    sizes = {"REC_20260621_145327.wav": 1000, "note.txt": 4}
    # server's prefixed copy of the same file -> matches the local original
    assert pend.find_local_duplicate(
        "0c634fb7_REC_20260621_145327.wav", local, server_size=1000, local_sizes=sizes
    ) == "REC_20260621_145327.wav"
    # genuinely new server file -> no match (must be downloaded)
    assert pend.find_local_duplicate(
        "b4377d31_REC_20260621_150000.wav", local, server_size=2000, local_sizes=sizes
    ) is None
    # same name-key but CONFLICTING size -> rejected, treated as not-a-dup
    assert pend.find_local_duplicate(
        "0c634fb7_REC_20260621_145327.wav", local, server_size=999, local_sizes=sizes
    ) is None
    # exact name already present
    assert pend.find_local_duplicate("note.txt", local) == "note.txt"
    # size unknown on either side -> name-key alone is enough
    assert pend.find_local_duplicate(
        "0c634fb7_REC_20260621_145327.wav", local
    ) == "REC_20260621_145327.wav"


def test_choose_canonical_collapses_prefixed_duplicate():
    files = ["REC_A.wav", "0c634fb7_REC_A.wav", "REC_B.wav"]
    # prefers the prefix-free original; collapses the pair to one
    assert pend.choose_canonical_attachment_names(files) == {"REC_A.wav", "REC_B.wav"}
    # if ONLY the prefixed copy exists, keep it (never drop the only copy)
    assert pend.choose_canonical_attachment_names(["a7537e63_REC_C.wav"]) == {"a7537e63_REC_C.wav"}
    # two server copies of the same file collapse to one (stable lexicographic pick)
    assert pend.choose_canonical_attachment_names(
        ["a7537e63_REC_C.wav", "0ddc6c98_REC_C.wav"]
    ) == {"0ddc6c98_REC_C.wav"}


# ─────────────────────── download-layer integration guards ───────────────────
class _FakeServerClient:
    """Returns a fixed GetStudyAttachments response (mimics the real server,
    which stores uploads under an id prefix)."""

    def __init__(self, items):
        self._items = items
        self.calls = 0

    def send_request(self, endpoint, params):
        self.calls += 1
        assert endpoint == "GetStudyAttachments"
        return {"status": "success", "data": {"attachments": self._items}}


def _server_item(file_name, content=b"audio-bytes"):
    return {
        "file_name": file_name,
        "attachment_type": "audio",
        "file_format": "wav",
        "file_size": len(content),
        "file_exists": True,
        "attachment_data": base64.b64encode(content).decode("ascii"),
    }


def _audio_files(d):
    return sorted(p.name for p in Path(d).iterdir() if p.suffix == ".wav")


def _patch_paths(tmp_path, monkeypatch):
    monkeypatch.setattr(config_mod, "ATTACHMENT_PATH", Path(tmp_path))
    monkeypatch.setattr(upload_mod, "ATTACHMENT_PATH", Path(tmp_path))
    monkeypatch.setattr(upload_mod, "append_attachments_uploaded", lambda **_k: True)


def test_one_synced_voice_not_duplicated_on_reopen(tmp_path, monkeypatch):
    """Acceptance #1: record one voice, sync, reopen -> appears once."""
    study_uid = "study-dedup-1"
    study_dir = tmp_path / study_uid
    study_dir.mkdir(parents=True)
    content = b"the-voice-bytes"
    (study_dir / "REC_20260621_145327.wav").write_bytes(content)

    _patch_paths(tmp_path, monkeypatch)
    client = _FakeServerClient([_server_item("0c634fb7_REC_20260621_145327.wav", content)])
    summary = upload_mod.download_attachments_for_study(study_uid, client=client, verbose=False)

    assert summary["saved"] == 0
    assert summary["deduped"] == 1
    assert _audio_files(study_dir) == ["REC_20260621_145327.wav"]   # NO second file


def test_two_synced_voices_stay_two_across_repeated_reopens(tmp_path, monkeypatch):
    """Acceptance #2: two voices synced -> exactly two after reopen, and stable
    across several reopens (never four/eight)."""
    study_uid = "study-dedup-2"
    study_dir = tmp_path / study_uid
    study_dir.mkdir(parents=True)
    c1, c2 = b"voice-one", b"voice-two-is-longer"
    (study_dir / "REC_20260621_145327.wav").write_bytes(c1)
    (study_dir / "REC_20260621_145631.wav").write_bytes(c2)
    _patch_paths(tmp_path, monkeypatch)

    items = [
        _server_item("a7537e63_REC_20260621_145327.wav", c1),
        _server_item("a7537e63_REC_20260621_145631.wav", c2),
    ]
    for _ in range(4):  # reopen several times
        client = _FakeServerClient(items)
        summary = upload_mod.download_attachments_for_study(study_uid, client=client, verbose=False)
        assert summary["saved"] == 0
        assert summary["deduped"] == 2
        assert _audio_files(study_dir) == [
            "REC_20260621_145327.wav", "REC_20260621_145631.wav",
        ]


def test_genuinely_new_server_voice_is_downloaded(tmp_path, monkeypatch):
    """A different recording that exists only on the server (e.g. recorded on
    another workstation) must still be pulled — dedup must not hide it."""
    study_uid = "study-dedup-new"
    study_dir = tmp_path / study_uid
    study_dir.mkdir(parents=True)
    (study_dir / "REC_20260621_145327.wav").write_bytes(b"local-voice")
    _patch_paths(tmp_path, monkeypatch)

    client = _FakeServerClient([_server_item("b4377d31_REC_20260621_150000.wav", b"remote-voice")])
    summary = upload_mod.download_attachments_for_study(study_uid, client=client, verbose=False)

    assert summary["saved"] == 1
    assert summary["deduped"] == 0
    assert _audio_files(study_dir) == [
        "REC_20260621_145327.wav", "b4377d31_REC_20260621_150000.wav",
    ]


def test_dedup_never_deletes_local_unsynced_voice(tmp_path, monkeypatch):
    """Offline-first: a local-only voice the server doesn't know about must
    survive a reconcile untouched."""
    study_uid = "study-dedup-local-only"
    study_dir = tmp_path / study_uid
    study_dir.mkdir(parents=True)
    (study_dir / "REC_LOCAL_ONLY.wav").write_bytes(b"unsynced")
    _patch_paths(tmp_path, monkeypatch)

    # server returns nothing for this study
    client = _FakeServerClient([])
    upload_mod.download_attachments_for_study(study_uid, client=client, verbose=False)
    assert _audio_files(study_dir) == ["REC_LOCAL_ONLY.wav"]   # kept


def test_dedup_flag_off_restores_legacy_duplicate(tmp_path, monkeypatch):
    """AIPACS_ATTACHMENT_DEDUP=0 must restore the byte-identical legacy
    behaviour (server copy written as a second file)."""
    study_uid = "study-dedup-off"
    study_dir = tmp_path / study_uid
    study_dir.mkdir(parents=True)
    content = b"voiceX"
    (study_dir / "REC_20260621_145327.wav").write_bytes(content)
    _patch_paths(tmp_path, monkeypatch)
    monkeypatch.setenv("AIPACS_ATTACHMENT_DEDUP", "0")

    client = _FakeServerClient([_server_item("0c634fb7_REC_20260621_145327.wav", content)])
    summary = upload_mod.download_attachments_for_study(study_uid, client=client, verbose=False)

    assert summary["saved"] == 1            # legacy: writes the prefixed second copy
    assert summary["deduped"] == 0
    assert _audio_files(study_dir) == [
        "0c634fb7_REC_20260621_145327.wav", "REC_20260621_145327.wav",
    ]


# ─────────────────────────── UI render-layer guard ───────────────────────────
def test_attachment_panels_collapse_duplicates_source_pin():
    """Both the audio and image panels must collapse on-disk duplicates before
    rendering (so already-duplicated files show once), and the collapse must be
    NON-DESTRUCTIVE (never deletes)."""
    src = _DROPDOWN.read_text(encoding="utf-8", errors="ignore")
    assert "_collapse_duplicate_attachment_files" in src
    # used by BOTH panels (audio + image) right after listing files
    assert src.count("files = _collapse_duplicate_attachment_files(files)") == 2
    # the collapse helper must never remove files from disk
    i = src.index("def _collapse_duplicate_attachment_files")
    body = src[i:i + 1400]
    assert "os.remove" not in body
    assert "unlink" not in body
    assert "rmtree" not in body
