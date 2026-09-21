"""Private, atomic PDF and JSON reports from immutable review snapshots."""
from html import escape
from pathlib import Path
import base64
import hashlib
import io
import json
import os
import tempfile
import uuid

from .measurements import SOURCES, validate_report_views


def evidence(view, measured, reviewed=False):
    from .annotations import annotated_image
    raster = annotated_image(view, measured, reviewed=reviewed)
    scale = min(530/raster.width, 620/raster.height)
    stream = io.BytesIO(); raster.save(stream, format='PNG')
    return f'<img width="{int(raster.width*scale)}" height="{int(raster.height*scale)}" src="data:image/png;base64,{base64.b64encode(stream.getvalue()).decode()}" />'


def render_html(views, measurements, reviewed, notes):
    from ..eagle_eye_brain.organized_report import PAGE
    pages = []
    sections = []
    for view, measured in zip(views, measurements):
        count = max(1, (len(measured['curves'])+1)//2, (len(measured['rotations'])+3)//4)
        for index in range(count):
            section = dict(measured, curves=measured['curves'][index*2:index*2+2],
                           rotations=measured['rotations'][index*4:index*4+4])
            sections.append((view, section))
    for view, measured in sections:
        image = view['image']; identity = image['identity']
        title = 'Coronal alignment' if image['projection'] == 'coronal' else 'Sagittal alignment'
        state = 'MEASUREMENT LANDMARKS REVIEWED - not digitally signed' if reviewed else 'DRAFT - landmarks and numbering require review'
        body = f'<h1>Total Spine Alignment | {title}</h1><p><b>{state}</b></p>'
        body += '<p>'+escape(' | '.join(str(identity.get(k, '')) for k in ('patient_name', 'patient_id', 'study_date')))+'</p>'
        body += '<p>Series '+escape(str(identity.get('series_number', '')))+' | '+escape(str(identity.get('series_description', '')))+' | Image '+escape(str(identity.get('instance_number', '')) )+'</p>'
        table = '<h2>Curve measurements</h2>'
        if not measured['curves']:
            table += '<p>No curve measured.</p>'
        for result in measured['curves']:
            table += f'<p><b>{escape(result["name"])}: {result["cobb_deg"]:.1f} deg</b><br/>'
            table += escape(f'{result["upper"]} superior to {result["lower"]} {result["lower_endplate"]}')+'<br/>'
            if result['convexity']:
                table += 'Convexity: '+escape(result['convexity'])+'<br/>'
            table += 'Reader apex: '+escape(result['apex'] or 'not assessed')
            if result['apex_candidate']:
                table += '<br/>Geometric apex candidate: '+escape(result['apex_candidate'])+' (verify body/disc)'
            assessment = result.get('coronal_assessment', {})
            if assessment:
                table += '<br/>CSVL apex proposal: '+escape(str(assessment['apex_csvl_candidate'] or 'unavailable'))
                for key in ('stable', 'neutral', 'last_touched'):
                    table += '<br/>'+escape(key.replace('_', ' ').title()+': '+str(assessment['reader'][key] or 'not assessed')+'; proposal: '+str(assessment[key+'_candidate'] or 'unavailable'))
            table += '</p>'
            table += '<p>'+escape(result['selection_source'])+'.</p>'
        if measured['balance']:
            balance = measured['balance']
            table += f'<h2>{escape(balance["name"])}</h2><p>{balance["value"]:+.2f} {balance["unit"]}; positive {escape(balance["positive"])}.</p>'
        table += '<h2>Axial rotation</h2>'
        if measured['rotations']:
            for rotation in measured['rotations']:
                table += '<p>'+escape(f'{rotation["level"]}: Nash-Moe grade {rotation["grade"]}, {rotation["direction"]}. Reader assessment; not degrees.')+'</p>'
        else:
            table += '<p>Not assessed. Endplate tilt is not axial rotation.</p>'
        table += '<p>Scale: '+escape(image['calibration_method'])+'.</p>'
        if not image['calibrated']:
            table += '<p>Unverified absolute scale: distances remain pixels. Angles use the recorded pixel aspect.</p>'
        body += table
        pages.append(body)
        body = '<h1>Annotated measurement evidence</h1><p>'+state+'</p>'+evidence(view, measured, reviewed)
        body += '<p>Method: '+escape(str(view.get('provenance', {}).get('model', 'Manual landmark placement')))+'. Source coordinates retained; all numbering requires reader confirmation.</p>'
        pages.append(body)
    appendix = '<h1>Method, interpretation and review</h1>'
    appendix += '<h2>Clinician impression</h2><p>'+escape(notes or 'Not provided.')+'</p>'
    appendix += '<p>Cobb values use the specified endplates after row/column aspect correction. Sagittal values are unsigned magnitudes; the reader selects kyphosis, lordosis or regional angle. Record vertebral endpoints when comparing examinations.</p>'
    appendix += '<p>The apex candidate is the body centroid furthest from the end-vertebra centroid chord. It is a proposal, not an anatomical apex determination. An apex may lie at a disc. Nash-Moe is an ordinal visual pedicle assessment; no degree conversion is performed.</p>'
    appendix += '<p>Balance uses a horizontal distance from the C7 plumb line to the sacral center (coronal) or S1 posterior-superior corner (lateral). The operator verifies vertical acquisition and anatomical sign. Blue marks show superior endplates; yellow marks show inferior endplates. CSVL is green; C7 and distance references are pink.</p>'
    appendix += '<p>No universal age-independent normal ranges or surgical targets are assigned. Projection, positioning, magnification, image stitching, transitional vertebrae and endplate visibility affect results. Missing projections and unmeasured parameters are not normal findings. No automatic diagnosis, Lenke classification, true 3D rotation or treatment plan is generated.</p>'
    appendix += '<p>Coronal proposals use available numbered body outlines only. CSVL apex maximizes lateral centroid displacement; stable proposal minimizes normalized centroid displacement among CSVL-touched bodies at or below the lower endpoint. These are geometric proposals, not definitive anatomical selections. Last-touched uses the most cephalad CSVL-touched body among T11-L5; verify coverage and convention. Neutral proposal uses the first recorded Nash-Moe grade-zero level below the apex; it does not infer rotation from endplate tilt.</p>'
    appendix += '<h2>Sources</h2>'+''.join('<p>'+escape(label)+'<br/>'+escape(url)+'</p>' for label, url in SOURCES)
    pages.append(appendix)
    patient = escape(' | '.join(str(views[0]['image']['identity'].get(k, '')) for k in ('patient_name', 'patient_id', 'study_date')), quote=True)
    return ('<html><head><meta charset="utf-8"><meta name="brain-patient" content="'+patient+'">'
            '<style>body{font:10pt Arial;color:#172b45;}h1{font-size:17pt;}h2{font-size:12pt;color:#256087;}td{padding:7px;}p{margin:7px 0;}</style></head><body>'+
            PAGE.join(pages)+'</body></html>')


def generate_report(views, study_uid, reviewed=False, notes='', *, root=None):
    from ..eagle_eye_brain.organized_report import write_paged_pdf
    from ..eagle_eye_alignment.service import digest
    from PacsClient.utils.data_paths import AI_DIR
    measured = validate_report_views(views, study_uid, reviewed=reviewed)
    if len(notes) > 2000:
        raise ValueError('Report impression is too long.')
    base = Path(root or AI_DIR/'eagle_eye'/'total-spine')/'studies'/hashlib.sha256(study_uid.encode()).hexdigest()
    base.mkdir(parents=True, exist_ok=True)
    destination = base/uuid.uuid4().hex
    with tempfile.TemporaryDirectory(dir=base, prefix='.report-') as temporary:
        folder = Path(temporary)
        document = render_html(views, measured, reviewed, notes)
        write_paged_pdf(document, folder/'report.pdf', title='AI-PACS | Total Spine Alignment | Review required',
                        heading='AI-PACS  |  EAGLE EYE TOTAL SPINE')
        payload = dict(format_version=1, study_uid=study_uid, landmarks_reviewed=reviewed,
                       clinical_report_signed=False, notes=notes, sources=SOURCES, views=[],
                       pdf_sha256=digest(folder/'report.pdf'))
        from .annotations import annotated_image
        for view, result in zip(views, measured):
            filename = view['image']['projection']+'-annotated.png'
            annotated_image(view, result, reviewed=reviewed).save(folder/filename)

            safe = {key: value for key, value in view.items() if key != 'image'}
            safe['image'] = {key: value for key, value in view['image'].items() if key != 'pixels'}
            safe['measurements'] = result
            safe['annotated_image'] = dict(filename=filename, sha256=digest(folder/filename))
            payload['views'].append(safe)
        (folder/'report.json').write_text(json.dumps(payload, indent=2, allow_nan=False), encoding='utf-8')
        (folder/'report.html').write_text(document, encoding='utf-8')
        os.replace(folder, destination)
    return {'artifact_directory': str(destination), 'pdf_available': True}
