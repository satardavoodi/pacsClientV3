# Linked English and Persian templates

## Behavior

Organization version 5 retains the authored source exactly and prepares a linked
counterpart using the saved GapGPT account and gpt-5.6-sol. Both versions and a
source hash survive local library reload. English is the report-generation baseline;
Persian is a wording reference, never a second set of patient findings.

The review dialog exposes Editable source, English, and Persian tabs. Editing
invalidates the pair. Generate Linked Versions prepares a draft without publishing;
Save & Use becomes available only after preparation. Counterpart tabs are previews;
wording changes are made through the source editor and regenerated for review.

Translation uses the originating report's template snapshot, not the current
composer selection. Final report facts outrank template wording. Exact whole-field
matches reuse the authored Persian line locally; changed or partial statements are
translated with explicit anatomy, side, negation, uncertainty and measurement rules.
Unused normal clauses, codes, options and assessments must not return. Both reporting
backends preserve this snapshot through Correction.

The bounded local reference cache stores report hashes and template snapshots, not
report text. Ambiguous hashes, missing references, manual report changes outside
Correction, and evicted references fall back to ordinary translation. This is not a
general provenance system. Standardize operates on dictation and is not covered by
the report-correction transfer.

## Independent review and resulting fixes

An independent read-only review identified publication before counterpart review,
unit/blank changes surviving validation, mixed Persian/English source misclassification,
and loss of reference after Correction. Preparation/publication are now separate;
numbers, Latin measurement units, underscores, dots and bracketed slots are checked;
Persian lexical characters identify mixed Persian prose; Correction transfers its
original snapshot. These checks do not prove semantic translation equivalence.

The earlier five real mammography cases remain flagged for physician/audio review.
ASR was not independently certified, and matching template personnel does not prove
the historical template revision. See TEMPLATE_MERGE_VALIDATION_2026-09-21.md.

## Evidence and outstanding acceptance

- 239 focused code, offscreen UI and edition-stage guards passed, exit 0.
- A fresh real GapGPT run on a generic Reception template preserved original Persian,
  persisted/reloaded both versions and reused one unchanged normal statement exactly.
  Private evidence includes source and prompt/code hashes; no patient report was sent.
- 470 plugin mirror pairs match. No release or installer was built.
- Documented native-control ping failed: no reachable source Test Control Server.
  Native Settings, report rendering, translation and Reception export acceptance remain
  pending. Offscreen tests and the limited provider probe are not clinical acceptance.

Guard: tests/code/echomind/test_bilingual_templates.py; review workflow coverage:
tests/gui/test_reception_template_ui.py. Existing templates without linked versions
remain supported and use ordinary translation until prepared and reviewed.
