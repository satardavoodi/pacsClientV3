"""Read-only reception report sources for a study's correction selector."""
import json
from html.parser import HTMLParser


class _Text(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style'):
            self.hidden += 1
        if tag in ('p', 'div', 'br', 'tr', 'li', 'h1', 'h2', 'h3'):
            self.parts.append('\n')
        elif tag in ('td', 'th'):
            self.parts.append(' | ')

    def handle_endtag(self, tag):
        if tag in ('script', 'style'):
            self.hidden = max(0, self.hidden - 1)
        if tag in ('p', 'div', 'tr', 'li', 'h1', 'h2', 'h3'):
            self.parts.append('\n')

    def handle_data(self, value):
        if not self.hidden:
            self.parts.append(value)


def report_items(study_uid, patient_id, fetch):
    """Never issue an unfiltered query or infer identity from a person's name."""
    if not study_uid:
        return []
    rows = list(fetch(study_uid=study_uid, limit=100))
    if patient_id:
        rows += list(fetch(patient_id=patient_id, limit=100))
    seen, items = set(), []
    for row in rows:
        uid = row.get('study_uid')
        if uid and uid != study_uid:
            continue
        if not uid and (not patient_id or str(row.get('patient_id')) != str(patient_id)):
            continue
        source = row.get('html_content')
        if not isinstance(source, str) or not source.strip() or len(source) > 200000:
            continue
        parser = _Text()
        parser.feed(source)
        plain = '\n'.join(line.strip() for line in ''.join(parser.parts).splitlines() if line.strip())
        if not plain or plain in seen:
            continue
        seen.add(plain)
        # A stable report object preserves the existing Correction renderer's contract.
        from .correction_source import pack
        raw = pack('reception-report.html', source.encode('utf-8'))
        items.append((raw, 'Reception report ' + str(row.get('id', ''))))
    return items


def load_for_study(study_uid):
    """Called from a worker, using the same repository as Reception View Reports."""
    if not study_uid:
        return []
    from PacsClient.utils import db_manager as db
    from PacsClient.utils.database import ai_get_reception_reports
    study = db.get_study_by_study_uid(study_uid) or {}
    patient = db.get_patient_by_patient_pk(study['patient_fk']) if study.get('patient_fk') else {}
    return report_items(study_uid, (patient or {}).get('patient_id'), ai_get_reception_reports)
