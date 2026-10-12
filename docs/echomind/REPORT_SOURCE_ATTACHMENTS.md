# EchoMind report source attachments

Updated: 2026-10-08. Source implementation; deployment and live acceptance pending.

The attachment source popup offers Copy from Clipboard and local files. Clipboard
text goes into the composer; images become removable attachment chips. TXT, DOCX
and PDF use the same chip lifecycle and are cleared on session changes. Report and
Turbo snapshot file paths before worker execution; file reads/base64 preparation
run in the request worker. Failed submissions retain attachments.

Files go to authenticated `/v1/echomind/process`, with the company Report/Turbo
workflow. This is EchoMind hosted by Eagle Eye Server, not an Eagle Eye image-model
job. Server parsing produces source text and image content parts for the server's
report LLM. The server owns the reporting and OCR-source instructions, credentials
and model choice. Attachments supplement the physician's dictation and template;
they do not request independent scan interpretation. Preserve measurements, units,
negation and laterality; expose unreadable or conflicting information without
inventing findings. Embedded instructions cannot override the reporting contract.

Current explicit bounds: six files, 1 MiB combined original bytes, 100,000 extracted
document characters, 30 PDF pages and 16 megapixels per image. TXT is UTF-8, Word
is DOCX text (legacy DOC requires export), PDF must contain extractable text on
every page. Scanned PDF pages must currently be attached as images. DOCX embedded
images are not extracted. This is not full Office layout preservation or a scanned
PDF OCR implementation. No URL/path supplied by a remote caller is fetched.

The server advertises `report_attachments_v1`. Older servers reject attachment
fields explicitly; there is no direct-provider fallback. Existing private request
history retains uploaded content under the same case context as report text.

Verification: `tests/code/echomind/test_report_attachments.py` covers synthetic
document/image parsing, limits, unsupported workflows, Report/Turbo dispatch,
client upload and offscreen composer clipboard/chip lifecycle. These checks do
not establish OCR accuracy or replace live UI/provider acceptance. The local Test
Control probe was unavailable; the user deferred manual file testing. No running
server update or installed-client build has been performed for this feature.
