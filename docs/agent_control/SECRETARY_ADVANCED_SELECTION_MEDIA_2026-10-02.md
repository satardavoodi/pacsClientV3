# Secretary advanced filters, exact selection and media control

Source implementation receipt, 2026-10-02. Not deployed or live accepted.

## Existing Advanced Search route

`advanced_search_patients` bypasses the old Secretary list executor and uses the existing Home Advanced Search handler behind the Patient-ID filter icon. It supports body_part, age_min/age_max, modality, YYYYMMDD dates, patient IDs/name and explicit Local/Server source. Age and date bounds are validated. Structured advanced fields reach the existing source-aware search service; no duplicate medical database query implementation was introduced. The previous protective UNSUPPORTED_ANATOMY_FILTER rejection is superseded by this real connection. Local/server routing, paging and existing matching semantics remain owned by Advanced Search. The basic controls are not a second authoritative copy of the advanced query.

Read back with `read_patients`: searching/ready status, bounded visible rows, total observed count, and list_id hashing ordered patient/study identities and source. Empty results remain empty, never a successful match claim.

## Multiple studies and downstream actions

`select_patients` accepts exactly one of study_uids, patient_ids or one-based row_indices. Ordinals require a preceding observed list and its list_id. Reordered lists and absent/duplicate identities fail before changing checkboxes. Ambiguous patient IDs spanning several visible studies require exact study identities. The selected checkboxes are read back and compared with the intended UID set. The action returns a selection_id for the actual selection; changes to source or selected UID set invalidate it. Receipts are bounded to the latest selection in this adapter.

`selection_status` verifies the receipt. `download_selection` submits the exact selected records through the existing Home download path; state queued is not completion. `download_selection_status` reads the existing in-memory download store and reports all-completed, running, or failed/cancelled without GUI-thread file checks. It does not initialize a new store to claim empty success. `film_selection` uses the existing Printing module with the selected rows, checks that a Printing tab exists, and reports navigation only. Physical film printing is still the module's configured workflow.

## CD/DVD and media folder

`media_drives` discovers existing optical drives on a worker and returns an operation_id; `media_status` polls it. `write_selection_media` requires explicit confirmation and a valid selection receipt. Burn mode requires an explicit discovered drive_id. Folder mode requires an absolute NEW directory with an existing parent. Existing directories are rejected on the worker, rather than overwritten. Optional disc_label, anonymize, report/images/attachments, original/uncompressed/lossless/jpeg2000 format, write speed, finalization and verification are typed; burn verification defaults on. `cancel_media` requests cancellation.

The adapter reuses CDBurnWorker/BurnOptions. It checks every selected study's available local DICOM content before output; one unavailable study fails the entire selection rather than exporting a partial patient list. Disk work, content collection and optical writing stay in the worker. COM initialization is explicit on the drive-discovery/burn thread. Sanitized status reports running/progress/succeeded/failed/cancelled; raw worker messages and patient paths are not returned as diagnostic status. include_viewer defaults on and resolves the saved viewer setting on the worker; unavailable viewer fails explicitly. The existing center identity is loaded locally, without accepting a generated executable path. Installed run_cd/printing gates are retained.

Running QThreads are retained, and an application quit/host-close request is intercepted while media is active: cancellation is requested and quit resumes on worker.finished, without blocking the GUI with wait(). Force termination and real IMAPI cancellation still require clean-host acceptance; no real disc was burned in this lap.

## Server and sequential contract

Client schemas, permissions, registered actions, server validator/catalog/contracts and source snapshot manifest were updated together. The server snapshot is source-only, not proof of a deployed Eagle Eye Server update. The existing test MCP bridge exposes home_selection_control and production Gateway tools enumerate the real bus actions. Runtime schema acknowledgement remains required.

Sequential workflows capture actual list_id, selection_id and operation_id. Advanced search waits for read_patients ready; subsequent ordinals use $list_id, downstream consumers use $selection_id. Download completion is polled before advancing. CD output is polled separately; bounded timeouts stop continuation without auto-resending physical writes. Never invent receipts or infer completion from successful submission.

## Verification and remaining acceptance

Two Advanced Search guards failed before the route was connected. Synthetic guards cover first/third exact selection, reordered-list rejection, stale selection, invalid ordinals, explicit CD confirmation/drive, missing selected local content before output, a verified search/select/download sequence, asynchronous quit deferral, saved viewer/center settings, and no overwrite of an existing output directory. Final affected suite including MCP entry-point guards: 102 passed, exit 0; separate permission guards: 11 passed, exit 0. Scope includes Home bus/capability/server/workflow plus existing Advanced Search routing/modality guards. Owned EchoMind mirrors and owned server assets were synchronized; unrelated ai_chat_pages.py mirror drift is preserved.

Live acceptance is pending: the owner's current source app predates these additions. A human-assisted fresh test-enabled launch/login was requested. No real patient download, Filming operation, media folder export or optical burn was done by the new actions. Need live Body Part/age filtering, exact first/third checkbox identity, queue completion, Printing tab selection, optical discovery and one approved synthetic/local media output. Real-disc capacity, write verification and cancellation need suitable blank media/hardware. No installer, release or server deployment was produced.


Additional gates: the existing MCP entry-point guard had a stale source assertion predating explicit confirmed propagation; it was updated to require both strict boolean validation and confirmed forwarding. The broad release-parity selection is not green: the known unrelated ai_chat_pages.py mirror drift and stale staged config/template parity still fail. Generated stage output was not modified or rebuilt. These are separate repository/release blockers, not proof of a new feature acceptance pass.
