"""Three-page alignment PDF using the established Eagle Eye report furniture.

Call from a background worker with an immutable image/landmark snapshot.
"""
from html import escape
from pathlib import Path
import base64
import io
import json
import os
import tempfile
import uuid

import numpy as np

from .geometry import MEASUREMENT_LABELS, measure_bilateral
from .references import reference_text, reference_manifest, scope_text, SOURCES

CORE = ('hka_deg', 'mad', 'mldfa_deg', 'mpta_deg', 'jlca_deg', 'limb_length')
ADVANCED = ('ldta_deg', 'ahka_deg', 'femur_length', 'tibia_length')
REFERENCES = (
    ('Luis & Varatojo. Radiological assessment of lower limb alignment. EFORT Open Rev 2021.',
     'https://doi.org/10.1302/2058-5241.6.210015'),
    ('MacDessi et al. Coronal Plane Alignment of the Knee classification. Bone Joint J 2021.',
     'https://doi.org/10.1302/0301-620X.103B2.BJJ-2020-1050.R1'),
    ('DICOM PS3.3, section 10.7: pixel spacing and calibration.',
     'https://dicom.nema.org/medical/dicom/current/output/chtml/part03/sect_10.7.html'),
)


def evidence(image, points, *, region='full', width=250, height=540):
    """Rasterize overlays in source coordinates before cropping/resizing."""
    from PIL import Image, ImageDraw, ImageFont
    raster = Image.fromarray(image['pixels']).convert('RGB')
    draw = ImageDraw.Draw(raster)
    size = max(14, raster.width // 65)
    font = ImageFont.load_default(size=size)
    radius = max(4, raster.width // 280)
    for side, color in (('R', '#38bdf8'), ('L', '#fb923c')):
        p = points[side]
        ankle = np.mean([p['ankle_lateral'], p['ankle_medial']], axis=0)
        pairs = [(p['hip'], p['knee']), (p['knee'], ankle), (p['hip'], ankle)]
        pairs += [(p[k+'_lateral'], p[k+'_medial']) for k in ('femur','tibia','ankle')]
        for a, b in pairs:
            draw.line([tuple(a), tuple(b)], fill=color, width=max(2, radius // 2))
        for index, key in enumerate(('hip','knee','femur_lateral','femur_medial',
                                      'tibia_lateral','tibia_medial','ankle_lateral','ankle_medial'), 1):
            x, y = p[key]
            draw.ellipse((x-radius,y-radius,x+radius,y+radius), fill=color)
            draw.text((x+radius*2,y-radius*2), f'{side}{index}', font=font, fill=color,
                      stroke_width=max(1,size//12), stroke_fill='black')
    if region != 'full':
        side, joint = region.split('_')
        p = points[side]
        center = (np.asarray(p['hip']) if joint == 'hip' else
                  np.asarray(p['knee']) if joint == 'knee' else
                  np.mean([p['ankle_lateral'],p['ankle_medial']],axis=0))
        joint_width = np.linalg.norm(np.asarray(p['femur_lateral'])-p['femur_medial'])
        extent = max(joint_width*2, raster.width*.13)
        x,y = center
        raster = raster.crop((max(0,int(x-extent/2)),max(0,int(y-extent/2)),
                              min(raster.width,int(x+extent/2)),min(raster.height,int(y+extent/2))))
    scale = min(width/raster.width, height/raster.height)
    display_w, display_h = raster.width*scale, raster.height*scale
    raster = raster.resize((max(1,int(display_w*2)),max(1,int(display_h*2))), Image.Resampling.LANCZOS)
    stream = io.BytesIO(); raster.save(stream, format='PNG')
    return f'<img width="{int(display_w)}" height="{int(display_h)}" src="data:image/png;base64,{base64.b64encode(stream.getvalue()).decode()}"/>'


def render_html(image, points, provenance, notes=None, landmarks_reviewed=False):
    from ..eagle_eye_brain.organized_report import PAGE, _table
    from .service import validate_points
    validate_points(points,image['pixels'].shape)
    m = measure_bilateral(points,image['spacing'],calibrated=image['calibrated'])
    notes = notes or {}
    for key in ('indication','comparison','impression'):
        if len(str(notes.get(key,''))) > 500:
            raise ValueError('Report text exceeds 500 characters. Shorten it before generating the PDF.')
    context = image['identity']
    field = lambda key: escape(str(context.get(key) or 'Not provided'))
    note = lambda key: escape(str(notes.get(key) or 'Not provided')).replace('\n','<br/>')
    unit = m['R']['length_unit']
    def measurements(keys):
        rows = [[MEASUREMENT_LABELS[k],f"{m['R'][k]:.2f}",f"{m['L'][k]:.2f}",
                 'deg' if k.endswith('_deg') else unit,reference_text(k,image)] for k in keys]
        return _table(['Measurement','Right','Left','Unit','Adult reference / context'],rows,[25,15,15,8,37])
    patient = ' | '.join(str(context.get(k) or 'Not provided') for k in ('patient_name','patient_id','study_date'))
    head = ('<!doctype html><html><head><meta charset="utf-8">'
            '<meta name="brain-patient" content="'+escape(patient,quote=True)+'">'
            '<style>body{font-family:Arial;font-size:9pt;color:#203e54}h1{font-size:16pt}'
            'h2{font-size:11pt}td,th{border-bottom:1px solid #cbd5e1}p{margin:5px 0}</style></head>')
    cover = '<h1>Lower-limb alignment | Core measurements</h1>'
    cover += '<p><b>Status: '+('Landmarks reviewed; clinical signature pending.' if landmarks_reviewed else 'Draft; landmark and clinical review required.')+'</b></p>'
    cover += f'<p><b>Institution:</b> {field("institution")} | <b>Accession:</b> {field("accession")}</p>'
    cover += f'<p><b>Birth date (YYYYMMDD):</b> {field("birth_date")} | <b>Sex:</b> {field("sex")}</p>'
    cover += f'<p><b>Primary series:</b> {field("series_number")} - {field("series_description")} | Image {field("instance_number")}</p>'
    technique = ('Standing AP bilateral hip-to-ankle radiograph; orientation and coverage reviewed by operator.'
                 if provenance.get('acquisition_reviewed') is True else
                 'Bilateral hip-to-ankle radiograph; weight-bearing positioning and laterality require operator verification.')
    cover += '<p><b>Technique:</b> '+technique+'</p>'
    cover += f'<p><b>Indication:</b> {note("indication")}<br/><b>Comparison:</b> {note("comparison")}</p>'
    body = measurements(CORE)
    body += f'<p><b>Projected length difference (R - L): {m["lld"]:.2f} {unit}.</b></p>'
    body += '<p>Reference: '+escape(reference_text('lld',image))+'.</p>'
    shorter = {'R':'Right shorter','L':'Left shorter','equal':'Equal projected lengths'}[m['shorter_side']]
    body += f'<p><b>Relative length difference: {m["lld_percent"]:.2f}% ({shorter}).</b><br/>'
    body += '100 x absolute difference / longer limb.<br/>Reference: '+escape(reference_text('lld_percent',image))+'.</p>'
    body += '<p>Percentage uses pixel-aspect-corrected projected lengths and assumes common magnification. A ruler is not required for this ratio; positioning and stitching can affect it.</p>'
    body += '<p>HKA: 0 neutral, negative varus, positive valgus.<br/>MAD: positive medial, negative lateral.<br/>JLCA: unsigned magnitude.</p>'
    body += '<p><b>Scale:</b> '+escape(image['calibration_method'])+'</p>'
    if not image['calibrated']:
        body += '<p><b>Lengths are pixels;</b> physical leg-length discrepancy cannot be determined until patient-plane calibration is verified.</p>'
    body += '<h2>Impression / clinician assessment</h2><p>'+note('impression')+'</p>'
    cover += '<table width="100%" cellpadding="6"><tr><td width="40%">'+evidence(image,points)+ '</td><td width="60%">'+body+'</td></tr></table>'
    cover += '<p>Blue = patient right; orange = patient left. Image and table use the same point snapshot.</p>'
    cover += '<p>'+escape(scope_text(image))+'</p>'
    advanced = '<h1>Advanced measurements | Joint orientation</h1>'+measurements(ADVANCED)
    advanced += _table(['Derived quantity','Right','Left','Unit','Adult reference / context'],[
        ['JLO (MPTA + mLDFA)',f'{m["R"]["mpta_deg"]+m["R"]["mldfa_deg"]:.2f}',f'{m["L"]["mpta_deg"]+m["L"]["mldfa_deg"]:.2f}','deg',reference_text('jlo_deg',image)]], [28,12,12,10,38])
    advanced += '<p>aHKA = MPTA - mLDFA; JLO here is the arithmetic CPAK sum, not the angle to the floor. These descriptors do not themselves establish a native phenotype in operated or deformed joints. No automatic CPAK class or surgical target is assigned.</p>'
    advanced += '<table width="100%"><tr><th>Right knee</th><th>Left knee</th></tr><tr><td>'+evidence(image,points,region='R_knee',width=280,height=280)+'</td><td>'+evidence(image,points,region='L_knee',width=280,height=280)+'</td></tr></table>'
    advanced += '<h2>Length definitions</h2><p>Femur: hip center to distal femoral joint midpoint. Tibia: plateau midpoint to ankle center. Whole limb: direct hip-to-ankle distance, not the sum of bone lengths. All are two-dimensional projected lengths.</p>'
    advanced += '<p>mLDFA and MPTA use the shared reviewed knee center. LDTA uses the ankle joint line and proximal tibial mechanical vector. Joint endpoints must represent the intended subchondral surfaces.</p>'
    audit = '<h1>Landmark evidence | Method and limitations</h1>'
    for joint in ('hip','ankle'):
        audit += '<table width="100%"><tr><th>Right '+joint+'</th><th>Left '+joint+'</th></tr><tr><td>'+evidence(image,points,region='R_'+joint,width=220,height=180)+'</td><td>'+evidence(image,points,region='L_'+joint,width=220,height=180)+'</td></tr></table>'
    audit += '<p><b>Point key:</b> 1 hip center; 2 shared knee center; 3/4 lateral/medial distal femur; 5/6 lateral/medial tibial plateau; 7/8 lateral/medial ankle. Mechanical axes join hip-knee-ankle; the whole-limb line joins hip and ankle.</p>'
    audit += '<p><b>Limitations:</b> Loading, flexion, rotation, stitching and magnification affect measurements. References require matching landmarks and axis definitions; LDTA requires true plafond endpoints. MAD is a published summary, not a 95% interval. No age-specific norms or automatic diagnosis are supplied.</p>'
    audit += '<p><b>Method:</b> '+escape(str(provenance.get('model','Manual')))+'; editable landmarks and deterministic geometry. Review of landmarks is not a signed clinical report.</p>'
    audit += '<h2>Method references</h2>'+''.join('<p>['+number+'] '+escape(label)+'<br/>'+escape(url)+'</p>' for number,label,url in SOURCES)
    audit += '<p>Calibration: DICOM PS3.3 section 10.7. Reference bands are not surgery targets.</p>'
    return head+'<body>'+PAGE.join((cover,advanced,audit))+'</body></html>'


def generate_report(image,points,provenance,notes=None,landmarks_reviewed=False,*,root=None):
    """Create a versioned private result. Never overwrite another review."""
    from ..eagle_eye_brain.organized_report import write_paged_pdf
    from .service import digest
    from PacsClient.utils.data_paths import AI_DIR
    import hashlib
    context=image['identity']
    if not context.get('study_uid') or not context.get('sop_uid'):
        raise ValueError('Verified study and image identity are required for a PDF report.')
    key=lambda value:hashlib.sha256(value.encode()).hexdigest()
    base=Path(root or AI_DIR/'eagle_eye'/'alignment')/'studies'/key(context['study_uid'])
    base.mkdir(parents=True,exist_ok=True)
    destination=base/uuid.uuid4().hex
    with tempfile.TemporaryDirectory(dir=base,prefix='.report-') as temporary:
        folder=Path(temporary)
        html=render_html(image,points,provenance,notes,landmarks_reviewed)
        write_paged_pdf(html,folder/'report.pdf',title='AI-PACS | Alignment View | Review required',
                        heading='AI-PACS  |  EAGLE EYE ALIGNMENT')
        (folder/'report.html').write_text(html,encoding='utf-8')
        payload=dict(format_version=4,identity=context,landmarks=points,provenance=provenance,
                     source_sha256=image['source_sha256'],spacing=image['spacing'],
                     calibrated=image['calibrated'],calibration_method=image['calibration_method'],
                     horizontal_flip=image.get('flipped',False),notes=notes or {},
                     measurements=measure_bilateral(points,image['spacing'],calibrated=image['calibrated']),
                     landmarks_reviewed=bool(landmarks_reviewed),clinical_report_signed=False,pdf_sha256=digest(folder/'report.pdf'))
        payload['reference_context']=reference_manifest(image)
        payload['derived_measurements']={side:{'jlo_deg':payload['measurements'][side]['mpta_deg']+
                                                       payload['measurements'][side]['mldfa_deg']} for side in ('R','L')}
        (folder/'report.json').write_text(json.dumps(payload,indent=2,allow_nan=False),encoding='utf-8')
        os.replace(folder,destination)
    return {'artifact_directory':str(destination),'pdf_available':True}
