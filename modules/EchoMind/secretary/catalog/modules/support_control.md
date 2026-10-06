# Diagnostics and patient communication

Use only the active registry. All company planning remains on Eagle Eye Server.

| Action | Entities | Actual behavior |
| --- | --- | --- |
| open_support_issue | description: optional user-supplied text, max 4000 | Opens a local editable issue form. Use the user's transcribed description without invented details. Local consent and Send are required; opening never sends |
| support_issue_status | {} | Current form receipt state only. Received requires a website-issued issue UUID. Pending is unconfirmed delivery |
| collect_support_diagnostics | include_windows_events: bool, default false | Starts bounded worker collection of four fixed logs; returns no raw text. Optional Windows Application candidates from last 24 hours |
| support_operation_status | operation_id | Polls collected evidence, source coverage and failures |
| get_visible_app_errors | {} | Visible Qt warning/critical dialog severities, no private message text |
| get_recent_function_results | {} | Last 100 function acceptance/failure results in this process; poll separately for worker completion |
| get_control_capabilities | {} | Actual registered actions, entity schemas, assistant permissions and deterministic digest; not proof of live prerequisites |
| prepare_patient_comment | study_uid, comment (max 4000) | Creates an active-study-bound draft, not local Note |
| sync_patient_comment | draft_id | Requires confirmation, uses existing Comment Sync cache/REST endpoint, preserves report status |
| patient_comment_status | operation_id | Delivered only after server acknowledgment; unknown transport outcomes are not success |
| prepare_patient_voice | study_uid | Prepares one app-owned recording path on worker, returns recording_id |
| start_patient_voice | recording_id | Starts existing inline capture after preparation succeeded; rejects busy microphone |
| pause_patient_voice / resume_patient_voice | recording_id | Explicit states, no blind toggle |
| stop_patient_voice | recording_id | Stops and saves using existing background WAV writer |
| patient_voice_status | recording_id | Saved requires actual WAV completion receipt; poll preparation/save/upload |
| send_patient_voice | recording_id | Requires confirmation; uploads only this completed take to study PACS attachments |

Get authoritative active-tab study identity before preparation. Recheck it at
execution; never join patients by name. Comment Sync is reception-bound; Local
Note is private. Existing transcribe_voice opens the report transcription path;
this module does not automatically extract or forward that transcript. User
reviewed transcript text can be passed as comment to prepare_patient_comment.

Voice PACS upload is not a verified reception delivery receipt. Its result
explicitly reports reception_delivery_confirmed=false. Never say reception
received voice on that basis. Do not expose paths or arbitrary file selection.

Log evidence is a bounded tail, not a precise retrospective time window.
Windows candidates have basename-only attribution and unverified source Python
events are excluded; candidates do not prove this source session crashed.
Visible severity is not message understanding. Explain observations in ordinary
language; do not invent root causes, ticket submission or reference numbers.

Help Ticket lifecycle: prepare_help_ticket opens a reviewed draft, submit_help_ticket requires local review and normal server-write confirmation, help_ticket_status polls packaging and validated delivery. Never pass file paths or upload URLs. The reviewed ZIP includes request, diagnostics, selected logs and retained voice; website receipt confirms delivery. get_loaded_study_summary returns scoped loaded-row aggregates, not all admissions. get_tutorial_catalog lists actual targets; show_tutorial(tutorial_id) highlights only a visible verified Home target without activating it.
