# EchoMind report typography and Reception export

## Scope and cause

The structured report renderer assigned 15px to its root, with no distinct sizes
for section and organ headings. Display stripped explicit sizes for A-/A+, while
export kept them and changed only the document default. Thus increasing the
visible body to 24px still sent 15px paragraphs and list items. Qt also serialized
semantic headings using relative size adjustments such as `x-large`.

## Correction

- `ai_chat_pages.py::_render_kv_report_html` defines title/section/organ/body
  sizes of 22/18/16/15px before scaling, preserving existing colors and text.
- `ai_chat_widgets.py::_wrap_scale_html` resolves rich text once per conversion
  and scales all character runs and block character formats from the 15px
  baseline. Scaling block formats is necessary for list-item round trips.
- Display and `get_export_html` share this conversion. The selected body size
  remains clamped to 10-40px. Explicit point sizes and flattened heading levels
  prevent relative heading defaults from being reapplied on import.
- Conversion starts from original HTML each time. Local saved content remains
  unchanged, repeated resizing is reversible, and transport/identity selection
  and Reception status writes retain their existing implementation.
- Historical HTML gains consistent scaling; its original section hierarchy is
  preserved. The new four-level template applies to newly rendered reports.

## Verification

The first five behavioral guards failed before the fix (pytest exit 1): display
versus export size mismatch at 10/16/24/40px and nonproportional scaling. The new
suite also covers historical h2 headings, edited point sizes, list items and plain
text. Existing export guards now inspect resolved text sizes instead of merely
checking a root style or a particular CSS unit spelling.

Final focused command (offscreen Qt, PYTHONPATH set to repository root):

```powershell
.\.venv\Scripts\python.exe -m pytest -p no:debugging tests/code/reporting tests/gui/test_echomind_reception_formatting.py tests/code/builder/test_release_parity_guards.py::test_plugin_mirrors_are_fresh -q --tb=short --reruns 0
```

Result: **119 passed**, exit **0**, six third-party deprecation warnings.
Mirror synchronization updated only the two EchoMind files; verification matched
all **462** source/payload pairs. A synthetic side-by-side Qt rendering with
explicitly loaded Arial fonts showed matching typography in display and export.
This is a Qt rendering check, not a live Reception browser or print check.

A broader installer parity selection also reported a separate failure in
`test_release_gate_stage_config_parity_against_current_stage`: existing staged
templates for echomind_settings, patient_table_sort and printing_config did not
match sanitized expectations. No installer was rebuilt or claimed verified.

## Human source test

1. Close the existing source instance and launch `main.py` once from VS Code;
   the human completes login.
2. Produce a new structured report to exercise the four-level template.
3. Compare title, section headings, organ headings and body at the default size,
   then use A+ and A- to verify proportional resizing.
4. Use the normal reviewed send workflow and inspect Reception display and print
   preview. Confirm sizes and colors against the source report.

Source testing and live Reception/print acceptance remain pending. No patient
report was modified or sent during automated verification. Rollback consists of
reversing only this typography change in the two canonical files and syncing
their mirrors; do not reset the unrelated dirty worktree.

## Pathological Findings organization amendment

The raw model response retained numbered findings, but the shared line cleaner
removed their numbers and the renderer emitted only a paragraph with breaks.
Its multiline early return also bypassed sentence splitting. The dedicated
pathology renderer now emits organ headings and ordered lists, restarts numbering
per organ, preserves explicitly grouped continuation text, and separates terminal
sentences within each item. Each item has an 8px bottom margin and 150% line height.
Plain paragraphs remain a single finding; separate list entries/lines become
separate findings. Text is escaped without removing punctuation. Decimal values,
common abbreviations and initials are protected by conservative boundary rules.
This is deterministic layout, not clinical reinterpretation or LLM regeneration.

`tests/code/reporting/test_echomind_pathology_layout.py` initially failed all eight
checks (exit 1). After repair, reporting plus GUI export checks passed 126 tests
(exit 0), and the separate builder mirror guard passed (exit 0). All 462 payload
pairs match. The new checks cover string/list/dictionary inputs, numbered/bulleted
findings, continuations, actual Qt decimal lists, sentence breaks, margins,
A-/A+ parity, abbreviations, decimals and escaped punctuation. A synthetic visual
comparison confirmed matching display/export layout with readable spacing.

Newly rendered report responses use the new structure. Existing saved HTML and
reports already in Reception are not rewritten. Restart the source instance and
render a new response, then use the reviewed send workflow for live Reception
and print acceptance. No clinical report was sent or modified by this amendment.

## All-modality and next-build coverage

The current `REPORT_MODALITIES` catalog contains CT, MRI, SONOGRAPHY, OBSTETRIC
ULTRASOUND, RADIOLOGY and MAMOGRAPHY. All use the same structured report renderer.
Ordinary report generation, both correction entry points, HQ/all-modality,
report translation and ChatGPT Report mode call that renderer. Standardization
prepares composer input, not a final structured report. Manually edited HTML and
historical saved HTML preserve their authored structure while sharing font export.

A remaining defect affected single-value specialty sections: mammography fields
such as Breast Composition/BI-RADS and obstetric fields such as Biometry/Placenta
used body-size inline headings. They now use the same separate 18px-baseline
section heading as other report sections, retaining 15px-baseline body text.
Normal findings retain their bullets; pathology findings use ordered groups.
Optional Impression and Recommendations retain their respective sections.

`test_echomind_modality_layout.py` reads actual modality/schema constants and
checks all six report shapes at 16px and 24px, including specialty headings,
text preservation, ordered pathology and display/export parity. Four specialty
heading cases failed before repair, with direct pytest exit 1. Six structural
entry-point guards keep these flows on the shared renderer.

Next-build evidence: `test_every_edition_retains_current_echomind_report_renderers`
stages the actual canonical/payload renderer bytes through Eagle Eye, Standard
and ARM edition profiles and verifies byte preservation. Both build backends
use the source-tree EchoMind package; materialization regenerates its version
metadata from the candidate version. Do not hand-edit historical package versions.
All 462 source/payload pairs match. Final reporting, GUI export, edition-profile
and mirror selection: **164 passed**, exit **0**, six third-party warnings.
No compiler/installer or live non-MRI clinical workflow was executed.

These changes are next-candidate source changes, not evidence that the completed
September 10 installers already contain them. The next canonical build must
snapshot this source and regenerate packages, then pass its ordinary release,
security, installer and live acceptance gates.
