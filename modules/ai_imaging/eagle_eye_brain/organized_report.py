"""Explicitly paginated brain report, with local DICOM identity and running furniture."""
from html import escape
import re

PAGE = "<!--EAGLE_BRAIN_PAGE-->"


def _cell(value, *, numeric=True):
    text = str(value)
    number = r'[+-]?(?:\d+(?:\.\d*)?|\.\d+)'
    is_number = re.fullmatch(rf'\s*[<>]?{number}(?:\s*[-–]\s*{number})?\s*%?\s*\*?\s*', text)
    align = 'center' if numeric and is_number else 'left'
    content = escape(text)
    if getattr(value, 'highlight', False):
        content = '<font color="#b91c1c"><b>' + content + '</b></font>'
    return f"<td align='{align}'>" + content + '</td>'


def _table(headers, rows, widths, *, numeric=True):
    head = "".join(f"<th align='center' width='{width}%'>{escape(str(name))}</th>" for name, width in zip(headers, widths))
    body = "".join("<tr>" + "".join(_cell(v, numeric=numeric and index > 0) for index, v in enumerate(row)) + "</tr>" for row in rows)
    return "<table width='100%' cellspacing='0' cellpadding='4'><thead><tr>" + head + "</tr></thead>" + body + "</table>"


def _num(value):
    return "Not available" if value is None else f"{value:.3f}"


def _lobar_summary(result):
    from .anatomical_groups import cortical_summaries
    from .volbrain_reference import range_text, highlight
    summaries = cortical_summaries(result["posterior_rows"])
    html = "<h1>Lobar and regional cortical summary</h1>"
    html += ("<p>Measured cortical gray matter only. Each row sums the native atlas parcels "
             "listed in the detailed regional pages. Cingulate and insular cortex are separate groups.</p>")
    html += _table(["Cortical group", "Right cm3", "Left cm3", "Total cm3", "% ICV", "Parcels R / L"],
                   [[r["structure"], _num(r["right_cm3"]), _num(r["left_cm3"]),
                     _num(r["total_cm3"]), _num(r["icv_percent"]),
                     r["right_coverage"] + " / " + r["left_coverage"]] for r in summaries],
                   [28, 14, 14, 14, 12, 18])
    html += ("<p class='note'>Coverage is measured/expected parcels per side. An incomplete group has no total. "
             "These are report-defined cortical sums, not complete lobe volumes. Paracentral cortex is "
             "grouped with frontal cortex; fusiform and parahippocampal cortex with temporal cortex. "
             "Do not add these sums to cortical parent volumes.</p>")
    html += ("<h2>Measurement coverage and interpretation</h2>"
             "<p><b>Lobar white matter: not separately measured.</b> Hemisphere white matter is not "
             "distributed among lobes. Full lobar parenchyma (gray + white matter) is not measured.</p>"
             "<p><b>Cortical thickness: not measured.</b> Cortical volume does not provide thickness in mm.</p>"
             "<p><b>No matched age/sex reference for these cortical group sums.</b> No lobar atrophy grade, "
             "Z-score or percentile is assigned. Available hemisphere white matter intervals remain "
             "cross-method comparisons. Regional appearance and boundaries require radiologist review.</p>")
    return html


def render_html(result):
    from .normative import active_report_context
    result = active_report_context(result)
    from .report import bilateral_rows, _medial_temporal_section
    context = result.get("patient_context", {})
    patient = context.get("patient_name", "").replace("^", " ") or "Not available"
    patient_id = context.get("patient_id") or "Not available"
    def field(key):
        return context.get(key) or "Not available"
    demographics = result.get("normative", {}).get("demographics", {})
    age = demographics.get("age_years")
    cover = "<h1>Brain volumetry report</h1><h2>Patient and examination</h2>"
    cover += _table(["Field", "DICOM / report value"], [
        ["Patient name", patient], ["Patient ID", patient_id],
        ["Birth date / study date (YYYYMMDD)", field("birth_date") + " / " + field("study_date")],
        ["Age at examination / sex", (f"{age:.2f} years" if age is not None else "Not available") + " / " + demographics.get("sex", "unknown")],
        ["Accession number", field("accession")], ["Imaging institution", field("institution")],
        ["Identity status", field("identity_status")]], [38, 62], numeric=False)
    cover += "<p><b>Report status: Review required.</b> Not signed for patient release. Clinical validation not established.</p>"
    values = {row["structure"]: row["volume_cm3"] for row in result["posterior_rows"]}
    icv = values.get("total intracranial")
    from .volbrain_reference import range_text, highlight
    published = result.get("normative", {}) if result.get("normative", {}).get("reference_id") == "volbrain" else {}
    range_heading = "Published 95% range cm3" if published else "Normal range cm3"
    paired_range_heading = "Published 95% R/L cm3" if published else "Normal range R/L cm3"
    overview = []
    for label, keys in [
        ("Intracranial volume", ["total intracranial"]),
        ("Cerebral white matter", ["left cerebral white matter", "right cerebral white matter"]),
        ("Cerebral cortical gray matter", ["left cerebral cortex", "right cerebral cortex"]),
        ("Cerebellar white matter", ["left cerebellum white matter", "right cerebellum white matter"]),
        ("Cerebellar cortex", ["left cerebellum cortex", "right cerebellum cortex"]),
        ("Brainstem", ["brain-stem"]), ("Model CSF label", ["csf"]),
        ("Third ventricle", ["3rd ventricle"]), ("Fourth ventricle", ["4th ventricle"])]:
        value = sum(values[k] for k in keys) if all(k in values for k in keys) else None
        overview.append([highlight(published,keys[0],label) if len(keys)==1 else label, highlight(published,keys[0],_num(value)) if len(keys)==1 else _num(value), range_text(published, keys[0]) if len(keys) == 1 else "Not available", _num(value / icv * 100 if value is not None and icv else None)])
    cover += "<h2>Global volumes and tissue compartments</h2>" + _table(["Structure", "Volume cm3", range_heading, "% ICV"], overview, [44, 18, 22, 16])
    cover += "<p class='note'>Red = >25% beyond nearest reference endpoint; not statistical significance. Published intervals use age, sex and local ICV; cross-method validation remains pending.</p>"
    cover += "<p class='note'>Selected compartments are not a complete additive brain partition. Model CSF is not total CSF. Do not sum cortical parent volumes with their parcels.</p>"
    pages = [cover]
    evidence = result.get("report_evidence_png")
    image = _image(evidence)
    pages.append("<h1>Segmentation and image review</h1>" + image +
                 "<p>Top: T1. Bottom: anatomical labels. Orthogonal LPS orientation. Colors do not indicate abnormality.</p>"
                 "<h2>Acquisition and review</h2><p>Primary input: 3D T1-weighted / MPRAGE. "
                 "Check coverage, motion, skull/dura inclusion and regional boundaries in the complete Slicer scene.</p>"
                 "<p>FLAIR: " + escape(result["flair_status"]) + ". Lesion volumetry is not implemented.</p>")
    pairs = bilateral_rows(result["posterior_rows"])
    from .anatomical_groups import CORTICAL_GROUPS, DEEP_GROUPS, TISSUE_GROUPS, group_pairs
    cortical_names = {name for _, names in CORTICAL_GROUPS for name in names}
    def paired_range(name):
        keys = ((f'ctx-rh-{name}', f'ctx-lh-{name}') if name in cortical_names else
                ('right '+name, 'left '+name))
        return 'R: '+range_text(published, keys[0])+'; L: '+range_text(published, keys[1])
    def region_table(title, subset):
        rows = [[r["structure"], _num(r["right_cm3"]), _num(r["left_cm3"]), paired_range(r['structure']) if published else "Not available",
                 *[_num(r[k]) for k in ("total_cm3", "icv_percent", "asymmetry_percent")]] for r in subset]
        for cells, r in zip(rows, subset):
            keys = ((f"ctx-rh-{r['structure']}", f"ctx-lh-{r['structure']}") if r['structure'] in cortical_names else
                    ('right '+r['structure'], 'left '+r['structure']))
            cells[1] = highlight(published, keys[0], cells[1])
            cells[2] = highlight(published, keys[1], cells[2])
            cells[0] = highlight(published, keys[0], highlight(published, keys[1], cells[0]))
        return "<h2>" + escape(title) + "</h2>" + (
            _table(["Structure", "Right cm3", "Left cm3", paired_range_heading, "Total cm3", "Total % ICV", "AI %"], rows, [26, 11, 11, 19, 11, 11, 11])
            if rows else "<p>No paired measurements available.</p>")
    note = ("<p class='note'>AI = 200 x (Right - Left) / (Right + Left). Positive means right is larger. "
            "No abnormality threshold is assigned. Published intervals are cross-method comparisons; unavailable entries have no mapped reference. "
            "Red = >25% beyond nearest interval endpoint, not statistical significance. "
            "* Cortical ranges are volBrain anatomical analogues, not matched normal limits; no atrophy flag is assigned. "
            "Atlas differs = split/merged territory with no direct interval. "
            "Groups organize native labels; no whole-lobe GM+WM volume is inferred.</p>")
    def paired_section(heading, definitions):
        return "<h1>" + heading + "</h1>" + "".join(
            region_table(title, subset) for title, subset in group_pairs(pairs, definitions)) + note

    pages.append(paired_section("Cerebral white matter", (
        ("Hemisphere white matter", ("cerebral white matter",)),)) +
        "<p>Lobar white matter is not separately measured.</p>")
    pages.append(_lobar_summary(result))
    pages.append(paired_section("Cerebral cortical gray matter", (
        ("Hemisphere cortical volumes", ("cerebral cortex",)),)))
    for title, names in CORTICAL_GROUPS:
        pages.append(paired_section("Cortical regions: " + title, ((title, names),)))
    csf = paired_section("CSF spaces and ventricles", (TISSUE_GROUPS[2],))
    csf += "<h2>Midline ventricles and model CSF</h2>" + _table(
        ["Structure", "Volume cm3", range_heading, "% ICV"],
        [[highlight(published, name, name), highlight(published, name, _num(values.get(name))),
          range_text(published, name), _num(values[name] / icv * 100 if name in values and icv else None)]
         for name in ("3rd ventricle", "4th ventricle", "csf")], [44, 18, 22, 16])
    pages.append(csf + "<p>Model CSF is not a measurement of total intracranial CSF.</p>")
    pages.append(paired_section("Basal ganglia", (DEEP_GROUPS[0],)))
    pages.append(paired_section("Other deep gray matter", (DEEP_GROUPS[1],)) +
                 "<p>Hippocampus and amygdala are grouped in the medial temporal section. "
                 "Ventral DC is a mixed diencephalic atlas territory.</p>")
    stem = values.get("brain-stem")
    pages.append("<h1>Brainstem</h1>" + _table(
        ["Structure", "Volume cm3", range_heading, "% ICV"],
        [[highlight(published, "brain-stem", "Brainstem"), highlight(published, "brain-stem", _num(stem)),
          range_text(published, "brain-stem"), _num(stem / icv * 100 if stem is not None and icv else None)]],
        [44, 18, 22, 16]) + "<p>Midline structure; no separate right/left or brainstem substructure measurements.</p>" + note)
    pages.append(paired_section("Cerebellum", (TISSUE_GROUPS[0],)))
    pages.append(paired_section("Medial temporal structures", (DEEP_GROUPS[2],)))
    assigned = {name for _, names in (*DEEP_GROUPS, *TISSUE_GROUPS, *CORTICAL_GROUPS) for name in names}
    remaining = [row for row in pairs if row["structure"] not in assigned]
    for offset in range(0, len(remaining), 17):
        pages.append("<h1>Other measured structures</h1>" + region_table("Atlas grouping not assigned", remaining[offset:offset + 17]) + note)
    medial = _medial_temporal_section(result).replace(" style='page-break-before:always'", "")
    image_heading = "<h3>Hippocampal coronal review</h3>"
    if image_heading in medial:
        measurements, image_review = medial.split(image_heading, 1)
        pages.extend([measurements, "<h1>Medial temporal image review</h1>" + image_heading + image_review])
    else:
        pages.append(medial)
    normative = result.get("normative", {})
    from .reference_report import pages as reference_pages
    pages.extend(reference_pages(normative))
    reference_summary = ("Percentiles and Z-scores are unavailable. T-scores, age curves and brain age are not calculated.")
    pages.append("<h1>Reference assessment and quality</h1><h2>Age and sex reference</h2><p>" +
                 escape(normative.get("reference_name", "No qualified reference model installed")) + "</p><ul>" +
                 "".join("<li>" + escape(reason) + "</li>" for reason in normative.get("reasons", [])) +
                 "</ul><p>" + reference_summary + "</p>"
                 "<h2>Model QC outputs</h2>" + _table(["QC measure", "Score"], [[name, f"{v:.4f}"] for name, v in result["qc_scores"].items()], [75, 25]) +
                 "<p>These scores do not automatically approve the segmentation.</p><h2>Measurement provenance</h2>"
                 "<p>Main tables use SynthSeg posterior volumes. Slicer binary-mask volumes are a separate estimator, "
                 "retained in the local analysis artifacts and excluded from these clinical summary tables.</p><p>Model revision: " +
                 escape(result["model_revision"]) + "</p><h2>Radiologist review</h2><p>Reviewer: ____________________</p>"
                 "<p>Signature / review date: ____________________</p><p>Review status remains pending until formally signed.</p>")
    head = ("<html><head><meta charset='utf-8'><meta name='brain-patient' content='" + escape(patient + " | ID: " + patient_id, quote=True) +
            "'><style>body{font-family:Arial;font-size:9pt;color:#203443}h1{font-size:17pt;color:#203e54}"
            "h2{font-size:12pt;color:#203e54}th{background-color:#dfeaf0}td{border-bottom:1px solid #d5dfe5}"
            ".note{font-size:8pt}</style></head><body>")
    return head + PAGE.join(pages) + "</body></html>"


def _image(data):
    import base64
    try:
        raw = base64.b64decode(data, validate=True)
    except (ValueError, TypeError):
        return "<p>Image evidence not available.</p>"
    if len(raw) > 8_000_000 or not raw.startswith(b"\x89PNG\r\n\x1a\n"):
        return "<p>Image evidence not available.</p>"
    return '<img width="620" src="data:image/png;base64,' + data + '"/>'


def write_paged_pdf(html, path, *, title="AI-PACS | Brain volumetry | Review required",
                    heading="AI-PACS  |  EAGLE EYE BRAIN"):
    from html.parser import HTMLParser
    from PySide6.QtCore import QRectF, QSizeF, Qt
    from PySide6.QtGui import QPdfWriter, QPageSize, QPainter, QTextDocument, QFont, QColor, QFontMetrics
    class HeaderParser(HTMLParser):
        patient = "Identity unavailable"
        def handle_starttag(self, tag, attrs):
            values = dict(attrs)
            if tag == "meta" and values.get("name") == "brain-patient":
                self.patient = values.get("content", self.patient)
    parser = HeaderParser(); parser.feed(html)
    head, body = html.split("<body>", 1)
    parts = body.removesuffix("</body></html>").split(PAGE)
    writer = QPdfWriter(str(path)); writer.setResolution(96); writer.setPageSize(QPageSize(QPageSize.A4))
    writer.setTitle(title)
    width, height = writer.width(), writer.height()
    documents = []
    for section_index, part in enumerate(parts, 1):
        doc = QTextDocument(); doc.setDefaultFont(QFont("Arial", 9))
        doc.setTextWidth(width - 24); doc.setHtml(head + "<body>" + part + "</body></html>")
        if doc.size().height() > height - 130:
            raise ValueError(f"Report section {section_index} exceeds its printable page; reduce content or split section.")
        documents.append(doc)
    painter = QPainter(writer)
    try:
        for index, doc in enumerate(documents):
            if index:
                writer.newPage()
            painter.setPen(QColor("#203e54")); painter.setFont(QFont("Arial", 13, QFont.Weight.Bold))
            painter.drawText(12, 24, heading)
            painter.setFont(QFont("Arial", 8))
            text = QFontMetrics(painter.font()).elidedText(parser.patient, Qt.TextElideMode.ElideRight, width - 24)
            painter.drawText(12, 43, text); painter.drawLine(12, 52, width - 12, 52)
            painter.save(); painter.translate(12, 64); doc.drawContents(painter, QRectF(0, 0, width - 24, height - 130)); painter.restore()
            painter.drawLine(12, height - 42, width - 12, height - 42)
            painter.drawText(12, height - 22, "AI-PACS | Review required - not signed for patient release")
            painter.drawText(QRectF(width - 115, height - 36, 100, 25), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                             f"Page {index + 1} of {len(documents)}")
    finally:
        painter.end()
