"""Validated review snapshots shared by the UI and report generator."""
from .geometry import (LEVELS, CORNERS, measure_curve, suggest_apex, validate_landmarks,
                       horizontal_offset, rotation_record, point)

SOURCES = (
    ('SRS terminology: Cobb method, end vertebrae, apex and sagittal alignment.',
     'https://www.srs.org/Education/Glossary'),
    ('Spinal Deformity Study Group. Radiographic Measurement Manual, 2008.',
     'https://www.srs.org/Files/Research/Manuals-and-Publications/sdsg-radiographic-measuremnt-manual.pdf'),
    ('Yi et al. Vertebra-Focused Landmark Detection for Scoliosis Assessment, ISBI 2020.',
     'https://arxiv.org/abs/2001.03187'),
    ('DICOM PS3.3 section 10.7: pixel spacing and calibration.',
     'https://dicom.nema.org/medical/dicom/current/output/chtml/part03/sect_10.7.html'),
)


def measure_view(view):
    image, points = view['image'], view['points']
    projection = image['projection']
    if projection not in ('coronal', 'lateral'):
        raise ValueError('Invalid image projection.')
    # Only selected measurement evidence is required; unused AI points cannot block a curve.
    from .review_workflow import required_points, curve_is_reviewed
    for spec in view.get('curves', []):
        validate_landmarks(required_points(points, spec), image['pixels'].shape)
    rows = []
    for spec in view.get('curves', []):
        name = spec['name']
        if name not in (('Scoliosis Cobb',) if projection == 'coronal' else ('Thoracic kyphosis', 'Lumbar lordosis', 'Regional sagittal angle')):
            raise ValueError('The curve type does not match this projection.')
        result = measure_curve(points, spec['upper'], spec['lower'],
                               lower_endplate=spec.get('lower_endplate', 'inferior'), spacing=image['spacing'])
        apex = spec.get('apex', '')
        if apex:
            # An apex may be a vertebral body or the intervening disc.
            levels = apex.split('/')
            if (len(levels) not in (1, 2) or any(x not in LEVELS for x in levels) or
                any(not LEVELS.index(spec['upper']) < LEVELS.index(x) < LEVELS.index(spec['lower']) for x in levels) or
                (len(levels) == 2 and LEVELS.index(levels[1])-LEVELS.index(levels[0]) != 1)):
                raise ValueError('Select an internal vertebral or adjacent-disc apex.')
        result.update(name=name, apex=apex or None, endplates_reviewed=curve_is_reviewed(view, spec),
                      selection_source=spec.get('selection_source', 'Reader-selected endpoints'),
                      apex_candidate=suggest_apex(points, spec['upper'], spec['lower'], image['spacing']) if projection == 'coronal' else None,
                      angle_convention='unsigned endplate angle; named by reader',
                      convexity=spec.get('convexity', 'not assessed') if projection == 'coronal' else None)
        if result['convexity'] not in (None, 'right', 'left', 'not assessed'):
            raise ValueError('Invalid curve convexity.')
        result["curve_number"] = len(rows)+1
        rows.append(result)
    rotations = []
    for rotation in view.get('rotations', []):
        if projection != 'coronal':
            raise ValueError('Nash-Moe assessment requires a coronal radiograph.')
        rotations.append(rotation_record(rotation['level'], rotation['grade'], rotation['direction']))
    markers = view.get('markers', {})
    h, w = image['pixels'].shape
    for level, evidence in view.get('pedicles', {}).items():
        if projection != 'coronal' or level not in LEVELS:
            raise ValueError('Pedicle rotation evidence requires a valid coronal vertebral level.')
        if not set(evidence).issubset(('image_left', 'image_right')):
            raise ValueError('Unknown pedicle landmark.')
        for value in evidence.values():
            x, y = point(value)
            if not (0 <= x < w and 0 <= y < h):
                raise ValueError('Pedicle landmark is outside the image.')
        if all(k in evidence for k in ('image_left', 'image_right')) and evidence['image_left'][0] >= evidence['image_right'][0]:
            raise ValueError('Image-left pedicle must lie left of image-right pedicle.')
    allowed = ('C7 center', 'Sacral center') if projection == 'coronal' else ('C7 center', 'S1 posterior superior')
    if not set(markers).issubset(allowed):
        raise ValueError('Unexpected balance landmark for this projection.')
    for value in markers.values():
        x, y = point(value)
        if not (0 <= x < w and 0 <= y < h):
            raise ValueError('Balance landmark is outside the image.')
    balance = None
    reference = allowed[1]
    if all(k in markers for k in allowed):
        if markers['C7 center'][1] >= markers[reference][1]:
            raise ValueError('C7 must be above the sacral reference in an upright image.')
        balance = horizontal_offset(markers['C7 center'], markers[reference], image['spacing'],
                                    calibrated=image['calibrated'], positive_image_right=view.get('positive_image_right', True))
        balance.update(name='Coronal balance' if projection == 'coronal' else 'Sagittal vertical axis',
                       positive='patient right' if projection == 'coronal' else 'anterior')
    if projection == 'coronal':
        from .assessment import coronal_assessment
        for spec, row in zip(view.get('curves', []), rows):
            row['coronal_assessment'] = coronal_assessment(view, spec)
    return dict(curves=rows, rotations=rotations, balance=balance)


def validate_report_views(views, study_uid, *, reviewed=False):
    if not study_uid or not views:
        raise ValueError('Load at least one image for this examination.')
    projections, patients, sop_uids = set(), set(), set()
    output = []
    for view in views:
        image = view['image']
        identity = image['identity']
        if (identity.get('study_uid') != study_uid or not identity.get('series_uid') or not identity.get('sop_uid') or
            not image.get('source_sha256')):
            raise ValueError('All report images must retain their verified examination and image identity.')
        if image['projection'] in projections or identity['sop_uid'] in sop_uids:
            raise ValueError('Each projection requires a distinct image.')
        projections.add(image['projection']); sop_uids.add(identity['sop_uid'])
        if identity.get('patient_id'):
            patients.add(identity['patient_id'])
        if len(patients) > 1:
            raise ValueError('Report images contain conflicting patient identities.')
        if not view.get('acquisition_confirmed'):
            raise ValueError('Confirm upright acquisition, projection and orientation for each image.')
        if reviewed and view.get('review_protocol') == 'selected-endplates-v1':
            from .review_workflow import curve_is_reviewed
            if any(not curve_is_reviewed(view, spec) for spec in view.get('curves', [])):
                raise ValueError('Confirm the selected endplates and numbering for each curve.')
        if reviewed and not view.get('landmarks_reviewed'):
            raise ValueError('Review acquisition and the landmarks used by the recorded measurements first.')
        measured = measure_view(view)
        if not measured['curves'] and measured['balance'] is None and not measured['rotations']:
            raise ValueError('Add a valid curve, balance measurement or rotation assessment for every loaded image.')
        output.append(measured)
    return output
