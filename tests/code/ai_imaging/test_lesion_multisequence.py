"""Synthetic multi-sequence MS safety and transport guards."""
import numpy as np
import pytest
import SimpleITK as sitk


def image(a):
    return sitk.GetImageFromArray(np.asarray(a, dtype=np.uint8))


def test_different_reference_frame_requires_explicit_registration_path():
    from modules.ai_imaging.eagle_eye_brain.patient_context import require_same_examination
    from modules.ai_imaging.eagle_eye_brain.contracts import BrainError
    a = dict(patient_id='synthetic',study_uid='1.2.3',frame_uid='1.2.4')
    b = dict(a,frame_uid='1.2.5')
    with pytest.raises(BrainError): require_same_examination(a,b)
    require_same_examination(a,b,allow_frame_registration=True)
    with pytest.raises(BrainError): require_same_examination(a,dict(b,patient_id='another'),allow_frame_registration=True)


def test_matching_keeps_whole_supported_component_and_preserves_disagreement():
    from modules.ai_imaging.eagle_eye_brain.lesion_multisequence import match_components
    a = np.zeros((12, 12, 12), np.uint8); b = a.copy()
    a[2:5, 2:5, 2:5] = 1; a[8:10, 8:10, 8:10] = 1
    b[3:6, 2:5, 2:5] = 1; b[8:10, 2:4, 8:10] = 1
    keep, other, report = match_components(image(a), image(b))
    assert sitk.GetArrayFromImage(keep).sum() == 27
    assert sitk.GetArrayFromImage(other).sum() == 8
    assert report['primary_only_count'] == report['secondary_only_count'] == 1
    assert report['supported_primary_count'] == 1
    assert np.array_equal(sitk.GetArrayFromImage(keep | other), a)


def test_single_voxel_touch_is_not_support():
    from modules.ai_imaging.eagle_eye_brain.lesion_multisequence import match_components
    a = np.zeros((8, 8, 8), np.uint8); b = a.copy()
    a[1:3, 1:3, 1:3] = 1; b[2:4, 2:4, 2:4] = 1
    keep, _, report = match_components(image(a), image(b))
    assert not sitk.GetArrayFromImage(keep).any()
    assert report['supported_primary_count'] == 0


def test_subtraction_is_not_raw_scanner_intensity_difference():
    from modules.ai_imaging.eagle_eye_brain.lesion_multisequence import subtraction
    rng = np.random.default_rng(22)
    pre = sitk.GetImageFromArray(rng.uniform(10, 100, (12, 12, 12)).astype('float32'))
    post = pre * 3 + 50
    delta = subtraction(pre, post, image(np.ones((12, 12, 12))))
    assert np.max(np.abs(sitk.GetArrayFromImage(delta))) < 1e-5


def test_subtraction_rejects_wrong_grid():
    from modules.ai_imaging.eagle_eye_brain.lesion_multisequence import subtraction
    pre = sitk.GetImageFromArray(np.arange(1000).reshape(10, 10, 10).astype('float32'))
    post = sitk.Image(pre); post.SetOrigin((2, 0, 0))
    with pytest.raises(ValueError, match='grid'):
        subtraction(pre, post, image(np.ones((10, 10, 10))))


def test_optional_roles_are_explicit_and_ms_only():
    from modules.ai_imaging.eagle_eye_remote.contracts import validate
    request = dict(protocol=1, request_id='0'*32, module='brain-lesions', study_uid='1.2.3',
                   series={k:dict(series_uid=f'1.2.{i}', expected_count=20)
                           for i,k in enumerate(('t1','flair','flair_secondary','t1_post'),10)},
                   parameters=dict(acquisition_mode='2d', primary_disease='ms', contrast_roles_confirmed=True))
    assert validate(request) == request
    request['parameters']['primary_disease'] = 'svd'
    with pytest.raises(ValueError): validate(request)


def test_gap_support_does_not_invent_acquired_tissue():
    import threading
    from modules.ai_imaging.eagle_eye_brain.lesion_multisequence import acquired_support
    moving = image(np.ones((4,4,4))); moving.SetSpacing((1,1,6))
    fixed = image(np.ones((19,4,4)))
    support=acquired_support(moving,fixed,sitk.Transform(3,sitk.sitkIdentity),2,threading.Event())
    a=sitk.GetArrayFromImage(support)
    assert a[0].all() and a[1].all() and not a[2].any() and not a[3].any() and a[6].all()


def test_opposite_direction_geometry_is_respected():
    import threading
    from modules.ai_imaging.eagle_eye_brain.lesion_multisequence import acquired_support
    moving=image(np.ones((4,4,4))); moving.SetSpacing((1,1,6))
    moving.SetDirection((-1,0,0,0,1,0,0,0,-1)); moving.SetOrigin((3,0,18))
    fixed=image(np.ones((19,4,4)))
    support=acquired_support(moving,fixed,sitk.Transform(3,sitk.sitkIdentity),2,threading.Event())
    a=sitk.GetArrayFromImage(support)
    assert a[0].all() and not a[3].any() and a[18].all()


def test_remote_route_never_sends_optional_paths(tmp_path,monkeypatch):
    from modules.ai_imaging.eagle_eye_remote import routing
    refs={'pre':('1.2.3',dict(series_uid='1.2.4',expected_count=5)),
          'flair':('1.2.3',dict(series_uid='1.2.5',expected_count=5)),
          'second':('1.2.3',dict(series_uid='1.2.6',expected_count=5))}
    monkeypatch.setattr(routing,'reference',lambda p:refs[p])
    class FakeClient:
        def json(self,*a):return dict(lesion_multisequence_review=True,lesion_acquisition_modes=['2d','3d'])
        def analyze(self,module,study,series,params,*a,**kw):
            assert series['flair_secondary']==refs['second'][1]
            assert not any(k.endswith(('_source','_uid')) for k in params)
            return 'sent'
    monkeypatch.setattr(routing,'Client',FakeClient)
    assert routing.lesions('pre','flair','1.2.3','1.2.4','1.2.5',tmp_path,
        flair_secondary_source='second',flair_secondary_uid='1.2.6',acquisition_mode='2d')=='sent'


def test_no_optional_request_to_old_server(tmp_path,monkeypatch):
    from modules.ai_imaging.eagle_eye_remote import routing
    monkeypatch.setattr(routing,'reference',lambda p:('1.2.3',dict(series_uid={'a':'1.2.4','b':'1.2.5','c':'1.2.6'}[p],expected_count=5)))
    class OldClient:
        def json(self,*a):return {}
        def analyze(self,*a,**k):pytest.fail('unsupported request submitted')
    monkeypatch.setattr(routing,'Client',OldClient)
    with pytest.raises(ValueError,match='multi-sequence'):
        routing.lesions('a','b','1.2.3','1.2.4','1.2.5',tmp_path,flair_secondary_source='c',flair_secondary_uid='1.2.6')


def test_picker_saves_four_roles_and_invalidates_on_mode_change(monkeypatch):
    from PySide6.QtWidgets import QApplication,QDialog,QComboBox,QCheckBox,QDialogButtonBox
    from modules.ai_imaging.eagle_eye_brain.lesion_widget import BrainLesionWidget
    app=QApplication.instance() or QApplication([])
    widget=BrainLesionWidget(study_uid='1.2.3')
    widget.acquisition_mode.setCurrentIndex(1)
    monkeypatch.setattr(widget,'_load_demographics',lambda:None)
    rows=[dict(series_uid=f'1.2.{i}',number=i,description=d,available=True,image_count=24,path=f'synthetic-{i}')
          for i,d in [(1,'t1 vibe'),(2,'FLAIR axial'),(3,'FLAIR sagittal'),(4,'t1 vibe')]]
    def choose(dialog):
        names=['lesionT1Series','lesionFlairSeries','lesionSecondaryFlairSeries','lesionPostT1Series']
        controls=[dialog.findChild(QComboBox,n) for n in names]
        for i,c in enumerate(controls): c.setCurrentIndex(i+1)
        verified=dialog.findChild(QCheckBox);verified.setChecked(True)
        buttons=dialog.findChild(QDialogButtonBox)
        assert buttons.button(QDialogButtonBox.Ok).isEnabled()
        controls[3].setCurrentIndex(1)
        assert not buttons.button(QDialogButtonBox.Ok).isEnabled()
        controls[3].setCurrentIndex(4)
        return QDialog.Accepted
    monkeypatch.setattr(QDialog,'exec',choose)
    widget._choose_t1_series(rows)
    assert widget._selected_flair_secondary['series_uid']=='1.2.3'
    assert widget._selected_t1_post['series_uid']=='1.2.4'
    assert widget._contrast_roles_confirmed
    widget.acquisition_mode.setCurrentIndex(0)
    assert widget._selected_flair_secondary is None and widget._selected_t1_post is None
    widget.deleteLater();app.processEvents()

def test_single_flair_request_remains_compatible_with_old_server(tmp_path, monkeypatch):
    from modules.ai_imaging.eagle_eye_remote import routing
    monkeypatch.setattr(routing,'reference',lambda p:('1.2.3',dict(series_uid={'a':'1.2.4','b':'1.2.5'}[p],expected_count=5)))
    class OldClient:
        def analyze(self,module,study,series,params,*a,**k):
            assert 'contrast_roles_confirmed' not in params
            return 'sent'
    monkeypatch.setattr(routing,'Client',OldClient)
    assert routing.lesions('a','b','1.2.3','1.2.4','1.2.5',tmp_path,contrast_roles_confirmed=False)=='sent'


def test_contrast_pair_requires_original_matching_acquisition(tmp_path):
    from pydicom.dataset import FileDataset,FileMetaDataset
    from pydicom.uid import ExplicitVRLittleEndian
    from modules.ai_imaging.eagle_eye_brain.lesion_multisequence import verify_contrast_pair
    from modules.ai_imaging.eagle_eye_brain.contracts import BrainError
    dirs=[tmp_path/'pre',tmp_path/'post']
    datasets=[]
    for directory in dirs:
        directory.mkdir()
        ds=FileDataset(str(directory/'test.dcm'),{},file_meta=FileMetaDataset(),preamble=b'\0'*128)
        ds.file_meta.TransferSyntaxUID=ExplicitVRLittleEndian
        ds.Modality='MR';ds.MRAcquisitionType='3D';ds.ImageType=['ORIGINAL','PRIMARY']
        ds.RepetitionTime=6;ds.EchoTime=2;ds.FlipAngle=8;ds.ScanningSequence='GR'
        ds.save_as(directory/'test.dcm');datasets.append(ds)
    verify_contrast_pair(*dirs)
    datasets[1].EchoTime=10;datasets[1].save_as(dirs[1]/'test.dcm')
    with pytest.raises(BrainError,match='settings'):verify_contrast_pair(*dirs)
    datasets[1].EchoTime=2;datasets[1].ImageType=['DERIVED','SUB'];datasets[1].save_as(dirs[1]/'test.dcm')
    with pytest.raises(BrainError,match='original'):verify_contrast_pair(*dirs)

def test_resampled_native_components_are_not_recounted_as_fragments():
    from modules.ai_imaging.eagle_eye_brain.lesion_multisequence import match_components
    a=np.zeros((10,10,10),np.uint8);b=a.copy()
    a[1:3,1:3,1:3]=1;b[1:3,1:3,1:3]=1;b[7:9,7:9,7:9]=1
    # Two disconnected resampling fragments belong to the same native component.
    native=image(b*7)
    _,_,report=match_components(image(a),image(b),native)
    assert report['secondary_count_on_primary_grid']==1
    assert report['secondary_only_count']==0
    assert report['pairs'][0]['secondary_id']==7

def test_manual_revision_invalidates_crossplane_and_contrast_claims(tmp_path, monkeypatch):
    import json
    from modules.ai_imaging.eagle_eye_brain import manual_review,lesion_report
    from modules.ai_imaging.eagle_eye_brain.runtime import sha256
    original=image(np.ones((3,3,3)));edited=image(np.zeros((3,3,3)))
    for name,im in [('original',original),('image',original),('corrected',edited)]:
        sitk.WriteImage(im,str(tmp_path/(name+'.nii.gz')))
    manifest=dict(lesion=True,source_mask=str(tmp_path/'original.nii.gz'),
                  source_sha256=sha256(tmp_path/'original.nii.gz'),source_result=dict(
                  acquisition_mode='2d',metrics={'slice_thickness_mm':1},
                  multisequence={'supported_primary_count':1},enhancement_review={'lesions':[1]},sampled_topography={'rows':[1]}))
    (tmp_path/'session.json').write_text(json.dumps(manifest))
    monkeypatch.setattr(lesion_report,'write_lesion_report',lambda *a:None)
    result=manual_review.recalculate_review(tmp_path)
    assert result['metrics']['candidate_count']==0
    assert 'multisequence' not in result and 'enhancement_review' not in result
    assert result['source_multisequence']['supported_primary_count']==1
    assert result['source_enhancement_review']['lesions']==[1]
    assert 'sampled_topography' not in result and result['source_sampled_topography']['rows']==[1]


def test_remote_exports_review_images_without_unrelated_inputs(tmp_path):
    import zipfile,json
    from modules.ai_imaging.eagle_eye_remote.artifacts import publish
    job=tmp_path/('a'*32);root=job/'work';root.mkdir(parents=True)
    for name in ('flair.nii.gz','labels.nii.gz','secondary-flair.nii.gz','t1-subtraction.nii.gz','pre-flair.nii.gz','post-flair.nii.gz','unrelated.nii.gz','source.dcm'):
        (root/name).write_bytes(b'synthetic')
    result=dict(artifact_directory=str(root),analysis_type='brain_lesions',mask_path=str(root/'labels.nii.gz'),
                multisequence={'supported_primary_count':1},enhancement_review={'classifier':None})
    request=dict(module='brain-lesions',protocol=1,request_id='b'*32,study_uid='1.2.3',series={})
    publish(job,request,[],result)
    with zipfile.ZipFile(job/'artifacts.zip') as archive:
        names=archive.namelist()
        assert all(n in names for n in ('secondary-flair.nii.gz','t1-subtraction.nii.gz','pre-flair.nii.gz','post-flair.nii.gz'))
        assert 'source.dcm' not in names and 'unrelated.nii.gz' not in names
        assert json.loads(archive.read('envelope.json'))['result']['enhancement_review']['classifier'] is None

@pytest.mark.parametrize('accept',[True,False])
def test_picker_can_switch_to_2d_without_leaving_dialog(monkeypatch,accept):
    from PySide6.QtWidgets import QApplication,QDialog,QComboBox,QCheckBox,QDialogButtonBox
    from modules.ai_imaging.eagle_eye_brain.lesion_widget import BrainLesionWidget
    app=QApplication.instance() or QApplication([])
    widget=BrainLesionWidget(study_uid='1.2.3')
    monkeypatch.setattr(widget,'_load_demographics',lambda:None)
    rows=[dict(series_uid=f'1.2.{i}',number=i,description=d,available=True,image_count=24,path=f'synthetic-{i}')
          for i,d in [(1,'T1'),(2,'FLAIR axial'),(3,'FLAIR sagittal')]]
    def choose(dialog):
        mode=dialog.findChild(QComboBox,'lesionPickerAcquisitionMode')
        assert mode is not None, '2D selection must be available inside the series picker'
        extra=dialog.findChild(QComboBox,'lesionSecondaryFlairSeries')
        assert not extra.isEnabled()
        mode.setCurrentIndex(mode.findData('2d'))
        assert extra.isEnabled() and '2D' in dialog.windowTitle()
        dialog.findChild(QComboBox,'lesionT1Series').setCurrentIndex(1)
        dialog.findChild(QComboBox,'lesionFlairSeries').setCurrentIndex(2)
        extra.setCurrentIndex(3)
        verified=dialog.findChild(QCheckBox);verified.setChecked(True)
        assert dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.Ok).isEnabled()
        mode.setCurrentIndex(mode.findData('3d'))
        assert extra.currentData() is None and not extra.isEnabled() and not verified.isChecked()
        mode.setCurrentIndex(mode.findData('2d'));extra.setCurrentIndex(3);verified.setChecked(True)
        return QDialog.Accepted if accept else QDialog.Rejected
    monkeypatch.setattr(QDialog,'exec',choose)
    widget._choose_t1_series(rows)
    assert widget.acquisition_mode.currentData()==('2d' if accept else '3d')
    assert bool(widget._selected_flair_secondary)==accept
    widget.deleteLater();app.processEvents()

def test_picker_hides_2d_controls_in_3d_mode(monkeypatch):
    from PySide6.QtWidgets import QApplication,QDialog,QComboBox,QLabel
    from modules.ai_imaging.eagle_eye_brain.lesion_widget import BrainLesionWidget
    app=QApplication.instance() or QApplication([])
    widget=BrainLesionWidget(study_uid='1.2.3')
    def choose(dialog):
        mode=dialog.findChild(QComboBox,'lesionPickerAcquisitionMode')
        extra=dialog.findChild(QComboBox,'lesionSecondaryFlairSeries')
        assert extra.isHidden(), '3D must not display an unusable 2D selector'
        heading=dialog.findChild(QLabel,'lesionFlairHeading')
        assert heading is not None and heading.text().startswith('3D')
        mode.setCurrentIndex(mode.findData('2d'))
        assert not extra.isHidden() and heading.text().startswith('2D')
        mode.setCurrentIndex(mode.findData('3d'))
        assert extra.isHidden()
        return QDialog.Rejected
    monkeypatch.setattr(QDialog,'exec',choose)
    widget._choose_t1_series([])
    widget.deleteLater();app.processEvents()

def test_study_series_sort_is_numeric_not_protocol_priority(monkeypatch):
    import sys
    from types import SimpleNamespace
    from modules.ai_imaging.eagle_eye_brain.study_workflow import load_study_series
    numbers=['11','5','100','2','10','7','',None,'unknown','0']
    rows=[dict(modality='MR',series_uid=f'1.2.{i}',series_number=n,
               series_description='T1' if n=='11' else 'FLAIR',series_path='') for i,n in enumerate(numbers)]
    monkeypatch.setitem(sys.modules,'PacsClient.utils.db_manager',SimpleNamespace(get_series_by_study_uid=lambda _:rows))
    result=load_study_series('1.2.3')
    assert [r['number'] for r in result[:7]]==['0','2','5','7','10','11','100']
    assert next(r for r in result if r['number']=='11')['preferred']
