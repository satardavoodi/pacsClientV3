"""Worker-side preparation of nonspatial MR/SC, DOC/SC and DX presentations.

Frames retain their native dimensions and components. They are NOT a 3D volume.
Only the Advanced renderer consumes these independently prepared VTK images.
"""
from pathlib import Path
import os

import numpy as np
import pydicom
import SimpleITK as sitk

SC = '1.2.840.10008.5.1.4.1.1.7'
MR = '1.2.840.10008.5.1.4.1.1.4'
DX_PRESENTATION = '1.2.840.10008.5.1.4.1.1.1.1'
FRAME_KEY = '_advanced_presentation_frames'
MAX_BYTES = 512 * 1024 * 1024
OVERLAY_KEY = '_advanced_presentation_overlays'


def overlay_image(ds, image, convert):
    """Prepare standard one-bit graphics separately from the source pixels."""
    if os.getenv('AIPACS_DICOM_OVERLAY', '1').lower() in ('0', 'false', 'no', 'off'):
        return None
    rows, cols = int(ds.Rows), int(ds.Columns)
    mask = None
    for group in range(0x6000, 0x6020, 2):
        if (group, 0x3000) not in ds:
            continue
        bits = ds.overlay_array(group)
        if bits.ndim == 3 and bits.shape[0] == 1:
            bits = bits[0]
        if bits.ndim != 2:
            raise ValueError('Unsupported presentation overlay frame layout')
        origin = ds.get((group, 0x0050))
        r, c = (int(v) - 1 for v in origin.value) if origin is not None else (0, 0)
        y0, x0 = max(0, r), max(0, c)
        y1, x1 = min(rows, r + bits.shape[0]), min(cols, c + bits.shape[1])
        if y1 <= y0 or x1 <= x0:
            continue
        if mask is None:
            mask = np.zeros((rows, cols), dtype=bool)
        mask[y0:y1, x0:x1] |= bits[y0-r:y1-r, x0-c:x1-c] != 0
    if mask is None or not mask.any():
        return None
    try:
        color = tuple(int(v) for v in os.getenv('AIPACS_DICOM_OVERLAY_COLOR', '0,255,0').split(','))
        if len(color) != 3 or any(v < 0 or v > 255 for v in color):
            raise ValueError
    except ValueError:
        color = (0, 255, 0)
    rgba = np.zeros((1, rows, cols, 4), dtype=np.uint8)
    rgba[0, mask, :3] = color
    rgba[0, mask, 3] = 255
    overlay = sitk.GetImageFromArray(rgba, isVector=True)
    overlay.CopyInformation(image)
    return convert(overlay)


class PresentationFrames(tuple):
    """Read-only frame references shared by metadata snapshots in this domain."""

    def __deepcopy__(self, memo):
        memo[id(self)] = self
        return self


def contains_presentation_frames(files):
    """Header-only routing probe; ordinary series retain their existing loader."""
    for path in files:
        try:
            ds = pydicom.dcmread(str(path), stop_before_pixels=True, force=True,
                                 specific_tags=['SOPClassUID', 'Modality'])
        except (OSError, ValueError):
            continue
        if (str(ds.get('SOPClassUID', '')), str(ds.get('Modality', '')).upper()) in (
                (SC, 'MR'), (SC, 'DOC'), (DX_PRESENTATION, 'DX')):
            return True
    return False


def load_presentation_sequence(files, *, series_number, max_itk_threads=None):
    """Return None for ordinary series; fail atomically for invalid presentations.

    Called only on the existing load worker. No decoder, file read or VTK image
    construction is deferred to scrolling. Never truncate to a dominant size.
    """
    files = tuple(files)
    if not contains_presentation_frames(files):
        return None
    headers = [(str(path), pydicom.dcmread(str(path), stop_before_pixels=True, force=True))
               for path in files]
    is_dx = any(str(ds.get('SOPClassUID', '')) == DX_PRESENTATION for _, ds in headers)
    is_document = any(str(ds.get('Modality', '')).upper() == 'DOC' for _, ds in headers)
    modality = 'DX' if is_dx else ('DOC' if is_document else 'MR')
    allowed_sops = (DX_PRESENTATION,) if is_dx else ((SC,) if is_document else (SC, MR))
    # A proven presentation candidate must not silently fall back to size grouping.
    if any(str(ds.get('Modality', '')).upper() != modality for _, ds in headers):
        raise ValueError('Mixed modalities in presentation sequence')
    identities = {(str(ds.get('StudyInstanceUID', '')), str(ds.get('SeriesInstanceUID', '')))
                  for _, ds in headers}
    sops = [str(ds.get('SOPInstanceUID', '')) for _, ds in headers]
    if len(identities) != 1 or any(not x for pair in identities for x in pair) or not all(sops) or len(set(sops)) != len(sops):
        raise ValueError('Invalid presentation sequence identity')
    estimate = 0
    document_workspace = 0
    for _, ds in headers:
        rows, cols = int(ds.get('Rows', 0)), int(ds.get('Columns', 0))
        components = int(ds.get('SamplesPerPixel', 1))
        photo = str(ds.get('PhotometricInterpretation', ''))
        if (str(ds.get('SOPClassUID', '')) not in allowed_sops
                or int(ds.get('NumberOfFrames', 1)) != 1 or rows <= 0 or cols <= 0
                or (photo, components) not in (('MONOCHROME2', 1), ('RGB', 3))
                or (components == 3 and int(ds.get('BitsAllocated', 0)) != 8)
                or str(ds.get('VOILUTFunction', 'LINEAR')) not in ('', 'LINEAR')
                or ds.get('VOILUTSequence') or ds.get('ModalityLUTSequence')
                or (is_dx and (photo != 'MONOCHROME2'
                    or str(ds.get('PresentationLUTShape', 'IDENTITY')) != 'IDENTITY'))):
            raise ValueError('Unsupported presentation frame layout')
        if is_document and components == 3:
            # Validated byte RGB is not promoted or filtered. Retain native buffers
            # plus a bounded largest-page decode/conversion workspace, not float64
            # storage for every component of every page.
            pixels = rows * cols
            native_bytes = pixels * components
            has_overlay = any((group, 0x3000) in ds for group in range(0x6000, 0x6020, 2))
            estimate += native_bytes + (pixels * 4 if has_overlay else 0)
            document_workspace = max(document_workspace,
                native_bytes * 4 + (pixels * 12 if has_overlay else 0))
        else:
            estimate += rows * cols * components * 8
    if estimate + document_workspace > MAX_BYTES:
        raise ValueError('Presentation sequence exceeds preparation memory limit')
    headers.sort(key=lambda pair: (int(pair[1].get('InstanceNumber', 0)), str(pair[1].SOPInstanceUID)))
    from .utils import convert_itk2vtk
    from .image_filters import apply_filters
    frames, overlays, instances = [], [], []
    for path, ds in headers:
        image = sitk.ReadImage(path)
        if image.GetDimension() != 3 or image.GetSize()[2] != 1:
            raise ValueError('Presentation decode is not a single frame')
        # Display coordinates only; the sequence has no common patient affine.
        image.SetOrigin((0.0, 0.0, 0.0))
        image.SetDirection((1.0,0.0,0.0,0.0,1.0,0.0,0.0,0.0,1.0))
        pixel_spacing = None
        calibration = None
        if is_dx or is_document:
            # Detector spacing preserves aspect/scale but is not patient calibration.
            spacing = ds.get('PixelSpacing')
            calibration = 'image_plane' if spacing is not None else 'detector'
            if spacing is None:
                spacing = ds.get('ImagerPixelSpacing') if is_dx else None
            if spacing is not None:
                spacing = tuple(float(v) for v in spacing)
                if len(spacing) != 2 or any(not np.isfinite(v) or v <= 0 for v in spacing):
                    raise ValueError('Invalid presentation spacing')
                image.SetSpacing((spacing[1], spacing[0], 1.0))
                if calibration == 'image_plane':
                    pixel_spacing = list(spacing)
            else:
                calibration = 'uncalibrated'
                image.SetSpacing((1.0, 1.0, 1.0))
        if str(ds.SOPClassUID) == MR or is_dx:
            image = apply_filters(image, {'series': {'modality': modality}}, max_itk_threads=max_itk_threads)
        frame = convert_itk2vtk(image)
        if (frame.GetDimensions() != (int(ds.Columns), int(ds.Rows), 1)
                or frame.GetNumberOfScalarComponents() != int(ds.SamplesPerPixel)):
            raise ValueError('Presentation decode does not match frame metadata')
        frames.append(frame)
        overlays.append(overlay_image(ds, image, convert_itk2vtk))
        def first_float(value):
            if value is None: return None
            if not isinstance(value, (str, int, float)): value = value[0]
            return float(value)
        lo, hi = frame.GetScalarRange()
        ww, wc = first_float(ds.get('WindowWidth')), first_float(ds.get('WindowCenter'))
        if ww is None or ww <= 0 or wc is None:
            ww, wc = max(1.0, hi - lo), (lo + hi) / 2.0
        instances.append(dict(instance_path=path, instance_number=int(ds.get('InstanceNumber', 0)),
            sop_uid=str(ds.SOPInstanceUID), rows=int(ds.Rows), columns=int(ds.Columns),
            is_rgb=int(ds.SamplesPerPixel) == 3, window_width=ww, window_center=wc,
            photometric_interpretation=str(ds.PhotometricInterpretation),
            image_orientation_patient=None, image_position_patient=None,
            slice_thickness=None, pixel_spacing=pixel_spacing,
            spacing_calibration=calibration))
    first = headers[0][1]
    study_uid, series_uid = next(iter(identities))
    metadata = dict(instances=instances, spatial_geometry_available=False, preview_only=False,
        instances_order_contract='ADVANCED_PRESENTATION_INSTANCE_ORDER',
        series=dict(series_number=str(series_number), series_uid=series_uid,
            series_instance_uid=series_uid, study_instance_uid=study_uid,
            series_path=str(Path(headers[0][0]).parent), modality=modality,
            series_thk='N/A',
            series_name=str(first.get('SeriesDescription', series_number)),
            series_description=str(first.get('SeriesDescription', '')),
            viewer_backend='vtk_simpleitk', spatial_geometry_available=False,
            orientation=None, geometry_plane='UNKNOWN', display_convention='UNKNOWN'))
    metadata[FRAME_KEY] = PresentationFrames(frames)
    metadata[OVERLAY_KEY] = PresentationFrames(overlays)
    return frames[0], metadata
