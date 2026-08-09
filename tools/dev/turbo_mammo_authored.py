# -*- coding: utf-8 -*-
"""Mammography reporting context — a PREFIX, never a replacement.

⚠️ CLINICAL REVIEW REQUIRED. Compiled 2026-08-09. Not read by a radiologist.

WHY MAMMOGRAPHY IS THE ONE MODALITY THE TEMPLATE DOES NOT RENDER
Its shared prompt opens with `SECTION 0 — REGEX-LOCKED JSON SCHEMA (HARD ENFORCEMENT)`
and a full structure lock. The output is not the five keys every other modality returns:
it is `Report Title`, `Breast Composition`, `Pathological Findings`,
`Normal Findings {Right Breast, Left Breast}`, `Axillary Evaluation`, and
`BI-RADS Category {Right Breast, Left Breast}` — with **no Impression and no
Recommendations keys at all**. The template's OUTPUT slot would emit the wrong shape and
the regex would reject it.

So the gate contributes a PREFIX and the shared prompt follows it unchanged. Everything
SECTION 0 through SECTION 9 says still applies, and the contract is nearer the end of
the message, which is where a machine-readable contract belongs. This is the same
decision made for the Turbo correction frame, for the same reason.

A CONSEQUENCE WORTH STATING. Because the shared prompt is preserved in full, mammography
gets no token reduction — the prefix makes the prompt slightly LONGER. The gain here is
relevance and coverage, not size. Every other modality bought both; this one buys one.

SOURCES: ACR BI-RADS Atlas 5th edition, mammography section (UNC-hosted reference card,
https://msrads.web.unc.edu/wp-content/uploads/sites/15695/2018/04/BIRADS-Reference-Card_web_F.pdf);
assessment categories cross-checked at PMC8211559; ACR practice parameters; the
project's own SECTION 3 lexicon and SECTION 4 normal template, which the prefix
deliberately does not duplicate.

NOT COVERED: breast MRI (that is the MRI library's `breast` module) and breast
ultrasound (the ultrasound library's `breast` module). This file is the mammogram.
"""
from __future__ import annotations

from typing import Dict, List

MAMMO_HEADINGS = ("Breast composition · Masses · Calcifications · Asymmetries · "
                  "Architectural distortion · Associated features · Skin and nipple · "
                  "Axilla · Comparison")

MAMMO_TECHNIQUE: List[str] = [
    "Preserve the views obtained for each breast — CC and MLO are the standard pair, "
    "and any spot compression, magnification, true lateral, exaggerated CC or Eklund "
    "view was taken to answer a specific question. Preserve which, and why if he said.",
    "Preserve whether the study was a screening or a diagnostic examination. They have "
    "different assessment vocabularies: an incomplete assessment belongs to screening, "
    "and a diagnostic study is expected to conclude.",
    "Preserve whether tomosynthesis was performed and whether the synthesised 2D image "
    "replaced the standard 2D acquisition.",
    "Preserve any statement about positioning, motion, or tissue excluded from the "
    "field. Posterior tissue not included on a view is a reported limitation, not a "
    "normal finding.",
    "Preserve implant status and whether implant-displaced views were obtained. Without "
    "them, the anterior tissue assessment is limited and that caveat must survive.",
]

MAMMO_PATHOLOGY: List[str] = [
    "Preserve the side, the quadrant or clock position, the depth (anterior, middle or "
    "posterior third) and the distance from the nipple for every finding. A mammographic "
    "finding without its location cannot be localised for biopsy.",
    "Preserve the breast composition category exactly as he assigned it (a, b, c or d). "
    "It is a statement about masking risk, not a diagnosis, and it is his to make.",
    "Mass — preserve shape, margin and density as three separate observations, in the "
    "words he used. Circumscribed and obscured are different margins with different "
    "consequences, and 'not circumscribed' is not a synonym for 'spiculated'.",
    "Calcifications — preserve the morphology and the distribution as two separate "
    "descriptors. Typically-benign and suspicious morphologies are distinct vocabularies "
    "in the lexicon; never substitute a term from one for a term in the other.",
    "Asymmetry — preserve which kind he named: asymmetry, global asymmetry, focal "
    "asymmetry or developing asymmetry. They carry different levels of concern and are "
    "not interchangeable words for the same thing.",
    "Preserve architectural distortion as its own finding, and never fold it into a mass.",
    "Preserve associated features by name — skin retraction or thickening, nipple "
    "retraction, trabecular thickening, axillary adenopathy, architectural distortion — "
    "each with its side.",
    "Preserve the BI-RADS category exactly as he assigned it, per breast, including any "
    "4A, 4B or 4C subdivision. Never assign, upgrade, downgrade or collapse a category, "
    "and never derive one from the descriptors: the category is a management decision.",
    "Preserve any comparison with a prior study, the date of that prior, and any change "
    "he described. On a mammogram, stability over time and interval change are findings "
    "in their own right.",
    "Preserve markers, clips, surgical scars and any post-treatment change with their "
    "locations, and keep them separate from new findings.",
]

MAMMO_NOTES: List[str] = [
    "Every finding carries a side. A mammogram report without laterality is not usable.",
    "This report has no Impression and no Recommendations key. A dictated impression or "
    "recommendation is preserved inside Pathological Findings — it is never dropped, and "
    "never promoted to a key the schema does not have.",
]

MAMMO_TERMS = [
    "ماموگرافی → mammography",
    "توموسنتز → tomosynthesis",
    "میکروکلسیفیکاسیون → microcalcifications",
    "کلسیفیکاسیون → calcification",
    "توده → mass",
    "آسیمتری → asymmetry",
    "دیستورشن → architectural distortion",
    "دانسیته پستان → breast composition",
    "غدد لنفاوی زیربغل → axillary lymph nodes",
    "پروتز → implant",
]

#: Study types, on the same second axis as ultrasound and radiography.
MAMMO_SUBTYPES: Dict[str, dict] = {}


def _s(key, title, technique, must, path):
    MAMMO_SUBTYPES[key] = {"title": title, "technique": technique,
                           "must_report": must, "pathology": path}


_s("mm_screening", "Screening mammography",
   ["Preserve that this was a screening study on an asymptomatic patient. A symptom "
    "reported at the time of a screening study changes it into a diagnostic one — "
    "preserve any such statement."],
   ["Preserve breast composition, both breasts assessed, the axillae, and the BI-RADS "
    "category per breast.",
    "Preserve any comparison with prior studies and their dates."],
   ["An incomplete assessment on screening means additional imaging is needed. Preserve "
    "that outcome and what he asked for; never resolve it into a final category.",
    "Preserve any recall recommendation exactly as stated."])

_s("mm_diagnostic", "Diagnostic mammography",
   ["Preserve the presenting complaint or the recall reason, and the additional views "
    "obtained to answer it. A diagnostic study exists to resolve a question and the "
    "question must be visible in the report."],
   ["Preserve the targeted finding with its full location and lexicon description, and "
    "preserve correlation with ultrasound or examination if he made one.",
    "Preserve the BI-RADS category per breast."],
   ["Preserve any biopsy or short-interval follow-up recommendation exactly, inside "
    "Pathological Findings, since this schema has no Recommendations key.",
    "Preserve his statement when a finding resolved on additional views — that a "
    "summation artefact was excluded is a finding."])

_s("mm_tomosynthesis", "Digital breast tomosynthesis",
   ["Preserve that tomosynthesis was performed, on which views, and whether the 2D "
    "image was acquired or synthesised.",
    "Preserve the slice or slab location of a finding seen only on tomosynthesis — it "
    "is what makes the finding findable again."],
   ["Preserve whether a finding was visible on 2D, on tomosynthesis, or on both.",
    "Preserve architectural distortion seen only on tomosynthesis as its own finding."],
   ["Preserve his statement that a 2D asymmetry resolved on tomosynthesis, and never "
    "carry forward a finding he explicitly excluded."])

_s("mm_implant", "Mammography with implants",
   ["Preserve the implant type, position (retroglandular or retropectoral) and side, "
    "and whether implant-displaced (Eklund) views were obtained.",
    "Preserve any statement that tissue was obscured by the implant. That limitation "
    "qualifies the whole examination."],
   ["Preserve implant contour and integrity as he described them, per side.",
    "Preserve capsular calcification, herniation or rupture signs separately from the "
    "breast tissue findings."],
   ["Preserve his wording on suspected rupture, including any hedge, and any "
    "recommendation for MRI or ultrasound — mammography does not exclude rupture and "
    "any such caveat must survive."])

_s("mm_post_treatment", "Post-surgical and post-radiotherapy mammography",
   ["Preserve the surgery or treatment and its date if he referenced it, and the side.",
    "Preserve which prior study he compared against and its date."],
   ["Preserve the surgical bed with its location, and any scar, distortion, seroma or "
    "fat necrosis he described there.",
    "Preserve skin and trabecular thickening as expected post-radiotherapy change where "
    "he characterised it that way.",
    "Preserve clip and marker positions."],
   ["Preserve his distinction between expected post-treatment change and a new or "
    "progressive finding. That distinction is the entire purpose of the study and it is "
    "the thing most easily lost when the wording is generalised.",
    "Preserve any increase, decrease or stability across the interval."])
