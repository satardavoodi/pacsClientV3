# Secretary client / Eagle Eye Server contract - 2026-09-30

Owner authorization: the echomind chat owns the client migration; the
mammography eagle eye chat owns the headless server implementation and target
deployment prerequisites. Preserve other shared work. This document is the
coordination surface; append separate CLIENT RECEIPT and SERVER RECEIPT sections.

## Wire protocol

POST `/v1/secretary/plan` on the existing authenticated Eagle Eye TLS listener.
Reuse paired certificate/token checks and worker-only client transport. No new
port, credentials, provider fallback or GUI execution service.

Required fields: `protocol: 1`, canonical UUID `request_id`, `phase` (`route`,
`plan`, `repair`), raw `text` (nonempty, max 20000 characters), `language`
(`fa`, `en`, `auto`), and offset-aware ISO8601 `client_time`. Optional fields:

- `modules`: at most 30 supported module IDs; pre-routing is data, not authority.
- `memory_context`: at most 20000 characters of quoted prior cycles. Company
  instruction headers are stripped by the client; server owns memory interpretation.
- `invalid_plan`: object for repair only.
- `validation_errors`: list of error objects for repair only.
- `execution_error`: `{code: string, message: string}` for repair only.
- `attempt`, `max_attempts`: integers 1..5 for execution repair.

Reject other fields, especially prompt/messages/catalog/documents, provider,
model, API key, URL, arbitrary code, tool credentials or storage paths.
Response: `{protocol:1, request_id:<same>, phase:<same>,
route:{modules:[...],reason:string}, plan:<object|null>}`. Route returns plan:null.
Plan performs server routing if modules are absent, then server action planning.
Repair interprets validation/execution failures and builds its prompt on server.
Use normal safe HTTP errors for malformed input, unavailable service, provider
failure and admission limits. No echo of inputs/prompts/exceptions in diagnostics.

## Execution boundary

The client validates single actions with `validate_plan` and workflow steps with
`validate_steps` before returning to the existing orchestrator. Unknown means
clarify; malformed/unsupported means no execution. The existing local executor,
CommandBus/MCP adapters, source/case ownership and confirmation gates remain in
force. Server-produced plans must never select arbitrary code/tool implementations.
No GUI, adapters or clinical database imports in the headless planning service.

Company mode is server-only regardless of legacy center alias. Server failure
does not run a local rule/LLM alternative. The explicit personal OpenAI mode
requires a personal key and the user's own phase-specific prompt; no bundled
company prompt is appended. Direct raw prepared company-prompt submission is
rejected on the client. Audio capture/STT is outside this text-planning slice.

## CLIENT RECEIPT

Client implementation is complete for company route, plan and repair. The new
worker-only `modules/EchoMind/secretary/remote_planner.py` sends bounded raw input,
clock and workflow data through the existing paired Client. Router, AgentBrain,
legacy parser, orchestration and both repair entry points stop before company
prompt construction or direct provider calls. Server failure has no provider
fallback. Personal OpenAI requires the user's own Secretary prompt. Legacy prompt
builders remain dormant migration authorities, not company request payloads.

Client validates correlated protocol/UUID/phase, local module/action allowlists,
workflow steps and confirmation before execution. The execution repair loop now
recomputes confirmation from the repaired proposal instead of retaining permission
for an earlier action. Execution-error repair is deferred by the GUI host to its
existing worker; validated repaired proposals resume locally with bounded attempts
and fresh confirmation. Two additional guards failed before this continuation. Shared Client.open preserves Secretary HTTP status for safe
user-facing authentication/update/busy errors. CommandBus/MCP execution stays local.

Fail-before evidence covered missing transport, reused confirmation and lost HTTP
401 classification. Final focused Secretary/server/loopback transport selection:
121 passed, 1 pre-existing quarantined legacy browser-document xfail, exit 0.
Client guards are `tests/code/echomind/test_secretary_remote_planner.py` (16 cases).
No live clinical database is used by these new guards.

Independent real calls from this workstation using the established private Razi
pairing succeeded: route 2.54 s, plan 2.88 s, repair 2.91 s. Planning and repair
returned the expected date and server source. Correlation and proposal validation
passed; no proposal was dispatched. Data-free receipt:
`generated-files/eagle-eye/echomind-20260930/secretary-client-recheck.json`.

Seven owned EchoMind Secretary source files match their plugin payload mirrors.
Full mirror verification checks 497 pairs and reports one unrelated in-progress
`viewer_chat/ai_chat_pages.py` mismatch; this slice did not overwrite that work.
Client shared transport and `PacsClient/pacs/workstation_ui/home_ui/secretary_button_widget.py` are included through the existing base payload. Next Client
edition/build candidates must include remote_planner.py and these six updated
Secretary files; no installer, version change or full release is claimed.

GUI gates are separate. Human confirmed a fresh source launch. Native Computer Use
opened EchoMind, acknowledged the informational validated-center dialog, opened
the F12 Secretary panel at Ready, and hid it without recording or changing the
active study. No screenshots or patient identifiers were saved to this receipt.
End-to-end Secretary execution/confirmation remains pending: documented local
Test Control ping failed; read-only source process inspection found
AIPACS_TEST_SERVER=0. Human bootstrap with -TestServer and Home ready was requested.
No source restart, authentication automation, installed executable launch, client
credential modification or Razi client deployment was performed by this owner.

## SERVER RECEIPT

Implemented and activated on the existing Razi Developer TLS listener, port
8002. The headless service returns the agreed protocol/request_id/phase/route/plan
envelope for all three phases. Route always has plan:null; repair always includes
route. Unsupported input returns safe HTTP 422. Explicit unknown intent becomes
a nonexecuting unknown clarification plan. Workflows are limited to 20 steps.
client_time requires an explicit UTC offset; relative date context is computed
from that client-local date. Repair requires invalid_plan and bounded attempts.
Repair data is rejected for other phases. Request body limit is 128 KiB.

Changed server source: modules/ai_imaging/eagle_eye_remote/server.py and the new
secretary package below it. Server-owned assets retain canonical router v2,
phase-2 prompt/prefix, catalog and module documents. Pure validator/contracts/
errors snapshots live under secretary/validation with provenance hashes. The
service never imports the client brain/router/remote_planner/orchestrator,
CommandBus, GUI or clinical database. It uses the existing request-local
EchoMind core company gateway; model selection is server configuration. No
client prompt/key/provider/model/catalog/destination is accepted.

The service shares EchoMind global/per-client admission slots, rejects duplicate
request UUIDs, and persists request/response with authenticated owner in private
user_data/secretary/remote_history/history.sqlite3. Current Razi configuration
selects D:/Eagle Eye Server/user_data/secretary/remote_history and server model
gpt-5.2. ACL grants only Administrators, SYSTEM and LocalService. No body, prompt,
provider exception or credential enters this receipt or ordinary HTTP logs.

Verification: guards failed before the missing server implementation. Final
local server/client/history/listener selection passed 38 tests; server/history/
listener tests passed 30 on the target. Existing listener authentication returned
401 before Secretary processing; schema, unsupported module/action, confirmation,
unknown clarification, workflow, repair, retry/clock bounds, shared admission and
duplicate protection were exercised with synthetic data.

Actual integration used modules.EchoMind.secretary.remote_planner.request through
the paired Razi Client: route (4.41 seconds), plan (8.23 seconds), repair (6.19
seconds). All returned the same request ID and valid homepage/list_patients
proposal; all three persisted succeeded responses on the server. No command was
executed. Receipt: generated-files/eagle-eye/echomind-20260930/secretary-live-recheck.json.
Run the same safe procedure with synthetic text, language=en, phase=route then
plan; repair supplies modules=['homepage'], a synthetic invalid_plan and
validation_errors. Never execute the proposal during transport qualification.

Target rollout: only this server-owned delta was copied into the active
20260930-echomind Developer source; no client Secretary or unrelated UI changes
were deployed. Prior server.py/config are retained in
D:/Eagle Eye Server/backups/secretary-20260930. Idle checks found no active model
jobs or established inbound 8002 requests before Restart-Service AIPacsEagleEye.
PACS/CRM and installed executables were not replaced. Rollback restores the
backed-up server.py and server-config.json, then restarts only AIPacsEagleEye;
preserve all new private history records.

Acceptance boundary: paired API/planning/storage passed; source GUI execution,
identity/confirmation/MCP workflow acceptance remains with the client owner and
is not claimed. No installer/release was requested or built. Build handoff must
include the new server package's non-Python prompt/catalog/module assets and
validation snapshots in the Server edition, while retaining client-only local
execution and the personal OpenAI exception. Known independent long-prompt
core/source parity and shared-page mirror drift remain open.


### Established client configuration and safe real-call command

Use this existing private pairing configuration read-only; do not copy its
contents or replace config/eagle_eye_client.json:
`E:/ai-pacs/ai-pacs codes/ai-pacs beta version/generated-files/eagle-eye/deployment/razi-client.json`.
The tool-process override applies only to that isolated test process, never the
active GUI or normal launch flags:

```powershell
$env:AIPACS_EAGLE_EYE_CLIENT_CONFIG = (Resolve-Path 'generated-files/eagle-eye/deployment/razi-client.json').Path
@'
from modules.EchoMind.secretary.remote_planner import request
for phase in ('route', 'plan', 'repair'):
    fields = {}
    if phase == 'repair':
        fields = dict(modules=['homepage'], invalid_plan={'action':'unsupported_synthetic_action',
            'entities':{}, 'confidence':1.0, 'needs_confirmation':False, 'reason':'Synthetic invalid plan.'},
            validation_errors=[{'code':'INVALID_ACTION','message':'Action is not supported.'}])
    result = request(phase, "Show today's patient list.", language='en', **fields)
    assert result['route']['modules'] == ['homepage']
    assert result['plan'] is None if phase == 'route' else result['plan']['action'] == 'list_patients'
    print({'phase':phase, 'passed':True})
'@ | .\.venv\Scripts\python.exe -
```

These are proposals only. Do not call an orchestrator/executor or perform a
patient action in this transport probe. The client owner's one-line HTTP-error
classification addition in eagle_eye_remote/client.py is preserved; it was not
included in the server-only delta and is not needed for headless server dispatch.

### Joint transport confirmation

The client owner independently repeated the live route/plan/repair calls from
this workstation to Razi and reported success, about three seconds per phase,
with correct date/source in the proposals. No local commands were executed.
This independently confirms the shared transport acceptance; Secretary GUI
execution/confirmation remains an explicit separate pending gate.

### Latest compound-command diagnosis (2026-09-30)

Read-only inspection of the last local Secretary workflow and a bounded,
read-only Razi private-history query matched the input by a digest without
printing or copying the request text, patient identities or response bodies.
The server recorded a successful plan response (17.82 seconds) containing
`list_patients` followed by `select_patient` with `limit: 1`. The local trace
contained the same actions: listing succeeded and verified; selection returned
success but failed its verification. No `open_patient` step was present.

The captured input contained a display verb and a first-item reference, not an
explicit open verb. This does not prove whether transcription altered the spoken
request; audio comparison has not been performed. Server planning interpreted the
second intent as row selection. Separately, workflow._default_verify currently
requires thumbnails_loaded for select_patient, while executor._select_patient
checks rows and does not open a patient or load thumbnails. This mismatch explains
the VERIFY_FAILED after successful row selection. The observed outcome is not a
transport failure. Fix work must distinguish ordinal open/display intent from
checkbox selection and align verification with the action contract. No runtime
fix, clinical replay, service restart or new provider request was performed for
this diagnosis.


### Compound-command client correction (2026-09-30)

Status: guarded client correction; source GUI and installed-artifact acceptance pending.
The server owner is staging the corresponding prompt/snapshot/model evaluation separately.
Company planning remains server-only; no client provider route or fallback was added.

- `open_patient.entities.row_index` is a strict integer, 1-based, 1..10000,
  exclusive with `patient_code` and `resolved_patient`. Confirmation stays mandatory.
- Ordinals resolve against a preceding locally captured ordered list and its source.
  A failed replacement search invalidates ordinal context. Missing/empty/out-of-range
  lists, changed sources, missing identity and stale/ambiguous current identity fail closed.
  Sorting cannot silently change the captured patient/study target.
- Local dispatch uses the captured patient ID and StudyInstanceUID. Workflow verification
  for ordinal opening checks both against the active tab, not merely the patient ID.
- Checkbox selection verifies a positive returned selection count. It no longer waits
  for thumbnails (selection does not open a study), and an empty selection fails.

Evidence: initial new guards failed 6 cases before implementation (13 passed).
An additional wrong-study verification guard failed before its focused correction.
After changes, 93 tests passed, exit 0, across ordinal-open (26), workflow, remote
planner, bus bridge and server guards. All fixtures are synthetic; no live database
or patient data was used. The three modified Secretary Python payload mirrors were
synchronized through `tools/dev/sync_plugin_mirrors.py::add_paths`.

The documented Test Control ping failed with QLocalSocket Invalid name. No app was
launched/restarted, no authentication automated, and no patient action executed.
The human was asked to launch/sign in to one fresh source test session outside
clinical work. Live list/open/confirmation/rendered-identity acceptance remains pending.
Client profile inclusion applies to Standard/ARM PyInstaller and Nuitka through the
existing EchoMind payload. Server prompt/validator ownership remains server-side;
no full build, release, service deployment or live model switch was performed here.
Rollback is limited to this correction's hunks in executor/validator/workflow and
matching payloads, coordinated with server ordinal-contract support; preserve the
separate company server-only routing migration and all unrelated worktree changes.


Client follow-up review: single-action ordinal confirmation previously appended a
conflicting `resolved_patient`; its failing round-trip guard now passes after
preserving the ordinal selector. The combined suite now passes 96 tests (including
server-owner additions). Four client mirrors (including orchestrator) are aligned.
Global mirror verification still detects one pre-existing shared `ai_chat_pages.py`
drift out of 497 pairs. The distribution-profile suite reports 19 passes and three
failures at that same unrelated renderer parity assertion (all editions); this is
not a full build-input pass. No unrelated page payload was synchronized.


### Ordinal server candidate and model comparison (2026-09-30)

Server candidate accepts strict integer open_patient.entities.row_index 1..10000,
exclusive with patient_code/resolved_patient. It preserves opening confirmation.
Module documents distinguish displaying a study from checkbox selection and
require list_patients then open_patient for compound list/display intent. Pure
validation is resnapshotted from the coordinated client validator; no client
executor is imported. A deterministic gate returns nonexecuting unknown if an
ordinal open lacks a preceding list in that proposed workflow; changing source
invalidates that preceding-list premise. Client still resolves and rechecks the
actual ordered list, source, patient and study identity before execution.

Fail-before: ordinal compound rejected with HTTP 422; after fix accepted with
confirmation. Two missing-list guards failed before the deterministic gate.
Final focused server/history suite: 33 passed, direct pytest exit 0. Source GUI
execution is pending with the client owner; no service deployment is claimed.

Bounded synthetic benchmark ran only on Razi in an isolated Secretary process,
using the existing server-owned company configuration, candidate prompt/catalog
and private staging history. No clinical data or local command execution was
used. The active listener, live model and settings were unchanged. Provider model
listing returned HTTP 404; actual successful completions confirmed the three
aliases work through the current gateway. No automatic provider/model fallback.

| Requested model | Raw semantic cases | Mean paired route+plan | Repair | Repeated compound/selection |
|---|---|---|---|---|
| gpt-4.1-mini | 4/5 | 4.72 s | pass, 3.17 s | both pass, 3.18 / 3.29 s |
| gpt-5-mini | 5/5 | 15.42 s | pass, 8.90 s | not repeated |
| gpt-5.4-mini | 5/5 | 4.53 s | pass, 1.84 s | not repeated |

The strict initial grader scored 4.1-mini 3/5. Manual synthetic inspection found
its local-second-patient case semantically equivalent: set_source_mode(local),
list_patients(date), open_patient(row_index=2). Its genuine raw failure was an
ordinal open without a preceding list; the new deterministic gate clarifies
this instead. Do not represent that gate as improved raw model intelligence.
These small one-shot samples do not establish general reliability or clinical
acceptance. Requested alias is verified; the gateway's underlying exact model
snapshot and account tariff are not independently attested.

For the requested low-cost command planner, stage gpt-4.1-mini as the source
default and proposed Secretary config override. gpt-5.4-mini remains an explicit
higher-cost alternative if broader acceptance fails, never automatic fallback.
Live Razi still uses gpt-5.2 until a separately coordinated idle deployment.

Official OpenAI reference USD per million input/output tokens: 4.1-mini
0.40/1.60; 5-mini 0.25/2.00; 5.4-mini 0.75/4.50. These are not verified GapGPT
account rates or measured invoice cost. Input-heavy catalog prompts favor
5-mini's reference input price, but it was substantially slower here. Sources:
https://developers.openai.com/api/docs/models/gpt-4.1-mini
https://developers.openai.com/api/docs/models/gpt-5-mini
https://developers.openai.com/api/docs/models/gpt-5.4-mini

Staging root: D:/Eagle Eye Server/staging/history-20260930/ordinal-benchmark.
Local receipt: generated-files/eagle-eye/echomind-20260930/secretary-model-benchmark.json.
Rollback for a future rollout restores the prior Secretary source/config and
restarts only AIPacsEagleEye after idle checks, preserving private histories.
No installer or full plugin/build parity acceptance is claimed for this slice.


Joint final automated acceptance: 104 passed, exit 0, in the ordinal-open,
workflow, remote-planner, bus-bridge, server and remote-history suites after the
staged model/default and deterministic server gate changes. Live GUI, live server
rollout and global build parity remain pending as described above.

Final joint server/history/client-ordinal automated check: 60 passed, direct pytest exit 0. GUI/deployment gates remain pending.


### Reopened GPT-5/GPT-6 selection (2026-09-30)

The human requested newer GPT-5/GPT-6 comparison; this supersedes the earlier
4.1-mini recommendation. Model/default/config deployment remains unapproved.
Live Razi configuration is still gpt-5.2; prior staged 4.1-mini source/default
and merge fragment are historical candidates, not the selected rollout.

Five support calls and 44 matched completions were run on Razi only (49 total).
Supported returned aliases: openai/gpt-5.6-luna, openai/gpt-6-luna,
openai/gpt-6-sol, plus the prior openai/gpt-4.1-mini baseline. gpt-6.1-sol failed
two minimal probes before a usable response; no reliable status was obtained.
It is excluded as an integration/support failure, not scored for accuracy.
No provider fallback was used. No clinical input, GUI action or command execution.

All candidates used the same frozen staged server prompts/catalog. Each had one
compound route and ten plan/repair cases: English/Persian first-row display,
checkbox-only selection, local MRI second-row opening, explicit do-not-open,
missing list, ambiguous patient, opening plus Eagle AI, and two repairs.
New models explicitly used low effort and omitted temperature through an isolated
transport shim; baseline used temperature=0. Production core currently forwards
reasoning_effort only for personal OpenAI. Equivalent production use requires a
guarded server-owned effort setting and company-payload compatibility change,
including appropriate token/temperature handling. That patch is not implemented
or deployed by this research slice. No arbitrary client model/effort field.

| Model | Pre-gate strict pass | Normalized pass | Mean time | Reference USD for 11 calls |
|---|---|---|---|---|
| gpt-4.1-mini | 10/11 | 11/11 | 3.13 s | 0.03538760 |
| gpt-5.6-luna | 11/11 | 11/11 | 4.50 s | 0.02641504 |
| gpt-6-luna | 11/11 | 11/11 | 4.50 s | 0.01319672 |
| gpt-6-sol | 11/11 | 11/11 | 4.09 s | 0.25783440 |

Recommendation: gpt-6-luna with explicit server-owned low effort after the guarded
compatibility patch and source GUI acceptance. This sample found no semantic
advantage for Sol over Luna; it does not establish equal general intelligence.
No model switch, default change, config write or service restart was made during
this reopened comparison. Current staged/default model remains the old candidate.

Each new model reported 135634 input tokens: 39267 cached, 96334 cache-write,
33 uncached ordinary tokens. Output includes reasoning: 5.6-luna 1283 output/
385 reasoning; 6-luna 1518/607; 6-sol 908/24. Baseline input 135645 with 69760
cached, output 1286, no reasoning/write tokens. Do not double-charge reasoning
already included in completion tokens. Prompt warming/order is not randomized;
these totals are not cold-only costs or representative per-request production
prices. The long existing catalog accounts for substantial input usage.

Reference cost = ordinary_input * input_rate + cached_input * cached_rate +
cache_write * (1.25 * input_rate) + completion_including_reasoning * output_rate,
all divided by one million. New-model sums exactly match provider usage.cost.
The provider response exposes no separately verified invoice/currency contract;
matching reference arithmetic does not certify the actual account charge.
Official per-million input/cached/output: 5.6-luna 0.20/0.02/1.20;
6-luna 0.10/0.01/0.50; 6-sol 2.00/0.20/10.00. Cache-write premium verified at:
https://developers.openai.com/api/docs/models/gpt-5.6-luna
https://developers.openai.com/api/docs/models/gpt-6-luna
https://developers.openai.com/api/docs/models/gpt-6-sol

Evidence limitations: initial pre-gate grade combines action semantics and
explicit confirmation; full raw parsed completions were not retained. Stored
normalized synthetic responses were recovered from isolated staging history
for offline adjudication. All checkbox-only results use limit=1 (not unsupported
selection row_index); source-switch plus list was treated as equivalent. Client
owner independently reviewed the normalized cases. Do not reconstruct missing
raw fields or claim raw permission omission improved model semantics. Returned
model aliases do not independently attest an underlying dated snapshot.

Local evidence under generated-files/eagle-eye/echomind-20260930:
secretary_new_models_probe.py (executed frozen grader),
secretary-new-models-matched-receipt.json (usage/latency/strict scores),
secretary-new-models-synthetic-plans.json (synthetic normalized responses),
secretary-new-models-summary.json (cache-write-corrected costs/limits).
The source script stays unchanged for reproducibility. Future probes should
retain synthetic raw parsed completions, separate permission normalization from
semantics, and require selection limit=1; no extra paid replay for grader fixes.


### Independent workstation acceptance after model activation (2026-09-30)

The human explicitly authorized activating the selected GPT-6 Luna model.
Server owner completed a scoped model/effort rollout: `gpt-6-luna`, `low`.
Live prompt assets and validator remained unchanged; pending ordinal changes were
not bundled into this model-only activation. No client process was restarted.

The client owner independently executed authenticated route/plan/repair requests
from this workstation through `remote_planner.request` to the live Razi server.
All three passed, process exit 0: route 10.20 s, plan 17.51 s, repair 4.34 s.
The synthetic request explicitly forbade opening a patient. Responses validated
as homepage routing and list_patients proposals; no local command was executed.
Correlated UUID/timing receipt (no clinical content or credentials):
`generated-files/echomind/secretary-activation-acceptance.json`.
This confirms live client/server planning transport, not Secretary GUI execution
or acceptance of the separate pending ordinal/prompt/UI correction.


## Optional structured clarification (source contract, 2026-10-03)
An unknown plan may include clarification with exactly question (nonempty string, max 2000 characters) and options (1..3 items). Each item has exactly id (unique nonempty string, max 40) and label (nonempty string, max 240). No executable actions or consent fields are permitted. The client validates the shape and preserves it in NEEDS_CLARIFICATION results. Older text-only unknown plans remain supported. Selection submits original request/question/answer as quoted text in a new planning request, retaining session and mode. It never grants confirmation. Cancel sends no request. Active Razi deployment and actual-model/native GUI acceptance for this extension are pending.

Clarification activation update: Razi AIPacsEagleEye now uses 20261003-secretary-clarification on existing paired TLS port 8002. Four modes, settings ownership and a real synthetic choice proposal passed; no clinical commands executed. Client text-only fallback and answer-needed status passed offscreen tests. Fresh source GUI voice acceptance remains pending; see deploy-record-secretary-clarification-2026-10-03.md.
