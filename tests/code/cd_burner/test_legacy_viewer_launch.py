"""Both supported AI-PACS viewers must receive their own media-input contract."""
import json
import hashlib
from pathlib import Path
import pytest
from modules.cd_burner import cd_burn_manager as manager


def test_legacy_launch_passes_root_dicomdir_and_avoids_default_launcher(tmp_path, monkeypatch):
    source = tmp_path / 'legacy'
    source.mkdir()
    exe = source / 'AiPacs.exe'
    exe.write_bytes(b'MZ synthetic legacy')
    # An unrelated default launcher nearby must not override the legacy contract.
    (tmp_path / 'AIPacsViewer.exe').write_bytes(b'MZ synthetic launcher')
    monkeypatch.setattr(manager, 'detect_viewer_launch_mode', lambda path: 'legacy_dicomdir', raising=False)
    stage = tmp_path / 'media'
    stage.mkdir()
    (stage / 'DICOMDIR').write_bytes(b'synthetic unchanged index')
    worker = manager.CDBurnWorker(studies=[], light_viewer_path=str(exe), burn_to_disc=False)
    worker._copy_light_viewer(str(stage))
    cmd = (stage / 'RUN_VIEWER.cmd').read_text(encoding='utf-8')
    assert '--import-folder' not in cmd
    assert '"%~dp0VIEWER\\AiPacs.exe" "%~dp0DICOMDIR"' in cmd
    assert not (stage / 'AIPacsViewer.exe').exists()
    info = json.loads((stage / 'AIPACS_MEDIA_INFO.json').read_text(encoding='utf-8'))
    assert info['viewer_launch_mode'] == 'legacy_dicomdir'
    assert info['viewer_launcher_primary'] == 'RUN_VIEWER.cmd'
    assert (stage / 'DICOMDIR').read_bytes() == b'synthetic unchanged index'


def test_default_viewer_retains_import_folder_launch(tmp_path):
    source = tmp_path / 'default'
    source.mkdir()
    exe = source / 'AIPacsLiteViewer.exe'
    exe.write_bytes(b'MZ synthetic default')
    stage = tmp_path / 'media'
    stage.mkdir()
    worker = manager.CDBurnWorker(studies=[], light_viewer_path=str(exe), burn_to_disc=False)
    worker._copy_light_viewer(str(stage))
    cmd = (stage / 'RUN_VIEWER.cmd').read_text(encoding='utf-8')
    assert '"%~dp0VIEWER\\AIPacsLiteViewer.exe" --import-folder "%~dp0"' in cmd


def test_detection_uses_verified_bytes_not_filename(tmp_path, monkeypatch):
    from modules.cd_burner import viewer_launch
    known = b'MZ synthetic verified legacy'
    monkeypatch.setattr(viewer_launch, 'LEGACY_AIPACS_SHA256', hashlib.sha256(known).hexdigest())
    renamed = tmp_path / 'renamed.exe'
    renamed.write_bytes(known)
    assert viewer_launch.detect_viewer_launch_mode(renamed) == viewer_launch.LEGACY_DICOMDIR
    unrelated = tmp_path / 'AiPacs.exe'
    unrelated.write_bytes(b'MZ unrelated')
    assert viewer_launch.detect_viewer_launch_mode(unrelated) == viewer_launch.IMPORT_FOLDER


@pytest.mark.parametrize('mode', ['legacy_dicomdir', 'aipacs_import_folder'])
def test_both_launch_modes_preserve_readable_dicomdir_and_pixels(tmp_path, monkeypatch, mode):
    from tests.code.cd_burner.conftest import write_ct_slice
    from modules.cd_burner.dicomdir_builder import DicomDirBuilder
    from modules.cd_burner.portable_viewer.media_scan import scan_media
    from pydicom.fileset import FileSet
    from pydicom import dcmread
    source = tmp_path / 'source'
    write_ct_slice(source, '1.2.3.4', '1.2.3', 1)
    stage = tmp_path / 'media'
    stage.mkdir()
    assert DicomDirBuilder().build_from_study_folders([str(source)], str(stage))
    original = (stage / 'DICOMDIR').read_bytes()
    exe = tmp_path / 'viewer' / 'viewer.exe'
    exe.parent.mkdir()
    exe.write_bytes(b'MZ synthetic')
    monkeypatch.setattr(manager, 'detect_viewer_launch_mode', lambda path: mode)
    worker = manager.CDBurnWorker(studies=[], light_viewer_path=str(exe), burn_to_disc=False)
    worker._copy_light_viewer(str(stage))
    assert (stage / 'DICOMDIR').read_bytes() == original
    instances = list(FileSet(stage / 'DICOMDIR'))
    assert len(instances) == 1
    assert Path(instances[0].path).is_file()
    assert dcmread(instances[0].path).pixel_array.size > 0
    assert scan_media(str(stage)).series
