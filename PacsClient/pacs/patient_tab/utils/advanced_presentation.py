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
ENHANCED_MR = '1.2.840.10008.5.1.4.1.1.4.1'
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
                (SC, 'MR'), (SC, 'DOC'), (DX_PRESENTATION, 'DX'), (ENHANCED_MR, 'MR')):
            return True
    return False


def _enhanced_frame_planes(ds, count):
    """Resolve frame planes only; never manufacture a volume affine.

    The known export anomaly inserts one display-only item before the final
    spatial item. Accept that shape only with ordered, unique 1..N frame content.
    Other mismatches retain viewable pixels with no spatial claims.
    """
    groups = list(ds.get('PerFrameFunctionalGroupsSequence', []))
    shared = ds.get('SharedFunctionalGroupsSequence', [])
    shared = shared[0] if shared else pydicom.Dataset()
    normalized = False
    if len(groups) != count:
        if len(groups) != count + 1 or count < 2:
            return [None] * count, False
        extra = groups[count - 1]
        if not extra or any(e.keyword not in ('FrameVOILUTSequence', 'PixelValueTransformationSequence') for e in extra):
            return [None] * count, False
        candidates = groups[:count - 1] + groups[count:]
        content = [g.get('FrameContentSequence', []) for g in candidates]
        if (any(len(c) != 1 for c in content)
                or [int(c[0].get('InStackPositionNumber', 0)) for c in content] != list(range(1, count + 1))
                or len({str(c[0].get('TemporalPositionIndex', '')) for c in content}) != 1):
            return [None] * count, False
        groups, normalized = candidates, True
    planes = []
    for group in groups:
        try:
            def value(sequence, keyword):
                items = group.get(sequence) or shared.get(sequence)
                return tuple(float(v) for v in items[0][keyword])
            ipp = value('PlanePositionSequence', 'ImagePositionPatient')
            iop = value('PlaneOrientationSequence', 'ImageOrientationPatient')
            spacing = value('PixelMeasuresSequence', 'PixelSpacing')
            if (len(ipp) != 3 or len(iop) != 6 or len(spacing) != 2
                    or not np.isfinite((*ipp, *iop, *spacing)).all() or min(spacing) <= 0
                    or not np.isclose(np.linalg.norm(iop[:3]), 1, atol=1e-4)
                    or not np.isclose(np.linalg.norm(iop[3:]), 1, atol=1e-4)
                    or abs(np.dot(iop[:3], iop[3:])) > 1e-4):
                raise ValueError('Invalid frame plane')
            planes.append(dict(image_position_patient=ipp, image_orientation_patient=iop,
                pixel_spacing=spacing, slice_location=float(np.dot(ipp, np.cross(iop[:3], iop[3:]))),
                frame_of_reference_uid=str(ds.get('FrameOfReferenceUID', ''))))
        except (KeyError, IndexError, TypeError, ValueError):
            planes.append(None)
    return planes, normalized


def _load_enhanced_mr_frames(headers, series_number):
    """Worker-only 2D presentation; never claim a spatial volume for these frames.

    Pixel frame index remains authoritative. Malformed group counts are allowed
    only when every item has identical rescale transforms and declared spacing, so
    no reassignment of ambiguous geometry or intensity transforms is necessary.
    """
    if len(headers) != 1:
        raise ValueError('Enhanced MR presentation requires one image object')
    path, ds = headers[0]
    n, rows, cols = int(ds.get('NumberOfFrames', 0)), int(ds.get('Rows', 0)), int(ds.get('Columns', 0))
    if (min(n, rows, cols) <= 0 or int(ds.get('SamplesPerPixel', 1)) != 1
            or str(ds.get('PhotometricInterpretation', '')) != 'MONOCHROME2'
            or ds.get('ModalityLUTSequence') or ds.get('VOILUTSequence')
            or str(ds.get('PresentationLUTShape', 'IDENTITY')) != 'IDENTITY'):
        raise ValueError('Unsupported Enhanced MR presentation pixels')
    if n * rows * cols * 16 > MAX_BYTES:
        raise ValueError('Enhanced MR presentation exceeds preparation memory limit')
    identities = [str(ds.get(key, '')) for key in ('StudyInstanceUID', 'SeriesInstanceUID', 'SOPInstanceUID')]
    if not all(identities):
        raise ValueError('Invalid Enhanced MR identity')
    shared = ds.get('SharedFunctionalGroupsSequence', [])
    shared = shared[0] if shared else pydicom.Dataset()
    groups = list(ds.get('PerFrameFunctionalGroupsSequence', []))

    def display_values(group):
        def macro(name):
            value = group.get(name) or shared.get(name)
            return value[0] if value else ds
        transform, measures = macro('PixelValueTransformationSequence'), macro('PixelMeasuresSequence')
        voi = macro('FrameVOILUTSequence')
        if (transform.get('ModalityLUTSequence') or voi.get('VOILUTSequence')
                or str(voi.get('VOILUTFunction', 'LINEAR')) not in ('', 'LINEAR')):
            raise ValueError('Unsupported Enhanced MR display transform')
        slope = float(transform.get('RescaleSlope', 1))
        intercept = float(transform.get('RescaleIntercept', 0))
        raw_spacing = measures.get('PixelSpacing')
        spacing = tuple(float(v) for v in raw_spacing) if raw_spacing is not None else None
        def first(value):
            if value is None: return None
            return float(value if isinstance(value, (str, float, int)) else value[0])
        ww, wc = first(voi.get('WindowWidth')), first(voi.get('WindowCenter'))
        if (not np.isfinite((slope, intercept)).all() or slope == 0
                or (spacing is not None and (len(spacing) != 2
                    or not np.isfinite(spacing).all() or min(spacing) <= 0))
                or any(v is not None and not np.isfinite(v) for v in (ww, wc))):
            raise ValueError('Invalid Enhanced MR display transform')
        return slope, intercept, spacing, ww, wc

    values = [display_values(g) for g in groups] or [display_values(pydicom.Dataset())]
    if len(groups) != n:
        transforms = {(v[0], v[1]) for v in values}
        spacings = {v[2] for v in values if v[2] is not None}
        if len(transforms) != 1 or len(spacings) > 1:
            raise ValueError('Ambiguous Enhanced MR functional-group display transforms')
        slope, intercept = next(iter(transforms))
        # Do not assign an ambiguous item's VOI to a pixel frame. Each decoded
        # plane receives its own scalar-range window; user windowing still works.
        values = [(slope, intercept, next(iter(spacings), None), None, None)] * n
    decoded = pydicom.dcmread(path)
    if ([str(decoded.get(key, '')) for key in
            ('StudyInstanceUID', 'SeriesInstanceUID', 'SOPInstanceUID')] != identities
            or int(decoded.get('NumberOfFrames', 0)) != n):
        raise ValueError('Enhanced MR identity changed during preparation')
    pixels = decoded.pixel_array
    if pixels.shape != (n, rows, cols):
        raise ValueError('Enhanced MR decoded frame count or shape mismatch')
    from .utils import convert_itk2vtk
    frames, instances = [], []
    planes, normalized_planes = _enhanced_frame_planes(ds, n)
    for index, (slope, intercept, spacing, ww, wc) in enumerate(values):
        plane = pixels[index].astype(np.float64) * slope + intercept
        image = sitk.GetImageFromArray(plane[np.newaxis, :, :])
        spacing = spacing or (1.0, 1.0)
        image.SetSpacing((spacing[1], spacing[0], 1.0))
        frame = convert_itk2vtk(image)
        frames.append(frame)
        lo, hi = frame.GetScalarRange()
        if ww is None or ww <= 0 or wc is None:
            ww, wc = max(1.0, hi - lo), (lo + hi) / 2
        instances.append(dict(instance_path=path, instance_number=index + 1,
            frame_index=index, number_of_frames=n, sop_uid=identities[2],
            rows=rows, columns=cols, is_rgb=False, window_width=ww, window_center=wc,
            photometric_interpretation='MONOCHROME2', image_orientation_patient=None,
            image_position_patient=None, pixel_spacing=None, slice_thickness=None,
            spacing_calibration='uncalibrated'))
        if planes[index] is not None:
            instances[-1].update(planes[index])
    metadata = dict(instances=instances, spatial_geometry_available=False, preview_only=False,
        instances_order_contract='ADVANCED_PRESENTATION_FRAME_ORDER',
        series=dict(series_number=str(series_number), series_uid=identities[1],
            series_instance_uid=identities[1], study_instance_uid=identities[0],
            series_path=str(Path(path).parent), modality='MR', series_thk='N/A',
            series_name=str(ds.get('SeriesDescription', series_number)),
            series_description=str(ds.get('SeriesDescription', '')),
            viewer_backend='vtk_simpleitk', spatial_geometry_available=False,
            orientation=None, geometry_plane='UNKNOWN', display_convention='UNKNOWN'))
    metadata['frame_geometry_available'] = any(p is not None for p in planes)
    metadata['frame_geometry_normalized'] = normalized_planes
    metadata['series']['frame_of_reference_uid'] = str(ds.get('FrameOfReferenceUID', ''))
    metadata[FRAME_KEY] = PresentationFrames(frames)
    metadata[OVERLAY_KEY] = PresentationFrames([None] * n)
    return frames[0], metadata


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
    if any(str(ds.get('SOPClassUID', '')) == ENHANCED_MR for _, ds in headers):
        return _load_enhanced_mr_frames(headers, series_number)
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
