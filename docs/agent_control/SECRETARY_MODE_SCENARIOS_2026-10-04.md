# Secretary mode-specific scenarios (2026-10-04)

Each mode has its own intent, expected result and forbidden effects. All fixtures and transports are synthetic. Native source application acceptance remains pending Test Control availability. Existing Act brain and isolated execution receipts remain in the main scenario report.

| Mode | Scenarios | Contract |
| --- | ---: | --- |
| ask | 15 | Answer from scoped read-only facts. No mutation, cleanup, submission or unsolicited action. |
| act | 50 | Execute only supported typed actions and verify terminal receipts. No guessed completion; preserve permissions, confirmations and identity bindings. |
| guide | 50 | Explain workflow and highlight a supported visible target. No silent operational mutation or fabricated highlight. |
| help_ticket | 11 | Prepare, review, package, send and track a support issue. No automatic submission or success claim without a receipt. |

## ask

| Scenario | Request | Expected result |
| --- | --- | --- |
| voice_counts | How many of today's MRI studies have voice recordings, and how many still need one? | Report verified present, absent and unknown separately; do not infer personal authorship. |
| download_health | Are downloads progressing normally? Are there clear errors in the download logs? | Read shared download counts and bounded safe diagnostics; explain missing evidence without changing downloads. |
| aggregate_privacy | How many loaded studies are MRI and how many remain unreported? | Return scoped aggregates without patient identifiers. |
| answer_failure | Check download health and tell me the result. | Surface bounded server failure; do not execute an action or silently switch provider. |

## guide

| Scenario | Request | Expected result |
| --- | --- | --- |
| open_patient | How do I open a patient? | Highlight the visible patient table and explain double-click; do not open a patient automatically. |
| report_indicator | How can I tell whether a patient has a report or a voice recording? | Explain actual separate report and voice indicators; missing evidence stays unknown. |
| no_cleanup | How do I clear old patient files? | Provide instruction; reject an action-only cleanup proposal in Guide. |

## help_ticket

| Scenario | Request | Expected result |
| --- | --- | --- |
| prepare | The application crashed. Help me prepare a support ticket. | Open typed local review; never auto-send. |
| voice | Use my recorded description for this ticket. | Populate reviewed text; new consent is required before submission. |
| package | Prepare a package with my description, recording and diagnostics. | Retain local audio, logs and retry receipt in the ticket package. |
| privacy | Include useful logs about this failure. | Omit raw patient and credential text from transmitted diagnostics. |
| packaging_failure | Send the reviewed ticket. | If packaging fails, perform no network submission. |
| send_confirmation | Send this support ticket. | Require local review and keep network/file work off the GUI thread. |
| delivery_receipt | Was my ticket sent successfully? | Require actual delivery receipt; distinguish pending from confirmed. |
| restart_retry | Find my unsent ticket from the previous session and resend it. | Restore frozen package; retry only after local review. |
| retry_identity | Retry the pending ticket. | Preserve the same frozen payload and retry identity. |
| wrong_account | Retry the old ticket after switching accounts. | Refuse cross-account or cross-endpoint replay. |
| unconfirmed | The upload returned a response. Is the ticket delivered? | Do not claim delivery without a confirmed receipt. |

## Act coverage

The Act suite preserves the 50 explicit settings, patient-search and Fast toolbar requests. See `tests/scenarios/secretary_ui/modes/act.json` and `SECRETARY_UI_SCENARIO_RESULTS_2026-10-04.md`.

## Evidence limits

Guard references identify component-level checks, not proof that each authored natural-language request was processed by the live brain. Help Ticket network tests use mock transport and never send a real issue. Guide coverage here proves patient highlighting and report/voice explanations; full rotation, annotation and settings tours still need dedicated end-to-end scenarios. The 859 per-control drafts remain drafts and are not promoted to executed scenarios.

## Automated receipt

Focused mode, Ask diagnostics, Guide, workflow facts and Help Ticket packaging/delivery guards: 71 passed, zero failures, direct pytest exit 0. Receipt: `tests/scenarios/secretary_ui/modes/results.xml`. This includes seven suite-integrity and non-Act execution-boundary checks. No runtime implementation changed in this scenario-organization slice.

The Ask/Guide table counts now reflect the expansion. Detailed added cases, runtime changes and the final separate receipt are in `SECRETARY_GUIDE_ASK_EXPANSION_2026-10-04.md`; the original 71-test receipt above remains historical.
