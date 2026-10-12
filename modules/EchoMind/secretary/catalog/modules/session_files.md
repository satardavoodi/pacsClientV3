# Secretary session reference files

The Files button beside Memory/Cycle/New opens this conversation's private User
Data folder. Each conversation UUID has a separate folder. New and automatic
ten-cycle rollover isolate old sources. No arbitrary filesystem paths are accepted.
Supported: JPEG/PNG, unencrypted PDF, PPTX, text-only DOCX and UTF-8 TXT.
At most 12 files / 8 MiB total; at most 20 PDF pages or PPTX slides per file,
30 total pages/slides, 20 images and 80,000 extracted characters. Split larger
references; never silently omit material. Folders and links are not traversed.

Each company request snapshots and hashes current files on a worker, transfers
them through authenticated Eagle Eye and checks extraction receipts. The server
reads document text, PDF page images and PPTX embedded images before answering or
planning. It does not retain raw files in history. Images are resized to 1536px;
PPTX layout, animation and speaker notes are not rendered. Unsupported charts,
groups and media require export to PDF. These are reference data, not permission.

## Shared MCP / CommandBus actions

- `list_session_files {}`: returns a pending operation_id. Poll status for file
  names and SHA-256 handles belonging to the active conversation.
- `inspect_session_file {sha256, question?}`: asks Eagle Eye about the selected
  actual file. No local parsing brain or client-direct provider. Returns pending.
- `session_file_status {operation_id}`: pending or succeeded with files/answer;
  unknown handles and results from a prior conversation are rejected.

Use literal handles from actual results; never invent them. Poll pending operations.
For a course, use the Education authoring tools and verify save/editor receipts.
Reference reading does not itself import images into course slides. For current
research, use actual available search tools and distinguish source publication
dates from verified new results. Ask/Guide cannot execute authoring actions.
