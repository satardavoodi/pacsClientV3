# Reception normal templates — 2026-09-20

## Implemented workflow

Settings > EchoMind > Reception Normal Templates and EchoMind > Normal Template >
Manage > Reception open the same browser. Refresh uses the active server's existing
Reception API configuration and the in-memory signed-in token. No separate address,
password, background synchronization, or Reception write is introduced.

The browser resolves Reception modality IDs through `/api/Modality/getAll`, including
MR -> MRI and DX -> RADIOLOGY. It defaults to the current report modality. Search,
personnel selection, and My templates first operate on downloaded records. The
verified Reception account ID from `/api/AdminUser/verify-token` prioritizes templates
whose User field matches. A linked PersonnelID is also supported when returned;
the currently inspected verify-token response does not expose this link, so automatic
priority currently uses the creator account. Manual personnel filtering remains available.
Never infer identity from a person's display name.

`/api/sample-reports` supplies paginated records with Name, Html, Modality, User,
Personnel, UpdatedAt and Disabled fields. This is a sample-report library, not a
guaranteed normal-only catalog. Import requires preview, selection and an explicit
normal-template review checkbox. The original HTML is retained locally; the model
receives the same plain template text shown in the composer.

Imported records are local, portable copies in the existing personal library, with
source provenance. IDs include the source/profile, remote record ID and body revision.
Reimporting an identical version preserves local edits. A changed remote body creates
a separate copy. There is no automatic overwrite or deletion of personal templates.
Open composers receive an in-process library update after a Settings import.

Network, parsing and import writes run on retained workers. Downloads use bounded
pagination, size, request timeouts and a total deadline; closing requests cancellation.
Redirects are rejected and the Reception session does not inherit provider proxy settings.
Account/server changes invalidate an in-flight fetch or import. Errors never include
remote bodies, credentials or clinical text. Incomplete pagination fails visibly.

## Organize, save and edit workflow

Settings > EchoMind > Reception Normal Templates now provides the browser and a
direct **Saved organized templates** entry. Select multiple downloaded templates
with Ctrl/Shift and choose **Optimize, Organize & Save**. The worker calls the
existing company report model sequentially, with the same center access and HTTP
transport as reporting. No Reception writes or separate credentials are introduced.

The organizer returns short section labels, category labels and source block IDs.
Local code requires every block exactly once, rejects unknown/duplicate/missing IDs,
and reconstructs content exclusively from source text. It does not translate,
rewrite clinical sentences, fill measurements or synthesize normals. Non-normal,
mixed, technique and incomplete blocks remain in the original and organization
views; only normal candidates populate the editable draft. Classification is a
model suggestion, not a clinical correctness guarantee.

Drafts are saved separately in `organized_template_drafts.json`, beside the existing
normal template library. Each draft retains its original record, complete blocks,
grouping, source hash, proposed wording and latest edited wording. Repeated processing
of the same source/version reuses its saved draft without calling the model or
overwriting edits. A changed source revision produces a different draft. Each success
is persisted immediately; failures are counted and retrying skips completed items.
Cancellation or account/server changes discard an unfinished model result and stop
the queue. In-flight HTTP requests finish within the existing transport timeout.

**Saved organized templates** shows original text, grouped/excluded content and an
editable final text. **Save & Use** explicitly publishes the reviewed text to the
ordinary Normal Template picker. Drafts never appear there automatically. Later
wording edits preserve library name/tag edits; stale draft editors cannot overwrite
newer wording. Save/read/network work runs off the GUI thread. Unsaved wording blocks
selection changes, offers a discard action and is checked on close. Settings and
Manage open the same editor; published changes notify open composers while retaining
their active working text.

HTML conversion now preserves adjacent table cell boundaries and decodes hexadecimal
entities exactly once, without deleting plain numeric inequalities. Original HTML is
retained separately. Reporting prompt behavior is unchanged by this organizer feature.

Initial organization/parser guards failed in nine cases before implementation. The
focused organization/library/prompt/offscreen suite passed 149 tests; 19 edition-stage
tests passed. A bounded provider check organized five existing sample templates with
complete source coverage. Thirty pre-identified non-normal or incomplete blocks were
excluded from normal candidates in those samples. This is sampled provider evidence,
not universal semantic validation. Native source GUI acceptance remains blocked as
described below; no installer build or clinical report update was performed.

## Reporting behavior (existing template contract)

The shared report prompt had a contradictory allowance for normal content outside a
supplied template. It now makes the template exhaustive, with a final precedence rule
after modality defaults. Preserve unaffected statements, remove conflicting statements,
or narrow paired/grouped statements to unaffected members. Keep all dictated pathology,
including pathology outside the template. Existing sex-specific and placeholder exclusions
remain in force. No-template reporting remains unchanged.

The company, direct-provider and Turbo paths use this shared prompt in normal operation.
This is an instruction contract, not a deterministic semantic verifier of arbitrary model
output. Physician review remains necessary; the tests below establish the sampled behavior.

## Verification receipt

- Five initial regression cases failed before implementation (missing adapter, DX mapping,
  provenance and contradictory template rule). An additional restart test exposed an
  unresolved remote modality being guessed from its name; it failed before correction.
- Final focused/offscreen suite: 332 passed, exit 0. Covers template core, shared
  prompt/Turbo parity, worker lifecycle, filters, import and typography/export boundaries.
- Real company-provider synthetic examples covered CT, MRI, sonography, radiography,
  mammography and obstetric ultrasound. Conflicting normals were removed and unaffected
  normals retained. The repeatable import-to-provider test passed for five modalities;
  the obstetric assertion initially rejected valid laterality insertion (`No right renal
  pelvic dilatation`). After accepting that permitted wording, the scoped obstetric test
  passed. These are synthetic tests, not patient report changes or a general accuracy claim.
- `tests/live/test_reception_template_reporting.py` is opt-in with
  `AIPACS_TEST_TEMPLATE_MODEL=1` and `pytest -m live`; it incurs provider usage and uses
  temporary template storage. No live patient database is opened by these tests.
- Scoped mirror synchronization used `sync_plugin_mirrors.add_paths`; 470 mirrors matched.
  Edition staging checks retain the new adapter, browser, template core and prompt bytes.
  No installer was built and no Reception service was changed.

## Default Turbo routing follow-up

The original shared-prompt tests did not cover the default regional V2 renderer.
That renderer replaced the shared prompt and silently discarded a supplied normal
template. Five modality cases failed before correction. Requests with a supplied
template now retain the shared template-aware contract; requests without one keep
the existing regional V2 structure. This applies across supported modalities.
`test_turbo_supplied_normal_template.py` covers six modalities and the unchanged
no-template route. The combined prompt/import/offscreen suite passed 168 tests,
exit 0. The 19 edition-stage tests also passed. Scoped Turbo mirror synchronization
verified 470 matching pairs.

Reception sample reports may contain pathological examples and unfilled measurements.
They must not be treated as pure normal templates without the existing preview/review
step. The private paired evaluation selects normal-only source lines and records a
meaning-preserving English translation; it does not import full pathological examples.
Its pelvis subset is sex-neutral and is not a complete sex-specific pelvic template.
No clinical report is overwritten by that evaluation. Automated provider evaluation
does not satisfy native source GUI or Reception export acceptance below.

## Remaining live acceptance

### Named pathology codes and fillable fields (2026-09-21)

Organizer version 3 distinguishes baseline normals, standalone fillable fields,
named `pathology_code` groups, and unnamed abnormal/uncertain examples. A named code
keeps all its source sentences, including internal blanks. `code_name_id` references
its original label block (or `template_name` for a whole named-code record); local
code copies the label without allowing the model to shorten or invent it. Each
source ID still appears exactly once. Ambiguous code boundaries stay in review.

Drafts retain structured groups, original source and editable final text. The
published text contains explicit `ON_REQUEST_PATHOLOGY_CODE` and `TEMPLATE_FIELDS`
boundaries, so the existing preview/editor, library reload and composer preserve
the same visible content. Physicians can edit labels and sentences in the final
editor while retaining boundaries. Old saved edits remain intact; reorganization
creates a version-3 draft and requires explicit Save & Use.

Template-bearing report prompts now treat explicit requests for available codes
as authorization to expand their source wording into numbered pathology findings.
Unrequested, negated or cancelled codes remain inactive. Region/modality mismatch,
ambiguous names and missing codes require clarification rather than invented
expansion; values must come from dictation. Explicit physician corrections override
code wording, and only conflicting normal baseline statements are removed/narrowed.
Legacy explicitly named code sections receive the same prompt rules. Code lookup
is within the template text supplied to the request, not an invisible search of
other saved templates. No-template routine reporting receives no code instructions.

The source-preservation/publish/reload guard failed before implementation. Combined
focused/offscreen/edition suite: 180 passed, exit 0; 470 mirror pairs match. A live
synthetic GapGPT/Sol probe preserved two named codes and a blank field, expanded
the requested lumbar code's two sentences without brain-code contamination, and
excluded macros on unrequested and cancelled-code scenarios. Initial model output
shortened names and was safely rejected; switching to source-label IDs resolved
that observed failure. These are bounded synthetic checks, not clinical proof of
all spoken names or ambiguous-code behavior. Native source GUI and Reception
acceptance remain blocked by the unavailable local control connection.

### GapGPT organization follow-up (2026-09-21)

The owner clarified that organization uses the GapGPT account configured in
EchoMind Settings. This is the existing Company Authentication connection and its
resolved GapGPT credential, not a ChatGPT subscription login or the separate
OpenAI direct connection. Organization now explicitly requests `gpt-5.6-sol`,
independent of the report model. No alternate model or provider is selected on
failure. Settings explains this routing.

Organization prompt version 2 requires complete immutable source-ID coverage,
neutral anatomical headings and conservative whole-block classification. It forbids
rewriting, translation, invented normal observations and salvaging normal clauses
from mixed abnormal blocks. Rendering still uses original source text locally.
Versioned draft IDs preserve earlier drafts and physician edits.

Two new guards failed with the former Terra selection and pass with Sol. The
combined organization, import, prompt, offscreen UI and edition-stage suite passed
170 tests, exit 0; all 470 mirrored pairs matched. A synthetic four-block request
through the saved GapGPT connection succeeded with requested model `gpt-5.6-sol`:
all source blocks were retained, and abnormal, incomplete and mixed blocks were
excluded from proposed normals. No patient data was used and nothing was published
to the clinical template library. This confirms provider acceptance of the model
identifier, not an independent attestation of the provider's underlying model.
The documented native-control ping still failed on September 21; native Settings
acceptance remains blocked. No application restart or release build was performed.

The documented source-control `client.py ping` failed: no local Test Control Server.
The human must start one fresh source instance with `run_app.ps1 -TestServer` outside
clinical reading, acknowledge disk warnings with OK, and sign in. Normal clinical launches
continue to default to `AIPACS_TEST_SERVER=0`.

Then probe ping/list_actions and verify native Settings/Manage entry points, authenticated
Reception refresh, actual current-user priority, modality/personnel changes, preview and
explicit import, composer selection, synthetic pathology generation and Reception preview.
Do not overwrite a real patient report as test setup. Source GUI and authenticated PACS-to-
Reception acceptance are currently BLOCKED, not passed. Existing Reception schema/read-only
discovery and offscreen Qt tests do not substitute for this gate.

## Linked language versions (2026-09-21)

Organization version 5 adds source-preserving English/Persian pairs, separate preparation and publication, and report-bound Persian wording reuse. See [behavior and validation](BILINGUAL_TEMPLATE_VALIDATION_2026-09-21.md).
