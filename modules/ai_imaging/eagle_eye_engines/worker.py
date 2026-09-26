"""CPU engine adapter, executed only inside its versioned isolated environment."""
import hashlib
import json
import os
from pathlib import Path
import sys


def normalize_estimators(value):
    """Unwrap serialized (name, estimator) members; preserve ensemble grouping."""
    if isinstance(value, tuple) and len(value) == 2 and isinstance(value[0], str):
        return value[1]
    if isinstance(value, (list, tuple)):
        return [normalize_estimators(item) for item in value]
    return value


def validate_stacker_schema(cache):
    """Do not invent the missing training-time feature construction contract."""
    expected = len(cache['used_kinds'])
    for estimator in cache['stackers'].values():
        if getattr(estimator, 'n_features_in_', None) != expected:
            raise ValueError('Breast classifier weights and inference feature schema do not match.')


def breast_model(root):
    import torch
    import FCOS_INFERENCE as fcos
    # Never download backbone weights or accept a randomly initialized detector.
    from types import SimpleNamespace
    fcos.ResNet50_Weights = SimpleNamespace(DEFAULT=None)
    model = fcos.make_detector(1)
    model.transform.min_size = [fcos.IMG_SIZE[0]]
    model.transform.max_size = fcos.IMG_SIZE[0]
    state = torch.load(root / 'weights/best_fcos_csv_delivery.pth', map_location='cpu', weights_only=True)
    model.load_state_dict(state, strict=True)
    model.eval()
    fcos.load_model = lambda: (model, torch.device('cpu'), {'mode': 'verified_state_dict'})
    return fcos, model


def classify(root, job, rows):
    import pandas as pd
    import CREATE_LESION as lesion
    import SINGLEVIEW_FEATURES as single
    import TWO_VIEW_FEATURES as paired
    import XGBOOST_INFERENCE as xgb
    original_log = xgb._log
    def strict_log(message):
        if str(message).startswith('[warn]'):
            raise RuntimeError('Incomplete classification is not accepted.')
        original_log(message)
    xgb._log = strict_log
    stages = [job / n for n in ('normalized.csv', 'lesion.csv', 'singleview.csv', 'twoview.csv', 'classification.csv')]
    pd.DataFrame(rows).to_csv(stages[0], index=False)
    calls = [
        lambda: lesion.run_lesion_stage1_safe(str(stages[0]), str(stages[1]), str(job / 'roi'), log_file=str(job / 'stage1.log')),
        lambda: single.run_single_features_safe(str(stages[1]), str(stages[2]), log_file=str(job / 'stage2.log')),
        lambda: paired.run_multiview_bilateral_safe(str(stages[2]), str(stages[3]), log_file=str(job / 'stage3.log')),
        lambda: xgb.run_stacked_infer_safe(str(stages[3]), str(root / 'weights/models_stacked'), str(stages[4]), log_file=str(job / 'stage4.log')),
    ]
    for index, call in enumerate(calls):
        message = call()
        if not stages[index + 1].is_file() or str(message).lower().startswith('[error]'):
            raise RuntimeError('Classification stage failed.')
        frame = pd.read_csv(stages[index + 1])
        if len(frame) != len(rows):
            raise RuntimeError('Classification lost an input lesion.')
        for col in frame.columns:
            if 'error' in col.lower() and frame[col].fillna('').astype(str).str.strip().ne('').any():
                raise RuntimeError('Classification contains an invalid lesion.')
    return str(stages[-1])


def breast(root, job, request):
    import numpy as np
    import pandas as pd
    import imageio.v3 as iio
    import CASE_DICOM_TO_PNG as d2p
    import XGBOOST_INFERENCE as xgb
    fcos, model = breast_model(root)
    png_dir = job / 'png'
    png_dir.mkdir()
    sources = request['files']
    rows = []
    if request['smoke']:
        # Actual FCOS forward and all four classification stages on synthetic DICOM.
        sources = synthetic_sources(job, 'MG', request['study_uid'])
    for index, record in enumerate(sources):
        png = png_dir / f'image-{index:03d}.png'
        pixels = d2p._read_dicom_u8_with_pydicom(record['path'], 0)
        if pixels.ndim != 2 or np.ptp(pixels) == 0:
            raise ValueError('Invalid source pixels.')
        iio.imwrite(png, pixels)
        rows.append(dict(dicom_full_path=record['path'], full_image_path=record['path'],
                         png_full_path=str(png), study_id=request['study_uid'],
                         study_instance_uid=request['study_uid'], series_instance_uid=record['series_uid'],
                         image_id=record['sop_uid'], laterality=record['laterality'],
                         view_position=record['view_position'], patient_id='', patient_name='',
                         width=pixels.shape[1], height=pixels.shape[0]))
    input_csv = job / 'input.csv'
    pd.DataFrame(rows).to_csv(input_csv, index=False)
    message = fcos.run_inference_safe(str(png_dir), str(job), request['threshold'], 0.75,
                                      str(job / 'detector.log'), str(input_csv))
    detection = job / 'updated_csv_with_boxes.csv'
    if not detection.is_file() or str(message).lower().startswith('[error]'):
        raise RuntimeError('Detection failed.')
    frame = pd.read_csv(detection, keep_default_na=False)
    if len(frame) != len(rows):
        raise RuntimeError('Detector did not process every input.')
    lesions = []
    for row in frame.to_dict('records'):
        for box in json.loads(row['box'] or '[]'):
            lesions.append({**row, **dict(zip(('xmin', 'ymin', 'xmax', 'ymax'), box))})
    if request['smoke'] and not lesions:
        lesions = [{**rows[0], 'xmin': 100, 'ymin': 100, 'xmax': 300, 'ymax': 350}]
    classified = None
    classification_status = 'no_detections'
    if lesions:
        try:
            xgb.preload_models(str(root / 'weights/models_stacked'))
            validate_stacker_schema(xgb._GLOBAL_CACHE)
            xgb._GLOBAL_CACHE['base_models'] = {
                kind: normalize_estimators(members)
                for kind, members in xgb._GLOBAL_CACHE['base_models'].items()}
            classified = classify(root, job, lesions)
            classification_status = 'completed'
        except Exception:
            if request['smoke']:
                raise
            classification_status = 'unavailable'
            (job / 'classification.csv').unlink(missing_ok=True)
    if classified:
        fcos.regenerate_overlays_with_classification(str(job), classified, verbose=False)
    return dict(csv=str(detection), csv_classification=classified, auxiliary_head_available=False,
                images=[str(p) for p in sorted((job / 'ALL_VIZ').glob('*.png'))],
                image_count=len(rows), classification_status=classification_status)


def bone(root, job, request):
    import numpy as np
    import torch
    from PIL import Image
    import pydicom
    import bone_age_inference as infer
    import dicom_utils
    model = infer.load_model(str(root / 'weights/final_model.pth'), torch.device('cpu'))
    sources = request['files']
    if request['smoke']:
        sources = synthetic_sources(job, 'DX', request['study_uid'])
    predictions = []
    for index, record in enumerate(sources):
        ds = pydicom.dcmread(record['path'])
        pixels = dicom_utils.dicom_to_uint8(ds)
        if pixels.ndim != 2 or np.ptp(pixels) == 0:
            raise ValueError('Invalid source pixels.')
        with torch.inference_mode():
            months = infer.predict_one(model, Image.fromarray(pixels),
                                       infer.sex_to_id(request['sex'] or 'M'), torch.device('cpu'))
        if not np.isfinite(months):
            raise RuntimeError('Nonfinite model result.')
        predictions.append(dict(image=f'image-{index:03d}', predicted_bone_age_months=round(months, 2),
                                predicted_bone_age_years=round(months / 12, 2)))
    months = round(float(np.mean([p['predicted_bone_age_months'] for p in predictions])), 2)
    return dict(predicted_bone_age_months=months, predicted_bone_age_years=round(months / 12, 2),
                image_count=len(predictions), per_image_predictions=predictions,
                model_used='Unified BoneAgeViT (single-step)', sex=request['sex'],
                reliability_warnings=['Local engine requires physician review.'], low_confidence=True)


def synthetic_sources(job, modality, study_uid):
    import numpy as np
    from pydicom.dataset import FileDataset, FileMetaDataset
    from pydicom.uid import ExplicitVRLittleEndian, generate_uid, SecondaryCaptureImageStorage
    meta = FileMetaDataset()
    meta.TransferSyntaxUID = ExplicitVRLittleEndian
    meta.MediaStorageSOPClassUID = SecondaryCaptureImageStorage
    meta.MediaStorageSOPInstanceUID = generate_uid()
    path = job / 'synthetic.dcm'
    ds = FileDataset(str(path), {}, file_meta=meta, preamble=b'\0' * 128)
    ds.SOPClassUID, ds.SOPInstanceUID = meta.MediaStorageSOPClassUID, meta.MediaStorageSOPInstanceUID
    ds.StudyInstanceUID, ds.SeriesInstanceUID = study_uid, generate_uid()
    ds.Modality, ds.PatientSex, ds.BodyPartExamined = modality, 'M', 'HAND'
    ds.Rows = ds.Columns = 512
    ds.SamplesPerPixel, ds.PhotometricInterpretation = 1, 'MONOCHROME2'
    ds.BitsAllocated = ds.BitsStored = 16
    ds.HighBit, ds.PixelRepresentation = 15, 0
    ds.PixelSpacing, ds.ImageLaterality, ds.ViewPosition = [0.1, 0.1], 'L', 'CC'
    yy, xx = np.mgrid[:512, :512]
    ds.PixelData = (500 + xx * 3 + yy * 2 + 1000 * np.exp(-((xx-250)**2+(yy-230)**2)/4000)).astype('<u2').tobytes()
    ds.save_as(path, enforce_file_format=True)
    return [dict(path=str(path), sop_uid=str(ds.SOPInstanceUID), series_uid=str(ds.SeriesInstanceUID), laterality='L', view_position='CC')]


def main(root, job):
    import torch
    torch.set_num_threads(4)
    request = json.loads((job / 'request.json').read_text(encoding='utf-8'))
    # Verify immutable source bytes again in the worker, before any decoder runs.
    for record in request['files']:
        with open(record['path'], 'rb') as stream:
            if hashlib.sha256(stream.read()).hexdigest() != record['sha256']:
                raise ValueError('Source changed before inference.')
    result = (breast if request['engine'] == 'breast' else bone)(root, job, request)
    result.update(status='success', study_id=request['study_uid'], synthetic=request['smoke'])
    temporary = job / 'result.partial'
    temporary.write_text(json.dumps(result, allow_nan=False), encoding='utf-8')
    temporary.replace(job / 'result.json')
