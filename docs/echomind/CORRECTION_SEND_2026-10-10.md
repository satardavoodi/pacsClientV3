# Correction Send regression - 2026-10-10

The owner reported repeated Correction Send producing no result after testing
reporting, translation, web search and standardization. Two local tracebacks
showed NameError for removed `turbo` in `_send_report_correction`, before worker
scheduling. The unified Send migration removed the variable but left the bubble
label conditional. Replace only that label with `You (Correction)`.

The regression executes the actual extracted method with synthetic UI and
transport collaborators. It failed with the same NameError before the fix and
now reaches exactly one remote correction worker. No prompt, model, payload,
patient identity, study-profile or template policy was changed.

Read-only exact-request metadata correlation found all four recent successful
workflows in both local transport history and active Razi server history. Their
server durations were approximately 12.3, 8.8, 16.0 and 25.6 seconds respectively.
No request/report content or patient identifiers are recorded here. Correction
failed before dispatch; it was not a server provider failure.

The recent report had a study profile but an empty normal_template. The current
local configured template-library file was absent; this is not proof of another
process's transient composer contents. Applied-template acceptance remains open.
Synthetic template import, preservation, prompt composition and worker propagation
checks passed. The broader selection had 143 pass and two existing failures:
reception-template guard expects generic template-heading text in the dedicated
echocardiography branch; bilingual translation guard mocks the old direct route
but now invokes authenticated remote translation. These were not hidden or
weakened. A focused Correction/template selection passed 120 tests.

Scoped EchoMind payload mirror synchronized. Root server coordinator owns
immutable Developer reconciliation; no executing Razi files or services changed.
Local Test Control ping was unavailable. Human source Correction Send and actual
selected normal-template GUI acceptance remain pending. No provider replay,
clinical write, installer build or release performed. This shared source/mirror
fix is next-build input only, not artifact acceptance.
