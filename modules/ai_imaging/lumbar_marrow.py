"""Server-only exploratory vertebral signal measurements, not red marrow fractions."""
import csv
import html
import math
from pathlib import Path

CLINICAL_FIELDS = {
    'ferritin_ng_ml': (0, 100000), 'transferrin_saturation_percent': (0, 100),
    'hemoglobin_g_dl': (0, 30), 'transfusions_per_year': (0, 1000),
    'dxa_z_score': (-15, 15), 'liver_iron_mg_g_dry': (0, 100),
    'cardiac_t2star_ms': (0, 200),
}
LIMITATION = ('Research draft. The ROI is an eroded whole-vertebra segmentation, '
              'not a validated vertebral-body marrow segmentation; posterior elements may remain. '
              'Inspect the segmentation and sampling overlay before interpretation. '
              'T1 signal is in arbitrary units and depends on acquisition and scaling. '
              'No red marrow percentage, fat fraction, iron concentration, diagnostic threshold '
              'or treatment recommendation can be derived from these measurements.')


def validate_parameters(params):
    if params.get('t1_confirmed') is not True:
        raise ValueError('Confirm native non-fat-suppressed, precontrast T1-weighted lumbar images.')
    clinical = params.get('clinical', {})
    if not isinstance(clinical, dict) or set(clinical) - (set(CLINICAL_FIELDS) | {'emh'}):
        raise ValueError('Unsupported marrow clinical fields.')
    for key, value in clinical.items():
        if key == 'emh':
            if value not in ('unknown', 'absent', 'present'):
                raise ValueError('Invalid physician-entered EMH status.')
        elif (type(value) not in (int, float) or not math.isfinite(value)
              or not CLINICAL_FIELDS[key][0] <= value <= CLINICAL_FIELDS[key][1]):
            raise ValueError('Clinical values must be finite and within the supported range.')


def validate_t1_headers(filenames):
    """Reject known incompatible acquisitions; physician confirmation remains mandatory."""
    import pydicom
    for filename in filenames:
        ds = pydicom.dcmread(filename, stop_before_pixels=True)
        text = ' '.join(str(ds.get(k, '')) for k in
                        ('SeriesDescription', 'ProtocolName', 'SequenceName', 'ScanOptions', 'ImageType')).lower()
        if (any(token in text for token in ('flair', 'stir', 'dixon', 't1map', 't1 map', 'fat sat', 'fat-sat', 't2', 'post', 'derived'))
                or 'FS' in ds.get('ScanOptions', []) or ds.get('ContrastBolusAgent')):
            raise ValueError('The experimental marrow workflow requires native precontrast non-fat-suppressed T1.')


def measure(array, labels, affine, segments, directory, params):
    import numpy as np
    validate_parameters(params)
    array, labels, affine = np.asarray(array), np.asarray(labels), np.asarray(affine, dtype=float)
    if (array.ndim != 3 or labels.shape != array.shape or affine.shape != (4, 4)
            or not np.isfinite(array).all() or not np.isfinite(affine).all()):
        raise ValueError('Signal and segmentation geometry must be identical and finite.')
    basis = affine[:3, :3]
    spacing = np.linalg.norm(basis, axis=0)
    if np.any(spacing <= 0) or not np.allclose((basis / spacing).T @ (basis / spacing), np.eye(3), atol=1e-4):
        raise ValueError('Orthogonal volume geometry is required for physical erosion.')
    voxel_volume = abs(float(np.linalg.det(basis)))
    roi_labels = np.zeros(labels.shape, dtype=labels.dtype)
    rows = []
    for segment in segments:
        name = segment['name']
        if name not in {f'vertebrae_L{i}' for i in range(1, 6)}:
            continue
        mask = labels == segment['label']
        # Physical-radius binary erosion. Outside-volume voxels count as background.
        radii = np.floor(2.0 / spacing[::-1]).astype(int)
        padded = np.pad(mask, [(int(r), int(r)) for r in radii])
        roi = mask.copy()
        import itertools
        for shift in itertools.product(*(range(-int(r), int(r) + 1) for r in radii)):
            if np.linalg.norm(np.asarray(shift) * spacing[::-1]) <= 2.0 + 1e-8:
                slices = tuple(slice(int(r + s), int(r + s + n)) for r, s, n in zip(radii, shift, mask.shape))
                roi &= padded[slices]
        count = int(roi.sum())
        row = dict(level=name.rsplit('_', 1)[-1], label=int(segment['label']),
                   whole_vertebra_voxels=int(mask.sum()), sample_voxels=count,
                   sample_volume_mm3=count * voxel_volume, mean_si=None, median_si=None,
                   p10_si=None, p90_si=None, std_si=None,
                   qc='insufficient_sample' if count < 20 else 'unreviewed')
        if count >= 20:
            values = array[roi].astype(float)
            row.update(mean_si=float(values.mean()), median_si=float(np.median(values)),
                       p10_si=float(np.percentile(values, 10)), p90_si=float(np.percentile(values, 90)),
                       std_si=float(values.std()))
            roi_labels[roi] = segment['label']
        rows.append(row)
    if not rows:
        raise ValueError('No lumbar vertebra labels were detected. No signal report was generated.')
    rows.sort(key=lambda row: row['level'])
    directory = Path(directory)
    np.save(directory / 'marrow-roi.npy', roi_labels, allow_pickle=False)
    with (directory / 'marrow.csv').open('w', newline='', encoding='utf-8') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    # Sagittal preview uses physical LR coordinates, including oblique acquisitions.
    from PIL import Image
    lr_axis = int(np.argmax(np.abs(basis[0])))
    axis = 2 - lr_axis
    counts = np.count_nonzero(roi_labels, axis=tuple(i for i in range(3) if i != axis))
    index = int(np.argmax(counts))
    image = np.take(array, index, axis=axis)
    overlay = np.take(roi_labels, index, axis=axis)
    low, high = np.percentile(array, [2, 98])
    gray = (np.clip((image.astype(float) - low) / max(float(high - low), 1e-8), 0, 1) * 255).astype(np.uint8)
    rgb = np.repeat(gray[..., None], 3, axis=2)
    for label in np.unique(overlay):
        if label:
            color = np.array([(int(label) * 97) % 200 + 55, (int(label) * 53) % 200 + 55, 90])
            selected = overlay == label
            rgb[selected] = (.55 * rgb[selected] + .45 * color).astype(np.uint8)
    Image.fromarray(rgb).save(directory / 'preview.png')
    columns = ['level', 'sample_voxels', 'sample_volume_mm3', 'mean_si', 'median_si', 'std_si', 'qc']
    table = '<tr>' + ''.join('<th>' + k + '</th>' for k in columns) + '</tr>'
    for row in rows:
        table += '<tr>' + ''.join('<td>' + html.escape(str(row[k])) + '</td>' for k in columns) + '</tr>'
    clinical = params.get('clinical', {})
    context = ''.join('<li>' + html.escape(k) + ': ' + html.escape(str(v)) + '</li>' for k, v in clinical.items())
    missing = ', '.join(f'L{i}' for i in range(1, 6) if f'L{i}' not in {r['level'] for r in rows})
    report = ('<!doctype html><html><body><h2>Lumbar Bone Marrow: Experimental T1</h2><p>'
              + LIMITATION + '</p><p>Sampling: 2 mm physical erosion; minimum 20 voxels. '
              'Missing levels: ' + (missing or 'none') + '</p><table border="1">' + table
              + '</table><h3>Physician-entered clinical context (not inferred)</h3><ul>'
              + (context or '<li>Not provided</li>') + '</ul><p>Report status: draft, not approved for patient delivery.</p>'
              '<img src="preview.png" width="600"></body></html>')
    (directory / 'report.html').write_text(report, encoding='utf-8')
    return dict(task='lumbar_marrow_t1_exploratory', marrow_measurements=rows,
                clinical_context=clinical, report_status='unreviewed_research_draft',
                roi_method='whole_vertebra_erosion_2mm', warning=LIMITATION,
                red_marrow_fraction=None, fat_fraction=None, iron_concentration=None,
                marrow_roi_file=str(directory / 'marrow-roi.npy'),
                marrow_csv=str(directory / 'marrow.csv'), report_html=str(directory / 'report.html'),
                preview=str(directory / 'preview.png'))
