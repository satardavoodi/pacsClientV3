# Regional volume reference profile and atrophy-pattern review

Status: report candidate; physician interpretation and Client/Server acceptance remain separate gates.

`modules/ai_imaging/eagle_eye_brain/atrophy_patterns.py` adds two sections to the
organized volumetry renderer. The first plots bilateral hippocampus, amygdala,
entorhinal and parahippocampal cortex, frontal pole, precuneus and cuneus when
matching observations and valid published reference limits are available. The
reference median is 100% independently for each region. The dot is measured
volume / reference median, and the band is the published 95% interval / median.
This scale is not a percentile, Z-score, tissue-loss percentage, atrophy grade,
disease likelihood or calibrated diagnostic index. Numerical physical volumes,
medians and limits remain alongside the plot. Cortical counterparts are explicitly
anatomical analogues and do not generate low-volume/atrophy flags.

The second section is a physician checklist for medial temporal, frontotemporal,
language-predominant and posterior cortical patterns. It identifies relevant
anatomy and required clinical context. It does not automatically assert that a
syndrome is present or absent. MRI volume alone cannot establish Alzheimer's
disease; an MTA grade needs visual assessment, and cortical volume is not cortical
thickness. Missing reference coverage is never interpreted as normality.

## Evidence

- Scheltens et al., 1992. Medial temporal atrophy visual assessment:
  https://doi.org/10.1136/jnnp.55.10.967
- Jack et al., 2024. Revised Alzheimer's disease diagnostic criteria:
  https://doi.org/10.1002/alz.13859
- Rascovsky et al., 2011. Behavioural variant FTD clinical/imaging criteria:
  https://doi.org/10.1093/brain/awr179
- Gorno-Tempini et al., 2011. PPA clinical and imaging-supported variants:
  https://doi.org/10.1212/WNL.0b013e31821103e6
- Crutch et al., 2017. Posterior cortical atrophy consensus:
  https://doi.org/10.1016/j.jalz.2017.01.014

These scientific criteria describe review patterns; they are not the numerical
normative dataset. Numerical ranges still come from the existing pinned offline
volBrain / AssemblyNet tables and their existing age/sex/ICV calculation, with
the documented cross-method limitations. No new reference source is activated.

## Verification and integration

Synthetic guards in `tests/code/ai_imaging/test_brain_atrophy_patterns.py` reject
nonfinite/invalid limits and mismatched observations, preserve original volume
data, retain unavailable results and verify PNG encoding. The new guard failed
before implementation (seven missing-module failures); the focused report suite
then passed 37 tests. Qt QImage/QPainter uses the existing report worker and
QGuiApplication; no new rendering dependency or provider call is added. HTML
without a QGuiApplication retains the numerical table. Patient PDFs and images
stay in protected local storage and must not enter source or test fixtures.

Source mirror/parity, active Razi source, live Client acceptance and release build
are recorded by the coordinating workstream. This report addition alone does
not claim those gates passed or authorize release.
