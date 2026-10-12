# Secretary session reference sources

The Files button beside Memory/Cycle/New creates and opens
`User Data/echomind/secretary_sessions/<conversation UUID>/files` on a worker.
Each New or ten-cycle rollover gets a new UUID and folder; old files stay saved.
Only direct files in the active session folder are considered. Users finish
copying before sending a request. No recursive User Data/patient-directory scan.

Every company request (Act, Ask, Guide, Help Ticket and repair) snapshots current
sources, checks stable file size/time/identity, computes SHA-256, and transfers
the bounded bytes on the existing authenticated TLS Secretary planning request.
No new credentials, port, provider fallback or AI permission path is introduced.
Old servers fail explicitly before sending file content. Response extraction
receipts must acknowledge every supplied filename/hash in order.

## Supported material and limits

- JPEG/PNG: actual re-encoded image pixels to the server-owned multimodal model.
- PDF: extracted text plus rendered page images, including scanned pages.
- PPTX: slide text, tables and embedded pictures. Layout, animations and speaker
  notes are not rendered; charts/groups/media require PDF export.
- DOCX: text only; documents containing images require PDF or separate images.
- TXT: UTF-8. Legacy PPT, executables, archives and arbitrary paths are refused.

Maximum 12 files, 8 MiB total, 20 PDF pages/PPTX slides per file, 30 total units,
20 images, 80,000 extracted characters. Images are reduced to 1536 pixels on the
longest side. Oversize/unsupported material fails visibly rather than being
silently omitted. Office archives have 2,000-entry/32 MiB expansion bounds and
reject XML entities. Session folders reject links/junctions; no macros execute.
The transport is bounded inline data, not resumable bulk storage. The local
session folder retains originals; server private history retains receipts, not
raw copies. Extraction is repeated for each request to reflect changed files.

## Server, prompts and MCP

Eagle Eye owns extraction, prompt interpretation, inference and credentials.
Source files are quoted reference data, never instructions, permission or proof
that an action/search completed. Screen-control observations remain a separate
channel. A request-scoped ContextVar prevents concurrent users/requests from
sharing attachment parts. All Secretary output remains English.

Shared typed CommandBus actions are exposed by existing MCP action discovery:
`list_session_files`, `inspect_session_file` and `session_file_status`.
The first two return pending operation handles; workflow verification polls the
third. Inspection reads the actual selected content through Eagle Eye, not a
client-side AI route. Handles are scoped to current session and fail after New.
No generated filesystem paths, commands or arbitrary file reads are accepted.

Course authoring can use reference evidence to compose a text draft and existing
Education save/editor actions. This change does not import attachment images into
course slide media. Current research still requires actual available web/search
tools; source files alone do not establish internet results. Personal direct AI
mode is outside this company-server attachment transport.

## Verification and delivery

Synthetic guards: `tests/code/echomind/test_secretary_session_files.py` covers
session isolation, path rejection, exact content hashes, actual image content,
PPTX and scanned PDF extraction, all four modes, scoped context cleanup and
asynchronous MCP stale-session refusal. Initial three guards failed before source
implementation. Existing Secretary/server/conversation guards remain required.
Runtime mirrors and the headless Secretary snapshot manifest must be synchronized.
Native GUI acceptance and actual authenticated Razi execution are separate gates;
see the private parity/deployment receipt for this revision's measured results.
No release build is authorized or implied by source parity.
