# Template measurement and mammography validation

## Scope and evidence

The owner requested real-provider checks of uterine dimensions, renal lengths,
unilateral cortical abnormalities, and recent mammography dictations. No clinical
report, Reception template, user library or active application was overwritten.
Private source/audio/output material is kept only in the ignored local artifact
directory; no patient content or identifiers belong in these regression fixtures.

Eight synthetic provider checks in `tests/live/test_template_measurement_merge.py`
passed, exit 0, after the final changes. They use the real configured GapGPT report
route and the production default report model; organization uses GPT-5.6 Sol.
Coverage: two uterine dimension pairs and source units; separate renal lengths;
unilateral cortex abnormality with contralateral normal preservation; retaining two
provided dimensions without inventing a third; not copying a right-sided length
to an unspecified left slot; latest dictated correction; and mammography positive
benign details, composition and axillary findings without unsupported muscle text.
These checks establish bounded source-fidelity behavior, not diagnostic accuracy.

## Confirmed organization defect and fix

An actual Reception choice bank exposed two structural problems: the parent FL
label was separated from its numbered history alternatives, and a negative BI-RADS
assessment option became baseline normal content. Two synthetic guards failed on
these boundaries before the correction. Organization version 4 introduces
`template_option`, keeps a parent code and its alternatives together, and renders
them under explicit TEMPLATE_OPTIONS boundaries. A local guard conservatively
demotes groups containing assessment/BC/FL labels to conditional choices even if
the model labels them as normal or as a pathology code. Options never constitute
automatic patient findings. Existing drafts/physician edits are not overwritten.

Reorganization of the same source text preserved exact original HTML and the
source-text hash, retained every block ID once, kept all three FL options with
their parent, and reduced baseline BI-RADS-labelled groups from one to zero.

Template-only report instructions now require per-fact preservation, exact
measurement/side/slot binding, explicit alternative selection, and an audit of
each normal assertion against the supplied source. FL1/BCB resolve only from their
available parent choice banks; unclear codes are not silently mapped to a different
assessment. No-template routine prompts are unaffected.

## Real mammography review and limits

Six studies were located for the requested approximate week-earlier date. Five
had Reception voice references containing the exact study UID and the matching
admission link; one lacked voice and was excluded from audio comparison. Five
recordings were retrieved with hash checks and transcribed using the required
VoiceTranscriptionService. ASR output has not been manually certified against audio.

The relevant templates were stored under the Reception radiography modality, so a
Mammography-only lookup missed them. An exploratory general-template comparison
was superseded after the selected source Personnel ID was matched exactly to all
five report radiologist IDs. A match does not prove the historical template version.
The final five-case comparison uses that matched source after version-4 organization.

Automated comparison flags are review aids, not confirmed clinical errors or proof
of equivalence. Persistent concerns include unclear spoken shorthand, omissions,
side/assessment ambiguity and broad normal statements. A reference report is also
not an infallible ground truth. These real cases must NOT be labelled as a passed
clinical acceptance suite on the strength of synthetic checks or model grading.
Private comparison pages retain the audio/transcript, saved report and candidate for
physician review; neither ASR text nor generated reports were published clinically.

## Verification and remaining gate

- 184 focused code, offscreen UI and edition-stage tests passed, exit 0.
- Eight opted-in synthetic provider checks passed, exit 0.
- All 470 packaged mirror pairs match; no installer/release was built.
- The documented native-control ping remains unavailable. Native Settings/editor,
  report rendering and Reception export acceptance are blocked, not passed.

Before clinical use, review the version-4 draft and its choice/code meanings, verify
ambiguous audio against the recording, and complete the affected source GUI workflow.
Reverting the organization/prompt slice is possible without altering source templates
or older drafts; do not republish older drafts containing unconditional assessments.
