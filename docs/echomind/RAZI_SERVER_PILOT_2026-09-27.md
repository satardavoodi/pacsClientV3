# Razi text-only EchoMind server pilot

> Current routing change (2026-09-30): the owner selected Eagle Eye Server as
> the processing host. Read [Eagle Eye routing](EAGLE_EYE_SERVER_ROUTING_2026-09-30.md).
> The fixed PACS port-8000 route below describes the historical pilot, not the new
> client transport. Source, deployment and GUI acceptance remain separate gates.

## Implemented and activated scope

The owner authorized direct public-IP HTTP for this pilot on 2026-09-27.
The fixed origin is http://81.16.117.196:8000. HTTPS is not claimed.
The new RAZI_SERVER center is additive: the eight prior records, including TEST,
are unchanged. The existing Razi provider credential is retained only to preserve
client STT; the new pilot account's separate PACS password is encrypted under
its new access code with a distinct envelope binding. The private access-code
handoff is outside the repository. No saved workstation settings were changed.

Selecting this center routes report, Turbo, standardization, report/text translation,
correction, chat and breast assistance through remote_backend.py. Native image and
search/assistant routes are refused in this pilot. Template organization requiring
custom local system prompts is refused, not sent directly to the provider.

The client sends text, modality, selected template and structured study context.
It does not send its system prompt, model override, provider credential or audio
in report requests. STT still uses VoiceTranscriptionService and its existing
configured provider and credential behavior. Preserving STT means this pilot does
not remove every provider credential from the client package or memory.

The client authenticates a dedicated PACS pilot account in the worker and uses
its JWT for the request. The account has only generate_reports in its assigned
permissions and is not an administrator. This does not constitute an audit of
all legacy PACS route authorization. Redirects and environment proxies are disabled;
there is no automatic retry or fallback to direct LLM reporting. A public-IP probe
from this control PC does not prove reachability from every external network.

## Server state

The installed PACS executable was not replaced or restarted. A new pilot account
and two previously absent provider configuration files were added under the
installation's data/echomind directory, protected for Administrators/SYSTEM.
No patients or clinical reports were modified. Configuration is read per request.
The added files configure the authorized Razi provider, not another center.

The independent PACS Server checkout has an additive turbo_correction flag and
server-owned editing-frame construction, plus a capability advertisement. This
source change is NOT deployed. The installed server rejects that extra field;
Turbo Correction remains unavailable until a separately validated server update.
Ordinary Correction works now. No client prompt is sent as a workaround.

## Verification

- 228 focused client/edition guards passed (exit 0). 473 mirror pairs match.
- Focused client tests cover payload boundaries, gate adaptation, no fallback,
  timeout redaction, missing authentication, template association and old-center
  compatibility. The initial missing transport test failed before implementation.
- Real synthetic public-IP calls succeeded: report 4.5 s, Turbo 3.6 s,
  ordinary correction 2.1 s and Persian translation 2.6 s. Report and Turbo
  returned structured JSON. These are transport/workflow checks, not clinical QA.
- Server offline suite: 35 passed, including two tests failing before the
  Turbo Correction extension. No live call used patient content.
- Native source control ping failed; Settings activation, rendered GUI and Reception
  export have NOT passed live acceptance. Human source launch/sign-in is required.
- No installer, release or clinical report publication was performed.

## Use and rollback

In a freshly launched source Standard Workstation, open Settings > EchoMind >
Company Authentication and enter the private RAZI_SERVER access code, then
Authenticate. The label reports local route selection, not an online health pass.
Try synthetic text in Send and Turbo; inspect the returned report before testing
Reception export. Leave the current STT configuration unchanged.

To restore the old workstation path, re-enter its original center code. Do not
share the test code as a production license. To disable the server pilot, use the
prepared private rollback helper on Razi: it verifies ownership and new-file hashes,
disables only the pilot account and archives only the two newly created config files.
Server code edits and workstation source/mirrors can be reverted independently;
do not roll back unrelated worktree changes.

## Owner-selected access alias

Added the owner-supplied C-prefixed Razi access alias to the existing RAZI_SERVER
record. Every previous center and the original pilot alias remain unchanged. Each
registered alias has separate STT and server-login envelopes; a prefix alone never
authorizes access. The plaintext code is absent from source and documentation.
48 focused remote/credential/entitlement guards passed, including wrong-alias rejection.
A synthetic live Turbo call using the new alias returned structured JSON in 3.4 seconds.
Saved workstation settings were not changed. Native GUI acceptance remains pending.

## Assistant and Search through the central server (2026-09-29)

The pilot client now sends Assistant and Search text to the same authenticated
`/api/echomind/process` destination as Report, with `provider=aipacs` and the
matching `assistant` or `search` workflow. The existing server native dispatcher
owns the downstream reference endpoints. No new server workflow or deployment is
required by this client change. The earlier report/chat-only client guard blocked
both actions before transport; it now permits these two text workflows.

The desktop workers adapt the returned content to the existing Assistant/Search
renderers, preserving structured reference content and usage. No local session ID,
prompt, model, provider secret or image is sent. Empty reference text is rejected
explicitly instead of treating a local session ID as a remote session. There is no
direct-endpoint fallback or automatic retry. Original centers retain their routes;
STT and Turbo Correction are unchanged. Assist still uses its existing Send menu.

Four new guards failed before the fix (missing transport methods and the blocking
UI gate). All four passed afterward; two additional timeout guards enforce no
fallback. Client routing/adjacent/edition checks: 63 passed; server offline suite:
35 passed. Scoped mirror verification: 493 pairs match. The edition staging guard
also includes the remote adapter in the expected EchoMind payload.

Source GUI acceptance is pending: the documented test-control ping could not
connect. No application restart, installer build, server deployment or clinical
report publication was performed. Live synthetic transport results are recorded
separately below when available.

Live synthetic transport: both requests used a generic educational question with
no patient case. Assistant returned nonempty text through the central server in
96.8 seconds; Search returned nonempty text in 28.2 seconds. No response text or
credentials were printed or copied into fixtures. This proves authenticated
transport and nonempty responses, not reference accuracy or GUI rendering.
After including the adapter in the edition payload guard, all three edition
staging cases passed again. Final scoped diff checks and 493-pair mirror checks
passed. A fresh source GUI Assist -> Send -> Assistant/Search pass is still needed.


## Three-source Assist and Radiology Expert Web Search (2026-09-29)

The Assist Send menu now labels the existing assistant route Radiopaedia and
search route Textbook, with a third Web Search action. Web Search requires the
central-server account and sends only text, workflow=web_search, provider=company
and response_format=json to the existing authenticated process endpoint. It
never uses a client prompt, client model override, or direct-provider fallback.
The desktop renders answer text inertly and citation URLs as HTTPS links.

The separate PACS Server source now owns the original Radiology Expert plugin
instructions plus overriding research rules: mandatory search, trusted-source
citations, de-identified queries, no invented normal findings or image review,
and explicit uncertainty. GapGPT Responses uses gpt-5.6-sol, low reasoning,
store=false and required web_search with a medical-domain filter. Completed
search execution and trusted URL annotations are both required. The server
console also exposes the three named sources.

Verification: 66 workstation/edition tests passed; 46 server tests passed (three
new server guards failed before implementation). JavaScript syntax passed;
495 mirror pairs matched. A real synthetic call from the local server source
returned five cited sources in 19.5 seconds with clickable links. A prior minimal
capability probe confirmed this model in GapGPT's model list and a completed web
search tool call. No patient input was used or output content retained in docs.

This new workflow requires deploying the updated server source before the
installed central endpoint can accept it. No release, clinical server update,
or app restart was performed. Source GUI acceptance is pending; the documented
control endpoint was unavailable. Existing Turbo Correction gaps are unchanged.


## Assist composer and report consultation (2026-09-29)

Assist now exposes only Transcribe and Standard. Normal Template and Correction
remain available in Report, and programmatic attempts to enter those tabs from
Assist return to Transcribe. The Standard action uses standardize_assist on the
central server, preserving the reference-question prompt rather than using the
report standardization prompt or the old unsupported-search error.

Report response footers now include Medical Consult for newly generated and
restored reports, including the ChatGPT report path. It extracts the current
visible report text so manual edits are not replaced by stale raw JSON. The viewer
creates a fresh Assist conversation for the same study and sends that text through
Web Search. The original report page remains alive; Back to Report returns to it.
Consultation pages participate in existing teardown when changing mode or closing.
A concurrent consultation is not silently replaced while it is busy.

Three regression guards failed before implementation (two UI-contract checks and
the previously rejected reference-standardization route). Final verification:
78 workstation/edition tests and 47 server tests passed; 495 mirror pairs match.
All test content was synthetic; tests did not import clinical DB modules. Source
GUI acceptance and installation of the updated server remain pending. No clinical
consultation, restart, release or server deployment was performed for this change.


## Conversation backgrounds (2026-09-29)

Report uses navy (#10263b), Assist uses teal (#10332e), ChatGPT uses purple (#2d203e), and Chat uses slate (#282c32). Scoped selectors tint only conversation surfaces; message and control styling stays independent. An isolated offscreen Qt render verified the actual surface pixels for all four modes. All three edition staging guards passed and 495 mirror pairs matched. This is not a live source-app GUI acceptance pass.


## Visual refinement (2026-09-30)

Refined conversation tones to navy #101e2c, teal #102723, violet #201a30 and slate #191f28. Added an explicit EchoMind/mode heading, reduced sidebar width to 238 px, normalized sidebar spacing, introduced flat rounded composer tabs, a mode-accented Send button, cooler message cards and clearer metadata typography. No transport or clinical/report content behavior changed. An isolated synthetic Qt preview was inspected; 73 metadata/layout/consultation/edition tests passed and 495 mirror pairs matched. Live source GUI acceptance remains pending because the documented control ping was unavailable. No application restart or deployment was performed.
