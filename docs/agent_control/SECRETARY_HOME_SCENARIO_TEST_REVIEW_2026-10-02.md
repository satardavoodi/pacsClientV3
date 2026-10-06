# Secretary Home scenario testing review

Date: 2026-10-02. Synthetic code review only; live source and authenticated server planning are pending.

The documented local control client ping failed because the expected source test listener is absent. No downloads, patient selections, external planning prompts, CD exports, application launches or production Gateway changes were performed. Human source launch/sign-in was requested under the project operating agreement.

## Evidence

Focused existing suite: 75 passed, exit 0, six existing SWIG import warnings. Selection: command bus unit, Secretary ordinal open, workflow, execution contract, advanced-search modality contract and Home default sorting. These do not prove all requested scenarios.

Direct English parse_command_rule probes (not authenticated Secretary end-to-end requests):

| Request | Observed local rule result | Acceptance |
|---|---|---|
| Show CT studies from two days ago | list_patients, empty entities | Missing modality and exact date |
| Show knee MRI studies from three months ago | list_patients, modality MR only | Missing body region and date |
| Sort patients by image count | list_patients | Wrong action |
| Sort patients by date | list_patients | Wrong action |
| Download first patient | download_patient, empty entities | Missing ordinal identity |
| Download first and third patients | download_patient, empty entities | Missing distinct selected identities |
| Select a patient and export to CD | No rule | Requires another planner path and CD control |

Source review finds sort_patients in the legacy executor but not in the Home actions registered by build_command_bus. Existing ordinal-open guards protect captured study identity; they do not establish ordinal-download support. Existing select-top-N behavior cannot stand in for first-and-third selection. Actual authenticated server planning may differ from the local rule probes, so these observations must not be reported as deployed server failures.

## Pending live matrix

For each request verify the normalized server plan, actual filter widgets, source mode, visible rows and final result. Bind ordinals to the observed ordered list using immutable study identity, then test sort/filter changes and reject stale selections. Confirm queue entries and terminal download state separately. CD export must use only the verified selected studies and inspect the resulting workflow/output; opening a module is not successful export. Preserve real identifiers and images locally and outside this report.

Use exact two-days-ago boundaries; specify whether three-month requests mean a calendar month or a rolling interval. Do not silently broaden failed date/body-region filters. Restore Home filters and sorting after testing. Do not treat current code-only green tests as live acceptance.


## Source follow-up after owner confirmed a running application

Read-only process inspection found source main.py processes with AIPACS_TEST_SERVER=0 and no socket override. A fresh documented ping again failed. These may include subprocesses; no claim of multiple GUI instances is made. No process was terminated or restarted, and no live patient actions were attempted. Human test-enabled launch remains requested.

Fixed the independently reproduced Home sort registration gap: sort_patients now registers in the shared bus and delegates to the existing Home sorting method, with a strict date/images_count/patient_id/patient_name/modality column allowlist and asc/desc order. Two new guards failed before the change. Final focused selection: 25 passed, exit 0 (sort guards, bus unit and capability alignment). Three owned EchoMind mirrors synchronized. A registered successful call is not proof of visible sorting; live acceptance remains pending. This slice does not fix the remaining date/anatomy, ordinal-download or CD-export gaps. The running process predates this source edit.


## Connected live source lap

After the owner-assisted test-enabled launch/login, ping passed and action discovery included sort_patients. Initial list was empty. CT September 30 search returned 19 rows; the initial exact-string modality assertion was invalid for combined modalities and does not establish a CT failure. July 1-31 MR search returned 100 observed rows: every normalized date was within July and every modality token list included MR (49 MR, 51 MR/DOC). The anatomy criterion was silently ignored by the shared adapter; knee-specific acceptance failed.

Sorting the populated July list by image count and date was accepted and the 100 read-back values were descending in both cases. No native screenshot or mouse-input verification was available, so this is shared-control/read-back evidence, not complete visual acceptance. The list remains July MR sorted by date descending; original filter widgets were not captured, so exact restoration was not attempted.

Unresolved download ordinal requests for first and first/third both returned MISSING_PATIENT_ID. No patient download or CD export happened. No CD action was advertised. Authenticated natural-language server planning was not exercised by this control-only lap.

Added a fail-before guard and source rejection UNSUPPORTED_ANATOMY_FILTER so an unsupported knee/body-region request cannot silently broaden to all MRI studies. This prevents false success; it does not implement anatomy filtering. The running app predates this last change. Further implementation remains necessary for anatomy search, ordinal downloads and CD export.
