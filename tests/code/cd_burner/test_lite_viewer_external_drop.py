"""Guard: the portable Lite Viewer must import DICOM dropped from the CD.

Root cause (Roshana CT test CD, 2026-07-12): the burned disc was correct — the
files were there, the DICOMDIR was valid, discovery worked — but dropping a file
or folder from File Explorer onto the viewer did nothing.

`ImageCanvas.dragEnterEvent` accepted ONLY the viewer's *internal* mime type
(`application/x-aipacs-series-index`, i.e. a series dragged from its own series
list). An Explorer drop arrives as `text/uri-list`, so it fell into
`event.ignore()` → Windows showed the "no entry" cursor and nothing happened.
`LiteViewerWindow` never called `setAcceptDrops` at all. **External drag-and-drop
was simply not implemented.**

It was NOT: elevation (the exe manifest is `asInvoker`), read-only media, path
resolution, or an extension filter — all of those were already correct.

These tests pin the fix, and pin that the *internal* series drag still works.
"""

import os
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pydicom = pytest.importorskip("pydicom")

from modules.cd_burner.portable_viewer import media_scan  # noqa: E402


# ---------------------------------------------------------------------------
# Synthetic patient CD (mirrors the real disc layout: PT/ST/SE/IM, NO extension)
# ---------------------------------------------------------------------------

STUDY_UID = "1.2.826.0.1.3680043.8.498.11111111111111111111111111111111"
SERIES_A = "1.2.826.0.1.3680043.8.498.22222222222222222222222222222222"
SERIES_B = "1.2.826.0.1.3680043.8.498.33333333333333333333333333333333"


def _write_instance(path: Path, series_uid: str, instance_number: int,
                    series_number: int = 1) -> None:
    from pydicom.dataset import Dataset, FileMetaDataset
    from pydicom.uid import CTImageStorage, ExplicitVRLittleEndian, generate_uid

    ds = Dataset()
    ds.PatientName = "TEST^PATIENT"
    ds.PatientID = "PT1"
    ds.StudyInstanceUID = STUDY_UID
    ds.SeriesInstanceUID = series_uid
    ds.SOPInstanceUID = generate_uid()
    ds.SOPClassUID = CTImageStorage
    ds.Modality = "CT"
    ds.SeriesNumber = series_number
    ds.InstanceNumber = instance_number
    # Required by pydicom's DICOMDIR record builders (a real disc has these).
    ds.StudyDate = "20260712"
    ds.StudyTime = "120000"
    ds.StudyID = "1"
    ds.AccessionNumber = "ACC1"
    ds.ContentDate = "20260712"
    ds.ContentTime = "120000"
    ds.ImageType = ["ORIGINAL", "PRIMARY"]
    ds.Rows = 4
    ds.Columns = 4
    ds.BitsAllocated = 16
    ds.BitsStored = 16
    ds.HighBit = 15
    ds.PixelRepresentation = 0
    ds.SamplesPerPixel = 1
    ds.PhotometricInterpretation = "MONOCHROME2"
    ds.PixelData = (b"\x00\x01" * 16)

    ds.file_meta = FileMetaDataset()
    ds.file_meta.MediaStorageSOPClassUID = CTImageStorage
    ds.file_meta.MediaStorageSOPInstanceUID = ds.SOPInstanceUID
    ds.file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
    ds.is_little_endian = True
    ds.is_implicit_VR = False

    path.parent.mkdir(parents=True, exist_ok=True)
    ds.save_as(str(path), write_like_original=False)


@pytest.fixture
def fake_cd(tmp_path: Path) -> Path:
    """A patient-CD-shaped tree with EXTENSION-LESS instances, like a real disc."""
    root = tmp_path / "CD"
    se0 = root / "PT000000" / "ST000000" / "SE000000"
    se1 = root / "PT000000" / "ST000000" / "SE000001"
    _write_instance(se0 / "IM000000", SERIES_A, 1, series_number=1)
    for i in range(3):
        _write_instance(se1 / f"IM{i:06d}", SERIES_B, i + 1, series_number=2)
    # Non-DICOM clutter that lives on every burned disc.
    (root / "autorun.inf").write_text("[autorun]\n", encoding="utf-8")
    (root / "START_HERE.txt").write_text("hello", encoding="utf-8")
    (root / "VIEWER").mkdir()
    (root / "VIEWER" / "AIPacsLiteViewer.exe").write_bytes(b"MZ not dicom")
    return root


# ---------------------------------------------------------------------------
# Discovery — every drop shape the spec requires
# ---------------------------------------------------------------------------

def test_drop_a_single_extensionless_file(fake_cd: Path):
    """A patient CD stores `IM000000` with NO extension — content, not suffix."""
    result = media_scan.scan_paths([str(fake_cd / "PT000000/ST000000/SE000000/IM000000")])
    assert result.source == "filescan"
    assert len(result.series) == 1
    assert result.total_images == 1


def test_drop_several_files_of_one_series(fake_cd: Path):
    files = [str(fake_cd / f"PT000000/ST000000/SE000001/IM{i:06d}") for i in range(3)]
    result = media_scan.scan_paths(files)
    assert len(result.series) == 1
    assert result.total_images == 3


def test_drop_a_series_folder(fake_cd: Path):
    result = media_scan.scan_paths([str(fake_cd / "PT000000/ST000000/SE000001")])
    assert len(result.series) == 1
    assert result.total_images == 3


def test_drop_a_study_folder_finds_every_series(fake_cd: Path):
    result = media_scan.scan_paths([str(fake_cd / "PT000000/ST000000")])
    assert len(result.series) == 2
    assert result.total_images == 4


def test_drop_the_disc_root_with_dicomdir(fake_cd: Path):
    """A real disc root has DICOMDIR — use the standard File-set reader."""
    from pydicom.fileset import FileSet

    fs = FileSet()
    for path in sorted(fake_cd.rglob("IM*")):
        fs.add(str(path))
    fs.write(str(fake_cd / "FS"))          # writes its own tree + DICOMDIR
    root = fake_cd / "FS"

    result = media_scan.scan_paths([str(root)])
    assert result.source == "dicomdir"
    assert len(result.series) == 2
    assert result.total_images == 4

    # Dropping the DICOMDIR file itself must behave identically.
    result2 = media_scan.scan_paths([str(root / "DICOMDIR")])
    assert result2.source == "dicomdir"
    assert result2.total_images == 4


def test_drop_mixed_files_and_folders(fake_cd: Path):
    result = media_scan.scan_paths([
        str(fake_cd / "PT000000/ST000000/SE000000/IM000000"),
        str(fake_cd / "PT000000/ST000000/SE000001"),
    ])
    assert len(result.series) == 2
    assert result.total_images == 4


def test_the_viewer_folder_and_junk_are_not_imported(fake_cd: Path):
    """Dropping the whole disc must not try to parse the viewer exe / autorun."""
    result = media_scan.scan_paths([str(fake_cd)])
    assert len(result.series) == 2
    assert result.total_images == 4
    for series in result.series:
        for inst in series.instances:
            assert "VIEWER" not in inst.path


def test_dropping_non_dicom_reports_a_clear_error(fake_cd: Path):
    result = media_scan.scan_paths([str(fake_cd / "autorun.inf")])
    assert not result.series
    assert result.errors


def test_the_viewer_own_bundle_is_never_used_as_a_media_root(tmp_path, fake_cd: Path):
    """CLINICAL SAFETY: the bundle ships pydicom's ~25 sample .dcm files.

    RUN_VIEWER.cmd copies the viewer to %TEMP% and runs it from there, so the
    exe's folder is a media-root candidate. If --import-folder is ever lost, the
    fallback probe would find those samples and show the patient SOMEONE ELSE'S
    test images instead of their study.
    """
    bundle = tmp_path / "AIPacsLiteViewer"
    internal = bundle / "_internal" / "pydicom" / "data"
    internal.mkdir(parents=True)
    (bundle / "AIPacsLiteViewer.exe").write_bytes(b"MZ")
    (bundle / "_internal" / "base_library.zip").write_bytes(b"PK")
    # pydicom's sample data, exactly as it ships inside the bundle:
    _write_instance(internal / "sample.dcm", "9.9.9.NOT.THE.PATIENT", 1)

    assert media_scan._is_viewer_bundle_dir(bundle)

    # No CLI folder → the exe dir must NOT become the media root.
    root = media_scan.discover_media_root(None, exe_dir=str(bundle))
    assert root is None or Path(root) != bundle

    # And the real media still resolves normally.
    root = media_scan.discover_media_root(str(fake_cd), exe_dir=str(bundle))
    assert Path(root) == fake_cd


def test_internal_payload_dir_is_never_scanned(tmp_path):
    """`_internal` (PyInstaller payload) must be skipped by the file walk."""
    root = tmp_path / "media"
    internal = root / "_internal" / "pydicom" / "data"
    internal.mkdir(parents=True)
    _write_instance(internal / "sample.dcm", "9.9.9.NOT.THE.PATIENT", 1)

    result = media_scan.scan_paths([str(root)])
    assert not result.series, "pydicom's bundled samples must never be imported"


def test_scan_paths_never_raises():
    for junk in ([], None, ["/no/such/path"], [""]):
        result = media_scan.scan_paths(junk)
        assert result.series == []
        assert result.errors


def test_import_never_writes_to_the_source_media(fake_cd: Path):
    """Read-only optical media: the import must not create sidecars/thumbnails."""
    before = {str(p): p.stat().st_mtime for p in fake_cd.rglob("*") if p.is_file()}
    media_scan.scan_paths([str(fake_cd)])
    after = {str(p): p.stat().st_mtime for p in fake_cd.rglob("*") if p.is_file()}
    assert set(after) == set(before), "import created or deleted files on the source"
    assert after == before, "import modified files on the source"


# ---------------------------------------------------------------------------
# Qt layer — the drop must actually be ACCEPTED (this is what was broken)
# ---------------------------------------------------------------------------

pytest.importorskip("PySide6")


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    yield app


def _url_mime(paths):
    from PySide6.QtCore import QMimeData, QUrl
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(p)) for p in paths])
    return mime


def test_local_paths_from_mime_extracts_dropped_files(qapp, fake_cd: Path):
    from modules.cd_burner.portable_viewer.viewer_app import local_paths_from_mime

    target = fake_cd / "PT000000/ST000000/SE000000/IM000000"
    paths = local_paths_from_mime(_url_mime([target]))
    assert len(paths) == 1
    assert Path(paths[0]) == target


def test_external_url_drop_is_recognized_not_ignored(qapp, fake_cd: Path):
    """THE regression: a text/uri-list payload used to be ignored outright."""
    from modules.cd_burner.portable_viewer.viewer_app import (
        _drop_payload_kind,
        build_series_mime,
    )

    assert _drop_payload_kind(_url_mime([fake_cd])) == "paths"
    # The internal series drag must keep working, unchanged.
    assert _drop_payload_kind(build_series_mime(0)) == "series"


def test_canvas_accepts_an_external_file_drop_and_reports_the_paths(qapp, fake_cd: Path):
    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtGui import QDragEnterEvent, QDropEvent

    from modules.cd_burner.portable_viewer.viewer_app import ImageCanvas

    canvas = ImageCanvas()
    assert canvas.acceptDrops()

    target = fake_cd / "PT000000/ST000000/SE000001"
    mime = _url_mime([target])
    pos = QPointF(10, 10)

    enter = QDragEnterEvent(pos.toPoint(), Qt.CopyAction, mime,
                            Qt.LeftButton, Qt.NoModifier)
    canvas.dragEnterEvent(enter)
    assert enter.isAccepted(), "the pane must accept an Explorer file drop"

    seen = []
    canvas.on_paths_dropped = seen.append
    drop = QDropEvent(pos, Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
    canvas.dropEvent(drop)

    assert drop.isAccepted()
    assert len(seen) == 1
    assert Path(seen[0][0]) == target


def test_internal_series_drop_still_loads_that_series(qapp):
    """No regression: dragging a series from the list onto a pane still works."""
    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtGui import QDropEvent

    from modules.cd_burner.portable_viewer.viewer_app import (
        ImageCanvas,
        build_series_mime,
    )

    canvas = ImageCanvas()
    dropped = []
    canvas.on_series_dropped = dropped.append
    canvas.on_paths_dropped = lambda paths: pytest.fail("wrong handler for a series drag")

    mime = build_series_mime(7)  # keep a reference: QDropEvent does not own it
    drop = QDropEvent(QPointF(5, 5), Qt.CopyAction, mime,
                      Qt.LeftButton, Qt.NoModifier)
    canvas.dropEvent(drop)

    assert drop.isAccepted()
    assert dropped == [7]


def test_window_is_a_drop_target(qapp):
    """Dropping anywhere on the window (not just a pane) must work."""
    from modules.cd_burner.portable_viewer.viewer_app import LiteViewerWindow

    window = LiteViewerWindow(media_root=None, show_welcome=False)
    try:
        assert window.acceptDrops()
        assert hasattr(window, "_import_dropped_paths")
    finally:
        window.close()
