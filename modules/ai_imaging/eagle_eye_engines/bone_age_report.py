"""Deterministic, study-bound Bone Age reporting; no model execution here.

Call file-writing methods from a worker, with a QApplication already present.
"""
from datetime import date
from html import escape
from pathlib import Path
import base64
import json
import math
import uuid

from .bone_age_reference import calculate, MALE, FEMALE, REFERENCE_ID, REFERENCE_NAME
from ..eagle_eye_remote.demographics import normalize, validate_review


def assessment(result, study_uid, patient_id, *, preview=False):
    original = result.get('confirmed_demographics') or {}
    if not preview and original.get('physician_confirmed') is not True:
        raise ValueError('Confirm patient information before preparing the PDF.')
    demographics = validate_review(original,study_uid,patient_id)
    demographics['physician_confirmed'] = original.get('physician_confirmed') is True
    if result.get('study_id',study_uid) != study_uid or result.get('patient_id',patient_id) != patient_id:
        raise ValueError('The stored result belongs to another patient or study.')
    if normalize(result.get('sex')) != demographics['sex']:
        raise ValueError('Confirmed sex differs from model input. Repeat Bone Age analysis before reporting.')
    bone = result.get('predicted_bone_age_months',result.get('bone_age_months'))
    if isinstance(bone,bool) or not isinstance(bone,(float,int)) or not math.isfinite(bone) or not 0 <= bone <= 228:
        raise ValueError('A finite model age from 0 to 228 months is required.')
    age = demographics['chronological_age_months']
    precision = 'Physician-entered completed years and months'
    if demographics.get('age_source') == 'birth_date' and demographics.get('birth_date') and demographics.get('study_date'):
        try:
            birth, exam = date.fromisoformat(demographics['birth_date']),date.fromisoformat(demographics['study_date'])
        except ValueError as exc:
            raise ValueError('Invalid confirmed birth or imaging date.') from exc
        completed=(exam.year-birth.year)*12+exam.month-birth.month-(exam.day<birth.day)
        if birth > exam or completed != age:
            raise ValueError('Confirmed age and dates disagree. Review patient information again.')
        age=(exam-birth).days/365.2425*12
        precision='Exact date interval / 365.2425 x 12 months'
    if not 0 <= age <= 240:
        raise ValueError('Chronological age outside the supported pediatric range.')
    try:
        reference=calculate(age,bone,demographics['sex'])
    except ValueError:
        reference=dict(available=False,reference_id=REFERENCE_ID,reference_name=REFERENCE_NAME,
                       reason='Chronological age outside reference range; no extrapolation.')
    return dict(schema='bone_age_report_v1',study_uid=study_uid,patient_id=patient_id,
        demographics=demographics,demographics_confirmed=original.get('physician_confirmed') is True,
        chronological_age_months=age,age_precision=precision,bone_age_months=float(bone),
        difference_months=bone-age,reference=reference,
        method=result.get('model_used') or 'AI-PACS Bone Age AI (recorded result)',
        engine_revision=result.get('engine_revision') or 'Not recorded in this result',
        checkpoint_sha256=result.get('checkpoint_sha256') or 'Not recorded in this result',
        server_job_id=result.get('server_job_id') or 'Not recorded in this result',
        image_count=result.get('image_count'),
        warnings=list(result.get('reliability_warnings') or []),unsigned=True)


def _table(rows):
    return '<table width="100%" cellspacing="0" cellpadding="5">'+''.join(
        '<tr><td width="42%" bgcolor="#eef3f7"><b>'+escape(str(k))+
        '</b></td><td>'+escape(str(v))+'</td></tr>' for k,v in rows)+'</table>'


def _png(image):
    from PySide6.QtCore import QByteArray, QBuffer, QIODevice
    data=QByteArray(); buffer=QBuffer(data); buffer.open(QIODevice.WriteOnly)
    if not image.save(buffer,'PNG'):
        raise RuntimeError('Report image encoding failed.')
    return base64.b64encode(bytes(data)).decode('ascii')


def reference_chart(report):
    """The equality line is distinct from the historical population mean."""
    from PySide6.QtCore import QPointF, QRectF, Qt
    from PySide6.QtGui import QImage, QPainter, QPolygonF, QColor, QPen, QFont, QGuiApplication, QFontDatabase
    if QGuiApplication.instance() is None:
        raise RuntimeError('Report rendering requires an initialized Qt application.')
    # A chart is rasterized before the PDF writer runs. Windows offscreen Qt
    # therefore needs font registration here, rather than only in the writer.
    if not QFontDatabase.families():
        import os
        fonts=Path(os.environ.get('WINDIR','C:/Windows'))/'Fonts'
        for name in ('arial.ttf','arialbd.ttf'):
            if (fonts/name).is_file():
                QFontDatabase.addApplicationFont(str(fonts/name))
        if not QFontDatabase.families():
            raise RuntimeError('Report fonts are unavailable.')
    image=QImage(1100,670,QImage.Format_RGB32); image.fill(QColor('white'))
    painter=QPainter(image); painter.setRenderHint(QPainter.Antialiasing)
    try:
        rows=MALE if report['demographics']['sex']=='M' else FEMALE
        age,bone=report['chronological_age_months'],report['bone_age_months']
        xmax=max(216,age+12); ymax=max(240,bone+12)
        def point(x,y): return QPointF(90+940*x/xmax,555-475*y/ymax)
        painter.setPen(QColor('#173d56')); painter.setFont(QFont('Arial',17))
        painter.drawText(QRectF(90,5,940,35),'Bone Age against Chronological Age')
        for n,color in ((2,'#edf2fa'),(1,'#cbdcf0')):
            polygon=QPolygonF([point(a,m+n*s) for a,m,s in rows]+
                             [point(a,m-n*s) for a,m,s in reversed(rows)])
            painter.setPen(Qt.NoPen); painter.setBrush(QColor(color)); painter.drawPolygon(polygon)
        painter.setBrush(Qt.NoBrush); painter.setFont(QFont('Arial',12))
        for years in range(0,int(xmax/12)+1,2):
            x=point(years*12,0).x()
            painter.setPen(QPen(QColor('#e2e8f0'),1)); painter.drawLine(QPointF(x,80),QPointF(x,555))
            painter.setPen(QColor('#475569')); painter.drawText(QRectF(x-15,560,35,22),Qt.AlignCenter,str(years))
        for years in range(0,int(ymax/12)+1,2):
            y=point(0,years*12).y()
            painter.setPen(QPen(QColor('#e2e8f0'),1)); painter.drawLine(QPointF(90,y),QPointF(1030,y))
            painter.setPen(QColor('#475569')); painter.drawText(QRectF(45,y-11,35,22),Qt.AlignRight,str(years))
        painter.setPen(QPen(QColor('#64748b'),2,Qt.DashLine)); painter.drawLine(point(0,0),point(min(xmax,ymax),min(xmax,ymax)))
        painter.setPen(QPen(QColor('#2563eb'),3)); painter.drawPolyline(QPolygonF([point(a,m) for a,m,s in rows]))
        painter.setPen(QPen(QColor('#64748b'),2)); painter.drawLine(point(0,0),point(xmax,0)); painter.drawLine(point(0,0),point(0,ymax))
        painter.setPen(QColor('#475569')); painter.drawText(QRectF(340,590,500,25),Qt.AlignCenter,'Chronological age (years)')
        painter.save(); painter.translate(20,440); painter.rotate(-90); painter.drawText(0,0,'Bone age (years)'); painter.restore()
        painter.setPen(Qt.NoPen); painter.setBrush(QColor('#dc6b30')); painter.drawEllipse(point(age,bone),8,8)
        painter.setPen(QColor('#475569')); painter.drawText(QRectF(90,630,940,28),Qt.AlignCenter,
            'Blue: reference mean | dark/light band: +/-1 / +/-2 SD | dashed: BA = CA | orange: recorded AI estimate')
    finally:
        painter.end()
    return image


def render_html(report, *, evidence_png=None):
    from ..eagle_eye_brain.organized_report import PAGE
    d=report['demographics']; r=report['reference']; age=report['chronological_age_months']; bone=report['bone_age_months']
    pending=not report['demographics_confirmed']
    state='DRAFT - PATIENT INFORMATION NOT CONFIRMED' if pending else 'Unsigned - physician interpretation and signature required'
    head='<html><head><meta name="brain-patient" content="'+escape('Patient code '+report['patient_id']+' | '+state,quote=True)+'"/>'
    head+='<style>body{font-family:Arial;color:#243746;font-size:10pt}h1{font-size:20pt;color:#173d56}h2{font-size:13pt;color:#173d56}td{vertical-align:top}p{line-height:1.25}</style></head><body>'
    first='<h1>Bone Age Assessment</h1><p><b>'+escape(state)+'</b></p>'+_table([
        ('Patient code / name',report['patient_id']+' / '+d['name']),
        ('Sex used in analysis','Male' if d['sex']=='M' else 'Female'),
        ('Birth date / imaging date',(d.get('birth_date') or 'Not available')+' / '+(d.get('study_date') or 'Not available')),
        ('Chronological age at imaging',f"{d['chronological_age_months']//12} years {d['chronological_age_months']%12} months ({age:.1f} months)"),
        ('Estimated bone age',f'{bone/12:.2f} years ({bone:.1f} months)'),
        ('Bone minus chronological age',f'{bone-age:+.1f} months')])
    rows=[('Reference',REFERENCE_NAME)]
    if r['available']:
        low,high=r['reference_range_2sd_months']; p=r['estimated_reference_percentile']
        percentile='<0.1' if p<.1 else '>99.9' if p>99.9 else f'{p:.1f}'
        rows += [('Reference mean / SD',f"{r['reference_mean_months']:.1f} / {r['reference_sd_months']:.2f} months"),
                 ('Expected range (+/-2 SD)',f'{low:.1f} to {high:.1f} months'),
                 ('Z-score',f"{r['z_score']:+.2f}"),('Estimated reference percentile',percentile),
                 ('Reference comparison',r['category']+(' (conditional draft)' if pending else ''))]
    else:
        rows += [('Reference comparison','Unavailable'),('Z-score / percentile',r['reason'])]
    first+='<h2>Age- and sex-matched reference</h2>'+_table(rows)
    first+='<h2>Interpretation</h2><p>'+escape(('Conditional calculation only. ' if pending else '')+
        (r['category']+'. This compares the recorded AI estimate with the historical reference; clinical interpretation requires image review.'
         if r['available'] else 'The age estimate is reported without a reference category or percentile.'))+'</p>'
    first+='<p>The +/-2 SD band describes population variation; it is not a model confidence interval. The percentile assumes a normal distribution and is not a height percentile.</p>'
    second='<h1>Reference Chart and Method</h1><p><img width="600" height="365" src="data:image/png;base64,'+_png(reference_chart(report))+'"/></p>'
    second+='<p>Historical Brush/Greulich-Pyle population. Not validated as a contemporary Iranian population reference. Mean and SD are linearly interpolated between tabulated ages; no extrapolation. Bands near skeletal maturity require particular care.</p>'
    second+='<h2>Method and traceability</h2>'+_table([
        ('Analysis method',report['method']),('Engine revision',report['engine_revision']),
        ('Checkpoint SHA256',report['checkpoint_sha256']),('Age calculation',report['age_precision']),
        ('Demographic sources',', '.join(f'{k}: {v}' for k,v in d.get('sources',{}).items()) or 'Physician review'),
        ('Reference version',REFERENCE_ID)])
    if report['warnings']:
        second+='<p><b>Acquisition / analysis review:</b> '+escape('; '.join(report['warnings']))+'</p>'
    second+='<h2>References</h2><p>Greulich WW, Pyle SI. Radiographic Atlas of Skeletal Development of the Hand and Wrist. 2nd ed. 1959.<br/>Gaskin CM et al. Skeletal Development of the Hand and Wrist. Oxford University Press, 2011; Tables 1-2, pp. 8-9.<br/>Bunch PM et al. Skeletal Radiology 2017;46:785-793. doi:10.1007/s00256-017-2616-7.</p>'
    evidence=''
    if evidence_png:
        from PySide6.QtGui import QImage
        image=QImage.fromData(evidence_png)
        if image.isNull():
            raise ValueError('Invalid report evidence image.')
        scale=min(440/image.width(),580/image.height())
        evidence=PAGE+'<h1>Source Image for Review</h1><p><img width="'+str(int(image.width()*scale))+'" height="'+str(int(image.height()*scale))+'" src="data:image/png;base64,'+base64.b64encode(evidence_png).decode('ascii')+'"/></p><p>Local original radiograph shown for physician review. Review full-resolution source images for acquisition coverage and skeletal maturity.</p>'
    return head+first+PAGE+second+evidence+'</body></html>'


def create_report(result, study_uid, patient_id, output, *, preview=False, evidence_png=None):
    from ..eagle_eye_brain.organized_report import write_paged_pdf
    report=assessment(result,study_uid,patient_id,preview=preview)
    output=Path(output); output.mkdir(parents=True,exist_ok=True)
    path=output/'bone_age_report.pdf'
    partial=output/('bone-age-'+uuid.uuid4().hex+'.partial')
    try:
        html=render_html(report,evidence_png=evidence_png)
        write_paged_pdf(html,partial,title='AI-PACS | Bone Age | Unsigned',heading='AI-PACS  |  EAGLE EYE BONE AGE')
        if not partial.is_file() or partial.stat().st_size < 1000:
            raise RuntimeError('Bone Age PDF publication failed.')
        partial.replace(path)
    finally:
        partial.unlink(missing_ok=True)
    record=output/'bone_age_report.json'
    temp=record.with_suffix('.partial')
    try:
        temp.write_text(json.dumps(report,allow_nan=False,ensure_ascii=False,indent=2),encoding='utf-8')
        temp.replace(record)
    finally:
        temp.unlink(missing_ok=True)
    return dict(pdf_path=str(path),report_json_path=str(record),reference=report['reference'])
