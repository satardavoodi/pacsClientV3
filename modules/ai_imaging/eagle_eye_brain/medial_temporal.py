"""Medial temporal review evidence; no automatic Alzheimer's diagnosis or MTA score."""
from html import escape
import math

REGIONS = (
    ("Hippocampus", "left hippocampus", "right hippocampus"),
    ("Entorhinal cortex", "ctx-lh-entorhinal", "ctx-rh-entorhinal"),
    ("Parahippocampal cortex", "ctx-lh-parahippocampal", "ctx-rh-parahippocampal"),
    ("Amygdala", "left amygdala", "right amygdala"),
    ("Inferior lateral ventricle", "left inferior lateral ventricle", "right inferior lateral ventricle"),
)


def focus_rows(result):
    values = {row["structure"]: row["volume_cm3"] for row in result["posterior_rows"]}
    icv = values.get("total intracranial")
    def valid(value):
        return isinstance(value, (int, float)) and math.isfinite(value) and value >= 0
    rows = []
    for name, left, right in REGIONS:
        lval, rval = values.get(left), values.get(right)
        lval = lval if valid(lval) else None
        rval = rval if valid(rval) else None
        total = lval + rval if lval is not None and rval is not None else None
        rows.append({"structure": name, "left_cm3": lval, "right_cm3": rval,
                     "left_icv_percent": 100 * lval / icv if lval is not None and valid(icv) and icv > 0 else None,
                     "right_icv_percent": 100 * rval / icv if rval is not None and valid(icv) and icv > 0 else None,
                     "asymmetry_percent": 200 * (rval - lval) / total if total else None})
    return rows


def section_html(result, image_html=""):
    from .organized_report import _cell
    from .volbrain_reference import range_text, highlight
    reference = result.get('normative', {})
    published = reference.get('reference_id') == 'volbrain'
    labels = {name: (left, right) for name, left, right in REGIONS}
    def interval(name):
        left, right = labels[name]
        return ('R: ' + range_text(reference, right) + '; L: ' + range_text(reference, left)) if published else 'Not available'
    def number(value):
        return "Not available" if value is None else f"{value:.3f}"
    body = "".join("<tr>" + _cell(row["structure"], numeric=False) + "".join(
        _cell(highlight(reference, labels[row['structure']][1 if key.startswith('right') else 0], number(row[key])) if key in ('right_cm3','left_cm3') else number(row[key])) for key in
        ("right_cm3", "left_cm3", "right_icv_percent", "left_icv_percent", "asymmetry_percent"))
        + _cell(interval(row['structure'])) + "</tr>" for row in focus_rows(result))
    return ("<h2 style='page-break-before:always'>Medial temporal assessment / Alzheimer's-related imaging review</h2>"
            "<p>This section supports evaluation of a cognitive presentation; it does not establish Alzheimer's disease. "
            "MRI atrophy is not disease-specific. Interpret with age, symptoms, cognitive testing and appropriate biomarkers.</p>"
            "<table width='100%' border='1' cellpadding='4' cellspacing='0'><thead><tr>"
            "<th align='center' width='26%'>Structure</th><th align='center' width='11%'>Right cm3</th><th align='center' width='11%'>Left cm3</th>"
            "<th align='center' width='11%'>Right % ICV</th><th align='center' width='11%'>Left % ICV</th><th align='center' width='11%'>AI %</th>"
            "<th align='center' width='19%'>" + ("Published 95% R/L cm3" if published else "Normal range R/L cm3") + "</th>"
            "</tr></thead>" + body + "</table>"
            "<p>AI = 200 x (Right - Left) / (Right + Left). Missing structures are not zero. "
            + ("Published intervals use local ICV; cross-method validation is pending. "
               "Red = >25% beyond nearest reference endpoint, not statistical significance. "
               "* Cortical ranges are anatomical analogues, not matched normal limits or atrophy thresholds. " if published else
               "Normal ranges for either side are unavailable: no validated reference for these SynthSeg measurements. ") +
            "Inferior lateral ventricle volume is a contextual model label, not a measured temporal-horn width.</p>"
            + image_html +
            "<p><b>Visual MTA score:</b> Right: not rated; Left: not rated. Review hippocampal height, "
            "choroid fissure and temporal horn on appropriately oriented coronal images. "
            "An MTA score is not derived from these volume numbers.</p>"
            "<p><b>Review priorities:</b> verify bilateral segmentation, hippocampal shape and regional versus generalized "
            "atrophy. Review posterior cortical patterns and FLAIR vascular burden in the full examination. "
            "No automated posterior-atrophy, Fazekas or Alzheimer's probability score is produced.</p>"
            "<p><b>Normative interpretation:</b> age/sex-adjusted regional centiles remain unavailable. "
            "Small cortical parcels require individual boundary review; reconstruction agreement does not prove accuracy.</p>"
            "<p>Methods: <a href='https://radiologyassistant.nl/neuroradiology/dementia/update'>MRI dementia / MTA review</a>; "
            "<a href='https://doi.org/10.1002/alz.13859'>Alzheimer's Association revised criteria (2024)</a>.</p>")
