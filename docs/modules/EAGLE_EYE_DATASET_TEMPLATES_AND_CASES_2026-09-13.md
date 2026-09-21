# Eagle Eye dataset templates and case forms

Status: implemented in application source; automated and synthetic visual checks
passed. Live acceptance in the human-launched source workstation is pending.

## Delivered workflow

Eagle Eye -> Data Set -> Datasets now supports three separate operations:

1. **New Dataset** creates a named collection with modality, anatomical area and
   a reusable field template. Start from Lumbar spine, a blank template, or a copy
   of another saved dataset's template. Add/remove fields, edit labels, choose
   text/multiline/number/choice types, define choice values, mark fields optional
   or required, and select once-per-case or once-per-region repetition.
2. **Add Current Study** binds the open Eagle Eye study to the selected collection
   and opens a form instantiated from that collection's current template. Patient
   code/name and study information come from a background local PACS lookup by
   the workspace study UID. Repeating enrollment opens the existing form without
   clearing its answers or creating another case. A modality mismatch or conflicting
   patient identity is rejected visibly.
3. The modality -> anatomy -> dataset tree shows case counts. The saved-case table
   shows patient code/name, study date, form status, filled fields, template version
   and save time. Search the list and double-click a case or use Open Selected Case
   to continue editing. The open study and the case being edited remain distinct
   identities; browsing a case does not silently change the clinical viewer.

The case dialog is nonmodal so Imaging Tools and Reception remain available for
reference. Dataset/template navigation within its owning dataset workspace is
disabled while that editor is open. The form supports Save Draft and Save Completed
Form. Closing an edited form asks before discarding unsaved edits. Saves run in the
background, disable duplicate submissions, and retain the form on a validation or
storage error. Complete requires a form author, at least one answer, and every
required field defined by that case's saved template.

The default lumbar template has 15 optional finding fields repeated over five
levels, plus one case notes field: 16 field definitions, 76 possible answer slots.
The findings are the existing lumbar binary morphology/degeneration targets,
central canal stenosis, bilateral recess/foraminal stenosis and bilateral root effect.
All start unknown. Custom forms support up to 100 fields and 30 regions; choices
are semicolon separated. Required per-region fields must be answered at each
configured region before the form is complete.

## Template versioning and persistence

Editing a template publishes another version. New cases use it automatically;
previous cases retain a complete snapshot of their original template and answers.
Removing, renaming or changing a field cannot reinterpret a saved old case.
Changing modality or anatomy after enrollment requires a separate collection.
There is no automatic migration of old answers to a revised template.

Production storage is created on first use at:

`C:\AI-PACS-Datasets\eagle-eye-workspace\catalog.sqlite`

The catalog is separate from the live clinical `dicom.db` and the existing
`lumbar-mri\v0.1` research dataset. SQLite transactions store dataset definitions,
all template versions, case records and append-only case revisions. The active
case update and its revision record commit together. Expected revision/version
checks prevent an older window overwriting newer edits. Study membership is unique
per dataset + source namespace + study UID, not patient code alone. One study may
belong to several collections. The current source namespace is local-pacs; a future
multi-center import must explicitly provide center-scoped identity.

This step stores identity-linked form records. It does not duplicate/download images,
automatically import the historical 291-case research cohort, transfer data to a
server, or promote forms to MONAI training labels. `training_eligible` remains false;
form completion is not image-reference approval. Existing HTML image review, source
reports, report proposals, patient splits and research files are unchanged. Their
shared-adapter migration and server release contract remain in the broader design.

## Source boundaries

- `modules/ai_imaging/eagle_eye/datasets/definitions.py`: pure schema and value
  validation, unknown defaults, lumbar preset and field expansion.
- `repository.py`: transactional catalog and immutable revisions, explicit
  enrollment identity, background-callable local study resolver.
- `dialogs.py`: reusable template builder and version-bound form; no filesystem,
  network or database work.
- `workspace.py`: native collection/case browser, bounded Qt pool jobs, application
  dispatcher and identity-bound callbacks. Workers own no widgets. Qt disconnects
  destroyed receivers; pending jobs can finish without touching deleted UI.
- `ai_module_ui/service_tab/dataset_tab.py`: attaches the workspace as the default
  Datasets section and retains AI Result Tables as the legacy CSV section. Explicit
  CSV pushes/refresh continue to use the existing result path. Opening the new
  catalog does not scan study attachment CSVs.

This is an internal feature of the already collected `modules.ai_imaging` package,
not a new optional installer module. No runtime module ID, feature flag or config
family was introduced. No edited source belongs to a plugin payload mirror. The
existing default-build inclusion guards cover both build collectors. No installer
was built or installed and no clinical application instance was launched by the agent.

## Verification

- The initial new repository tests failed because the required feature package did
  not exist. After implementation, the 18 new tests pass: independent case values,
  concurrent duplicate enrollment, schema snapshots/removal, conflicting writes,
  invalid/missing values, modality/identity mismatch, overlapping collections,
  retained history, field builder behavior, a full native create/enroll/save/reopen
  cycle, case switching, failed saves, closed receivers and draft preservation.
- Focused combined selection: **75 passed, exit 0**, with existing SWIG deprecation
  warnings. It includes dataset identity, Eagle Eye workspace/UI boundaries and
  default-build inclusion guards alongside the new tests.
- Three synthetic offscreen Qt renders were inspected: collection browser,
  template editor and lumbar case form. Explicit Optional/Required choices and
  nonalternating row backgrounds preserve readability with the workstation theme.
  Synthetic screenshots remain in `generated-files/dataset-workspace-review-20260913`.
- Tests use temporary dedicated catalogs and injected synthetic study resolvers.
  No live PACS database, patient payload, remote provider, GPU job or real annotation
  was accessed or modified by this verification.

Source acceptance: open Eagle Eye -> Data Set on a locally loaded study; create a
lumbar collection, change its fields, add the study, save and reopen the form;
repeat Add Current Study and verify one case; add a second study from its Eagle Eye
workspace; edit the template and verify old cases still use their original version.
The installed build does not include these source changes until the normal release.

Rollback only the new dataset package, the Dataset tab integration and matching
tests/docs. Preserve unrelated worktree changes and retain the user's catalog;
removing a UI feature must not delete collected forms or historical research data.
