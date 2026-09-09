"""Local review report. No diagnostic or normative claims are inferred."""
from html import escape


def bilateral_rows(rows):
    """Pair exact atlas labels; never guess equivalence across atlases."""
    import math
    values = {row["structure"]: row["volume_cm3"] for row in rows}
    icv = values.get("total intracranial")
    pairs = []
    for left in sorted(values):
        if left.startswith("left "):
            name, right = left[5:], "right " + left[5:]
        elif left.startswith("ctx-lh-"):
            name, right = left[7:], "ctx-rh-" + left[7:]
        else:
            continue
        if right not in values:
            continue
        lval, rval = values[left], values[right]
        if any(not math.isfinite(v) or v < 0 for v in (lval, rval)):
            from .contracts import BrainError
            raise BrainError("Invalid bilateral measurement.")
        total = lval + rval
        pairs.append({"structure": name, "left_cm3": lval, "right_cm3": rval,
                      "total_cm3": total,
                      "icv_percent": 100 * total / icv if icv and icv > 0 else None,
                      "asymmetry_percent": 200 * (rval - lval) / total if total else None})
    return pairs


def _review_sections(result):
    from .organized_report import _cell
    from .normative import reference_assessment
    assessment = result.get("normative") or reference_assessment()
    demographics = assessment["demographics"]
    age = demographics["age_years"]
    context = (f"Age at examination: {age:g} years" if age is not None else "Age at examination: not supplied")
    context += "; sex: " + escape(demographics["sex"])
    sections = ["<p>" + context + ". Entered demographics require examination verification.</p>",
                "<h2>Age and sex reference assessment</h2><p><b>" + escape(assessment["reference_name"])
                + "</b></p><ul>" + "".join("<li>" + escape(s) + "</li>" for s in assessment["reasons"]) + "</ul>",
                "<p>Percentile, Z-score, T-score and age curves: unavailable. "
                "Brain age requires a separate trained model. No abnormality colors are assigned.</p>"]
    if assessment["source"]:
        sections.append('<p>Reference: <a href="' + escape(assessment["source"], quote=True)
                        + '">' + escape(assessment["reference_name"]) + '</a></p>')
    evidence = result.get("report_evidence_png")
    if evidence:
        # Only a locally generated PNG data URI can be embedded. Never fetch remote images.
        import base64
        try:
            raw = base64.b64decode(evidence, validate=True)
            valid = raw.startswith(b"\x89PNG\r\n\x1a\n") and len(raw) <= 8_000_000
        except (ValueError, TypeError):
            valid = False
        if valid:
            sections.append('<h2>Segmentation evidence</h2><img width="620" src="data:image/png;base64,'
                            + evidence + '"/><p>Representative slices in LPS physical orientation. '
                            'Colors identify labels, not abnormality or brain age. Review the full Slicer scene.</p>')
    pairs = bilateral_rows(result["posterior_rows"])
    if pairs:
        def number(value):
            return "Unavailable" if value is None else f"{value:.3f}"
        body = "".join("<tr>" + _cell(row["structure"], numeric=False) + "".join(
            _cell(number(row[key])) for key in
            ("total_cm3", "right_cm3", "left_cm3", "icv_percent", "asymmetry_percent")) + "</tr>" for row in pairs)
        sections.append("<h2>Bilateral structure volumes</h2><p>AI = 200 x (Right - Left) / (Right + Left). "
                        "Positive means right is larger. No normal / abnormal threshold is assigned.</p>"
                        "<table width='100%' border='1' cellpadding='4' cellspacing='0'><thead><tr>"
                        "<th align='center' width='35%'>Structure</th><th align='center' width='13%'>Total cm3</th><th align='center' width='13%'>Right cm3</th>"
                        "<th align='center' width='13%'>Left cm3</th><th align='center' width='13%'>Total % ICV</th><th align='center' width='13%'>AI %</th>"
                        "</tr></thead>" + body + "</table>")
    return "".join(sections)


def _medial_temporal_section(result):
    if not any(row["structure"] == "total intracranial" for row in result["posterior_rows"]):
        return ""
    import base64
    from .medial_temporal import section_html
    image_html = ""
    data = result.get("medial_temporal_evidence_png")
    if isinstance(data, str):
        try:
            raw = base64.b64decode(data, validate=True)
        except ValueError:
            raw = b""
        if raw.startswith(b"\x89PNG\r\n\x1a\n") and len(raw) <= 8_000_000:
            image_html = ('<h3>Hippocampal coronal review</h3><img width="620" src="data:image/png;base64,'
                          + data + '"/><p>Top: T1. Bottom: hippocampal labels only. Three coronal levels '
                          'selected from segmentation extent. These are orthogonal LPS views, not dedicated '
                          'hippocampal-axis oblique MTA reformats. Display crops enlarge the hippocampal region; '
                          'measurement masks are unchanged. Full-volume review is required.</p>')
    if not image_html:
        image_html = "<p>Dedicated hippocampal image evidence: not available in this report.</p>"
    return section_html(result, image_html)


def report_html(result):
    from .normative import active_report_context
    result = active_report_context(result)
    from .organized_report import _cell
    if result.get("model") == "SynthSeg 2.0" and any(r["structure"] == "total intracranial" for r in result["posterior_rows"]):
        from .organized_report import render_html
        return render_html(result)
    def table(rows):
        body = "".join("<tr>" + _cell(row["structure"], numeric=False)
                       + _cell(f'{row["volume_mm3"]:.3f}') + _cell(f'{row["volume_cm3"]:.3f}')
                       + (_cell(f'{row["icv_percent"]:.3f}') if "icv_percent" in row else _cell("Unavailable"))
                       + "</tr>" for row in rows)
        return ("<table width='100%' border='1' cellpadding='5' cellspacing='0'><thead><tr>"
                "<th align='center' width='55%'>Structure</th><th align='center' width='17%'>mm3</th>"
                "<th align='center' width='14%'>cm3</th><th align='center' width='14%'>% ICV</th></tr></thead>"
                + body + "</table>")
    return ("<!doctype html><html><head><meta charset='utf-8'><title>Eagle Eye Brain</title></head><body>"
            "<h1 style='color:#203e54'>AI-PACS | Eagle Eye Brain volumetry</h1><p><b>Research / review required. Clinical validation not established.</b></p>"
            "<p>No qualified normative reference is installed. Percentiles and Z-scores are unavailable. "
            "Review anatomy, coverage and segmentation overlays before interpreting measurements.</p>"
            + _review_sections(result) +
            _medial_temporal_section(result) +
            "<p>FLAIR: " + escape(result["flair_status"]) + ". White matter lesion segmentation is not implemented.</p>"
            "<h2>SynthSeg posterior volumes</h2><p>Probability-based estimates. "
            "Do not sum overlapping parent structures and cortical parcels.</p>" + table(result["posterior_rows"])
            + "<h2>Slicer binary-mask volumes</h2><p>Measured from the final labelmap; "
            "these are a different estimator from posterior volumes.</p>" + table(result["binary_rows"])
            + "<h2>Model quality scores</h2><p>Scores are retained for review; they do not automatically approve the result.</p><ul>"
            + "".join(f"<li>{escape(name)}: {value:.4f}</li>" for name, value in result["qc_scores"].items())
            + "</ul><p>Model revision: " + escape(result["model_revision"]) + "</p></body></html>")


def write_pdf(html, path):
    """Run in the report worker while the workstation QApplication exists."""
    from .organized_report import PAGE, write_paged_pdf
    if PAGE in html:
        return write_paged_pdf(html, path)
    from PySide6.QtGui import QTextDocument, QPdfWriter, QPageSize, QFont
    from PySide6.QtCore import QSizeF
    writer = QPdfWriter(str(path))
    writer.setPageSize(QPageSize(QPageSize.A4))
    writer.setResolution(96)
    writer.setTitle("Eagle Eye Brain - review required")
    document = QTextDocument()
    document.setDefaultFont(QFont("Arial", 9))
    document.setPageSize(QSizeF(writer.pageLayout().paintRectPixels(writer.resolution()).size()))
    document.setHtml(html)
    document.print_(writer)
