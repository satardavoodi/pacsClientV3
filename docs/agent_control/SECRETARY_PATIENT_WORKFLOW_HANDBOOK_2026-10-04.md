# Secretary patient workflow handbook

## Authorities and mode boundaries

Eagle Eye owns company prompts and planning; the workstation owns verified shared CommandBus actions, current case identity, permissions and GUI execution. Actual get_control_capabilities schemas define executable availability. Server module documents explain meaning; they cannot invent installed controls. This handbook complements the existing module catalog rather than introducing a second brain.

| Intent | Facts and workflow | Completion boundary |
| --- | --- | --- |
| Ask: MRI voice/report workload | get_loaded_study_summary supplies loaded-row groups by validated date and modality, voice present/absent/unknown and actual report status | Counts cover primary studies of displayed rows; not all daily admissions or personal voice authorship |
| Act: first patient without voice | read_patients returns original row_index and list_id; choose exactly absent; open_patient uses required_voice_presence=absent | Client rechecks current ordered identity and voice evidence; stale/unknown/changed evidence rejects opening |
| Guide: report/voice indicators | get_tutorial_catalog supplies workflow_guide and offered tutorial IDs | Text guidance is distinct from a successful visible tutorial overlay |
| Home filtering | advanced_search_patients, then poll read_patients; use explicit source and client-local calendar date | Searching is not ready; truncated rows cannot establish full counts |
| Settings modality visibility | Existing typed Settings controls and operation status | Changing Modality Grid differs from filtering the current patient list |
| Voice delivery | Existing study-bound recording, stop/WAV receipt, confirmed upload and reception status | Local WAV, PACS upload and reception delivery are distinct |
| Download / media | Existing selection receipt, download status and media operation status | Queued is not downloaded; opening CD preparation is not burning |
| Help Ticket | Existing reviewed draft / retry / status and received delivery receipt | Prepared or pending is not received |

## Patient workflow facts

read_patients and Home rows now expose report_status, voice_presence, server_audio_count, voice_evidence, voice_author_known=false, local_artifacts, original row_index/list_id and workflow_scope. get_loaded_study_summary exposes privacy-preserving aggregate workflow_groups and workflow_guide. Groups are capped at 200 with a truncation flag. Missing dates and fields remain unknown.

Server audio evidence comes from the existing person/study-bound authenticated workflow snapshot, cached on the corresponding Qt row. It expires after 60 seconds and is invalid after source/search/session binding changes. The receiver refreshes visible rows at most every 30 seconds. Only visible subscribed rows receive fresh server evidence; unobserved rows remain unknown. No synchronous network, database or file scan is added to GUI extraction. Positive fresh local voice cache establishes local availability, but local absence never proves server absence.

A displayed patient row can merge studies. Workflow facts describe its primary study; count displayed rows explicitly rather than pretending every study or admission is represented. Ordered-list handles bind identity/order/source; the required_voice_presence guard separately rechecks changing voice state at opening. Memory formatting retains original rows, study identity and observed report/voice state, and labels personal authorship unavailable. Always re-read old memory before acting.

## Verified indicator meanings

Completed reports use emerald double-check, or a green reporting-physician name where available. Physician approval and secretary approval use check-circle and are not necessarily completed. Pending uses clock; awaiting physician/secretary approval uses the corresponding person icon; archived uses archive. The Report tooltip is the status explanation. A red microphone indicates local voice; a blue microphone indicates server audio. Neither identifies its author or proves reception delivery. Download, assignment, voice and final report are separate dimensions.

## Remaining source and live gaps

The PACS workflow_state response currently provides audio_count, assignment and report_status, without authenticated voice-author identity. Attachment uploaded_by is client-supplied metadata and may be unknown; it is not sufficient to certify who dictated. Personal counts and complete center-wide daily workload require an authenticated, scoped upstream aggregate with distinct person/admission/study linkage and explicit author evidence. No clinical PACS server was changed by this slice. Do not synthesize personal counts from assignment or display names.

The current Eagle Eye accepts new Ask/Guide context: two authenticated synthetic requests answered the workload and indicator questions correctly, including unknowns and unavailable authorship. Updated canonical server prompts/catalog/validator are prepared in source; this turn did not activate a new deployed server revision. Voice-conditioned Act planning needs the matching server validator update. Native workstation control remains unavailable; offscreen Qt tests are separate from native acceptance.

## Verification

Two aggregate/guide guards failed before implementation. Focused synthetic checks cover fresh/stale/wrong-person audio, local versus remote absence, actual Qt snapshots and source invalidation, original bound ordinal opening, changing voice-state rejection, summary privacy and source handbook consistency. No live patient database or real patient data is used in these guards.

Final focused code gate: 200 tests passed, exit 0. Eight owned Secretary mirrors match. Global verification reports only the pre-existing unrelated viewer_chat/ai_chat_pages.py drift; it was preserved. Native GUI and deployed voice-conditioned Act remain separate pending gates.
