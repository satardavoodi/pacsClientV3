"""Synthetic regressions for actual-execution failures; never use the live database."""
from pathlib import Path
import threading

import pytest


@pytest.mark.parametrize('kind', ['ms', 'svd'])
@pytest.mark.parametrize('changed', ['spacing', 'origin', 'direction'])
def test_assessment_rejects_anatomy_with_changed_physical_geometry(tmp_path, monkeypatch, kind, changed):
    import json
    import SimpleITK as sitk
    from modules.ai_imaging.eagle_eye_brain import ms_assessment, svd_assessment, lesion_longitudinal
    from modules.ai_imaging.eagle_eye_brain.contracts import BrainError
    context = {'patient_id': 'synthetic', 'birth_date': '19700101', 'study_uid': '1.2.3'}
    nested = tmp_path / (kind + '-anatomy')
    nested.mkdir()
    (nested / 'result.json').write_text(json.dumps({'pdf_available': True, 'patient_context': context}))
    moving = sitk.Image([4, 5, 6], sitk.sitkUInt16)
    labels = sitk.Image(moving)
    if changed == 'spacing':
        labels.SetSpacing((1, 1, 2))
    elif changed == 'origin':
        labels.SetOrigin((5, 0, 0))
    else:
        labels.SetDirection((-1, 0, 0, 0, -1, 0, 0, 0, 1))
    sitk.WriteImage(moving, str(nested / 'resampled.nii.gz'))
    sitk.WriteImage(labels, str(nested / 'labels.nii.gz'))
    sitk.WriteImage(moving, str(tmp_path / 'flair.nii.gz'))
    monkeypatch.setattr(lesion_longitudinal, 'register_previous',
                        lambda *args: pytest.fail('Mismatched anatomical geometry reached registration'))
    result = {'patient_context': context, 'artifact_directory': str(tmp_path)}
    function = ms_assessment.enrich_ms if kind == 'ms' else svd_assessment.enrich_svd
    with pytest.raises(BrainError, match='geometry'):
        function(result, tmp_path)
    assert not (tmp_path / (kind + '-anatomy-in-flair.nii.gz')).exists()


@pytest.mark.parametrize('outcome', ['completed', 'failed', 'cancelled'])
def test_ms_fallback_anatomy_uses_short_owned_directory(tmp_path, monkeypatch, outcome):
    import json
    import SimpleITK as sitk
    from modules.ai_imaging.eagle_eye_brain import ms_assessment, service, lesion_longitudinal
    from modules.ai_imaging.eagle_eye_brain.contracts import BrainError
    destination = tmp_path / ('patient-' + 'a' * 80) / ('study-' + 'b' * 80) / ('lesions-' + 'c' * 50)
    destination.mkdir(parents=True)
    cancel = threading.Event()
    roots = []

    def compute(t1, flair, output, **kwargs):
        output = Path(output)
        roots.append(output)
        assert len(str(output.resolve())) < 200, 'Nested anatomy must not inherit the patient-store cwd'
        selected = output / 'brain-synthetic'
        selected.mkdir()
        (selected / 'result.json').write_text(json.dumps({'pdf_available': True}))
        (selected / 'labels.nii.gz').write_bytes(b'synthetic-only')
        (selected / 'label_names.json').write_text('{}')
        (selected / 'process.log').write_text('Synthetic engine diagnostic')
        (selected / 'process-diagnostics.jsonl').write_text('{"outcome":"synthetic"}\n')
        if outcome == 'failed':
            raise BrainError('Synthetic engine failure')
        if outcome == 'cancelled':
            cancel.set()
        return {'artifact_directory': str(selected)}

    monkeypatch.setattr(service, '_run_analysis', compute)
    monkeypatch.setattr(sitk, 'ReadImage', lambda *_: sitk.Image([4, 4, 4], sitk.sitkUInt16))
    monkeypatch.setattr(sitk, 'WriteImage', lambda *_: None)
    monkeypatch.setattr(sitk, 'WriteTransform', lambda *_: None)
    monkeypatch.setattr(lesion_longitudinal, 'register_previous', lambda *_: sitk.Transform(3, sitk.sitkIdentity))
    monkeypatch.setattr(ms_assessment, 'assess_topography', lambda *_: {'physician_confirmation_required': True})
    result = {'patient_context': {}, 'mask_path': str(destination / 'mask.nii.gz'),
              'artifact_directory': str(destination)}
    if outcome == 'completed':
        assessment = ms_assessment.enrich_ms(result, destination, t1_source='synthetic-t1', cancel=cancel)
        retained = Path(assessment['anatomical_source'])
        assert retained.is_file() and retained.is_relative_to(destination)
        assert assessment['physician_confirmation_required'] is True
    else:
        with pytest.raises(BrainError, match='failure|cancelled'):
            ms_assessment.enrich_ms(result, destination, t1_source='synthetic-t1', cancel=cancel)
        assert not (destination / 'ms-anatomy').exists()
    assert roots and all(not root.exists() for root in roots)
    assert (destination / 'ms-anatomy-process.log').read_text() == 'Synthetic engine diagnostic'
    assert (destination / 'ms-anatomy-process-diagnostics.jsonl').is_file()


def test_svd_isolated_job_computes_missing_anatomy(tmp_path, monkeypatch):
    import json
    import SimpleITK as sitk
    from modules.ai_imaging.eagle_eye_brain import svd_assessment, service, lesion_longitudinal
    source = tmp_path / 'lesion-job'
    source.mkdir()
    calls = []
    def compute(t1, flair, output, **kwargs):
        assert t1 == 'synthetic-t1'
        selected = Path(output) / 'brain-synthetic'
        selected.mkdir()
        for name, value in [('result.json', {'pdf_available': True}), ('label_names.json', {})]:
            (selected / name).write_text(json.dumps(value))
        calls.append(Path(output))
        return {'artifact_directory': str(selected)}
    monkeypatch.setattr(service, '_run_analysis', compute)
    monkeypatch.setattr(sitk, 'ReadImage', lambda *_: sitk.Image([4, 4, 4], sitk.sitkUInt16))
    monkeypatch.setattr(sitk, 'WriteImage', lambda *_: None)
    monkeypatch.setattr(sitk, 'WriteTransform', lambda *_: None)
    monkeypatch.setattr(lesion_longitudinal, 'register_previous', lambda *_: sitk.Transform(3, sitk.sitkIdentity))
    monkeypatch.setattr(svd_assessment, 'spatial_burden', lambda *_: {'compartments': ['synthetic']})
    result = {'patient_context': {}, 'mask_path': str(source / 'mask.nii.gz'),
              'artifact_directory': str(source), 'metrics': {'total_volume_cm3': 0}}
    assessment = svd_assessment.enrich_svd(result, source, t1_source='synthetic-t1')
    assert assessment['compartments'] == ['synthetic']
    assert Path(assessment['anatomical_source']).is_file()
    assert calls and all(not path.exists() for path in calls)


@pytest.mark.parametrize('kind', ['ms', 'svd'])
@pytest.mark.parametrize('state', ['complete', 'failed', 'other-study'])
def test_nested_anatomy_remains_available_for_same_study_review(tmp_path, monkeypatch, kind, state):
    import json
    import SimpleITK as sitk
    from modules.ai_imaging.eagle_eye_brain import ms_assessment, svd_assessment, lesion_longitudinal
    context = {'patient_id': 'synthetic', 'birth_date': '19700101', 'study_uid': '1.2.3'}
    nested = tmp_path / (kind + '-anatomy')
    nested.mkdir()
    stored_context = dict(context, study_uid='1.2.4') if state == 'other-study' else context
    (nested / 'result.json').write_text(json.dumps({'pdf_available': True, 'patient_context': stored_context}))
    (nested / 'label_names.json').write_text('{}')
    (nested / 'labels.nii.gz').write_bytes(b'synthetic')
    if state == 'failed':
        (nested / 'FAILED').write_text('Synthetic incomplete computation')
    monkeypatch.setattr(sitk, 'ReadImage', lambda *_: sitk.Image([4, 4, 4], sitk.sitkUInt16))
    monkeypatch.setattr(sitk, 'WriteImage', lambda *_: None)
    monkeypatch.setattr(sitk, 'WriteTransform', lambda *_: None)
    monkeypatch.setattr(lesion_longitudinal, 'register_previous', lambda *_: sitk.Transform(3, sitk.sitkIdentity))
    monkeypatch.setattr(ms_assessment, 'assess_topography', lambda *_: {'physician_confirmation_required': True})
    monkeypatch.setattr(svd_assessment, 'spatial_burden', lambda *_: {'compartments': ['synthetic']})
    result = {'patient_context': context, 'mask_path': str(tmp_path/'mask.nii.gz'),
              'artifact_directory': str(tmp_path), 'metrics': {'total_volume_cm3': 0}}
    assessment = (ms_assessment.enrich_ms if kind == 'ms' else svd_assessment.enrich_svd)(result, tmp_path)
    if state == 'complete':
        assert Path(assessment['anatomical_source']) == nested/'result.json'
    else:
        assert 'anatomical_source' not in assessment


@pytest.mark.parametrize('module', ['alignment', 'total-spine'])
def test_explicit_stitched_radiograph_can_be_staged(tmp_path, monkeypatch, module):
    import pydicom
    from pydicom.dataset import FileDataset, FileMetaDataset
    from pydicom.uid import ExplicitVRLittleEndian, DigitalXRayImageStorageForPresentation
    from modules.ai_imaging.eagle_eye_remote.source import PacsSource
    path = tmp_path / 'source.dcm'
    meta = FileMetaDataset()
    meta.TransferSyntaxUID = ExplicitVRLittleEndian
    meta.MediaStorageSOPClassUID = DigitalXRayImageStorageForPresentation
    meta.MediaStorageSOPInstanceUID = '1.2.3.4.5'
    ds = FileDataset(str(path), {}, file_meta=meta, preamble=b'\0' * 128)
    ds.SOPClassUID = meta.MediaStorageSOPClassUID
    ds.SOPInstanceUID = meta.MediaStorageSOPInstanceUID
    ds.StudyInstanceUID, ds.SeriesInstanceUID = '1.2.3', '1.2.3.4'
    ds.Modality, ds.ImageType = 'DX', ['DERIVED', 'SECONDARY']
    ds.save_as(path, write_like_original=False)
    provider = PacsSource({})
    monkeypatch.setattr(provider, 'storage_files', lambda request: [path])
    request = dict(module=module, study_uid='1.2.3', series={'primary': {
        'series_uid': '1.2.3.4', 'sop_uid': '1.2.3.4.5', 'expected_count': 1}})
    records = provider.stage(request, tmp_path / 'staged', threading.Event())
    assert len(records) == 1 and Path(records[0]['path']).read_bytes() == path.read_bytes()
    # The exception must not admit derived MR or automatically selected images.
    request['module'] = 'lumbar'
    ds.Modality = 'MR'; ds.save_as(path, write_like_original=False)
    with pytest.raises(ValueError, match='no matching'):
        provider.stage(request, tmp_path / 'rejected', threading.Event())


def test_oversized_report_section_paginates_without_losing_rows(tmp_path):
    from PySide6.QtWidgets import QApplication
    from PySide6.QtPdf import QPdfDocument
    from modules.ai_imaging.eagle_eye_brain.organized_report import write_paged_pdf, _table
    app = QApplication.instance() or QApplication([])
    rows = [[f'Region-{i:03d}', 'Long anatomical reference name with several wrapped words ' * 3]
            for i in range(45)]
    html = ("<html><head><meta name='brain-patient' content='SYNTHETIC-ONLY'></head><body>"
            '<h1>Published reference intervals</h1>' + _table(['Region', 'Reference'], rows, [25, 75])
            + '<p>END-OF-REFERENCE</p></body></html>')
    path = tmp_path / 'report.pdf'
    write_paged_pdf(html, path)
    document = QPdfDocument()
    assert document.load(str(path)) == QPdfDocument.Error.None_
    assert document.pageCount() > 1
    texts = [document.getAllText(i).text() for i in range(document.pageCount())]
    full = ''.join(texts)
    for label, _ in rows:
        assert full.count(label) == 1
    assert 'END-OF-REFERENCE' in full
    for i, text in enumerate(texts):
        assert 'SYNTHETIC-ONLY' in text
        assert f'Page {i + 1} of {len(texts)}' in text


@pytest.mark.parametrize('outcome', ['completed', 'failed', 'cancelled'])
def test_lesion_engine_uses_short_private_cwd_and_preserves_output(tmp_path, monkeypatch, outcome):
    import SimpleITK as sitk
    from modules.ai_imaging.eagle_eye_brain import lesions, images, patient_context, runtime, lesion_report
    from modules.ai_imaging.eagle_eye_brain.normative import BrainDemographics
    from modules.ai_imaging.eagle_eye_brain.contracts import BrainError
    volume = sitk.Image([5, 5, 5], sitk.sitkUInt8)
    monkeypatch.setattr(images, 'read_volume', lambda *a, **k: volume)
    monkeypatch.setattr(patient_context, 'dicom_context', lambda p: {
        'study_uid': '1.2.3', 'series_uid': p, 'patient_id': 'synthetic'})
    monkeypatch.setattr(patient_context, 'require_same_examination', lambda *a: None)
    monkeypatch.setattr(patient_context, 'demographics_for_report', lambda *a: BrainDemographics(40, 'female'))
    bundle = tmp_path / 'bundle'; bundle.mkdir(); (bundle / 'manifest.json').write_text('{}')
    monkeypatch.setattr(lesions, 'lesion_bundle', lambda: bundle)
    monkeypatch.setattr(lesions, 'validate_lesion_bundle', lambda p: {'version': 'synthetic'})
    monkeypatch.setattr(lesion_report, 'write_lesion_report', lambda *a: None)
    from modules.ai_imaging.eagle_eye_brain import ms_assessment
    monkeypatch.setattr(ms_assessment, 'enrich_ms', lambda *a, **k: {'regions': []})
    observed = []
    def engine(command, directory, cancel, **kwargs):
        observed.append(Path(directory))
        assert len(str(directory)) < 240, 'Windows child cwd exceeds supported length'
        assert Path(command[-1]) == directory
        assert (directory / 't1.nii.gz').is_file()
        (directory / 'process.log').write_text('Synthetic engine diagnostic')
        (directory / 'process-diagnostics.jsonl').write_text('{"outcome":"synthetic"}\n')
        if outcome == 'failed':
            raise BrainError('Synthetic engine failure')
        (directory / 'output').mkdir()
        sitk.WriteImage(volume, str(directory / 'output/space-flair_seg-lst.nii.gz'))
        if outcome == 'cancelled':
            cancel.set()
    monkeypatch.setattr(runtime, 'run_process', engine)
    root = tmp_path / ('long-server-root-' + 'x' * 70)
    def run():
        return lesions._run_lesions('1.2.3.1', '1.2.3.2', study_uid='1.2.3',
            t1_uid='1.2.3.1', flair_uid='1.2.3.2', root=root)
    if outcome == 'completed':
        result = run()
        assert Path(result['mask_path']).is_file()
        assert Path(result['artifact_directory']).is_relative_to(root)
    else:
        with pytest.raises(BrainError):
            run()
        assert list(root.rglob('FAILED'))
        assert not list(root.rglob('result.json'))
        assert not list(root.rglob('space-flair_seg-lst.nii.gz'))
    assert next(root.rglob('process.log')).read_text() == 'Synthetic engine diagnostic'
    assert next(root.rglob('process-diagnostics.jsonl')).is_file()
    assert observed and not observed[0].exists()


@pytest.mark.parametrize('inventory', ['valid', 'missing', 'mixed', 'duplicate'])
def test_lumbar_start_resolves_ctk_identity_in_worker(tmp_path, monkeypatch, inventory):
    import importlib.util
    import queue
    import sqlite3
    import sys
    from types import SimpleNamespace as NS, ModuleType
    import numpy as np
    database = tmp_path / 'ctk.sql'
    with sqlite3.connect(database) as db:
        db.executescript('CREATE TABLE Images(SOPInstanceUID,SeriesInstanceUID); '
                        'CREATE TABLE Series(SeriesInstanceUID,StudyInstanceUID);')
        db.execute('INSERT INTO Series VALUES(?,?)', ('1.2.3.4', '1.2.3'))
        db.executemany('INSERT INTO Images VALUES(?,?)', [(f'1.2.3.4.{i}', '1.2.3.4') for i in range(1, 4)])
        if inventory == 'mixed':
            db.execute('INSERT INTO Series VALUES(?,?)', ('1.2.9.4', '1.2.9'))
            db.execute('UPDATE Images SET SeriesInstanceUID=? WHERE SOPInstanceUID=?', ('1.2.9.4', '1.2.3.4.3'))
    host = ModuleType('slicer')
    host.dicomDatabase = NS(databaseFilename=str(database))
    host.app = NS(slicerHome=str(tmp_path), temporaryPath=str(tmp_path))
    array = np.zeros((3, 4, 5), dtype=np.uint8)
    host.util = NS(arrayFromVolume=lambda v: array, arrayFromVTKMatrix=lambda m: np.eye(4))
    bases = ModuleType('slicer.ScriptedLoadableModule')
    bases.ScriptedLoadableModule = bases.ScriptedLoadableModuleWidget = object
    monkeypatch.setitem(sys.modules, 'slicer', host)
    monkeypatch.setitem(sys.modules, 'slicer.ScriptedLoadableModule', bases)
    monkeypatch.setitem(sys.modules, 'qt', ModuleType('qt'))
    vtk = ModuleType('vtk'); vtk.vtkMatrix4x4 = object
    monkeypatch.setitem(sys.modules, 'vtk', vtk)
    path = Path(__file__).resolve().parents[3] / 'modules/mpr/advanced_3d_slicer/slicer_modules/AIPacsOfflineLumbar.py'
    spec = importlib.util.spec_from_file_location('lumbar_test_host', path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    from modules.ai_imaging.eagle_eye_remote import settings, client
    monkeypatch.setenv('AIPACS_EAGLE_EYE_PACKAGE_ROOT', str(tmp_path))
    monkeypatch.setattr(settings, 'remote_required', lambda: True)
    monkeypatch.setattr(module, '_segmentation_data', lambda *a: object())
    in_worker = [False]; calls = []
    connect = sqlite3.connect
    def guarded_connect(*a, **k):
        assert in_worker[0], 'DICOM index I/O reached the GUI thread'
        assert 'mode=ro' in a[0]
        return connect(*a, **k)
    monkeypatch.setattr(sqlite3, 'connect', guarded_connect)
    def analyze(self, module, study, series, params, work, **kwargs):
        calls.append((study, series))
        np.save(tmp_path / 'labels.npy', array)
        return {'labels_file': str(tmp_path / 'labels.npy'), 'affine_ras': np.eye(4), 'segments': []}
    monkeypatch.setattr(client.Client, 'analyze', analyze)
    monkeypatch.setattr(client.Client, '__init__', lambda self: None)
    class Worker:
        def __init__(self, target, **kwargs): self.target = target
        def start(self):
            in_worker[0] = True
            try: self.target()
            finally: in_worker[0] = False
    monkeypatch.setattr(module.threading, 'Thread', Worker)
    instances = {'valid': '1.2.3.4.1 1.2.3.4.2 1.2.3.4.3',
                 'mixed': '1.2.3.4.1 1.2.3.4.2 1.2.3.4.3',
                 'missing': '1.2.3.4.1 1.2.3.4.2 1.2.3.4.9',
                 'duplicate': '1.2.3.4.1 1.2.3.4.1 1.2.3.4.3'}[inventory]
    volume = NS(IsA=lambda name: True, GetImageData=lambda: NS(GetMTime=lambda: 1),
                GetParentTransformNode=lambda: None, GetIJKToRASMatrix=lambda m: None,
                GetAttribute=lambda key: 'MR' if key == 'DICOM.Modality' else instances)
    logic = module.AIPacsOfflineLumbarLogic.__new__(module.AIPacsOfflineLumbarLogic)
    logic._thread = None; logic._cancel = threading.Event(); logic._results = queue.Queue()
    logic._timer = NS(start=lambda: None)
    logic.start(volume)
    if inventory == 'valid':
        assert calls == [('1.2.3', {'primary': {'series_uid': '1.2.3.4', 'expected_count': 3}})]
        assert logic._results.get_nowait()[2] is None
    else:
        assert not calls
        assert logic._results.get_nowait()[2] == 'ValueError'
