# Reception reports in Correction

2026-10-08: source implementation, live GUI acceptance pending.

Entering Correction refreshes chat reports and asynchronously loads the same
`ai_get_reception_reports` repository used by Reception Data / View Reports.
Saved HTML reports appear as `Reception report <id>` entries in Select Report.
The selection uses the existing Send and Turbo Correction functions and output
handling; it does not change or overwrite the reception report.

The loader requires a study UID. It accepts exact study matches and legacy rows
without a study UID only when the DICOM patient's exact patient ID matches. Rows
with a different study UID are excluded even if the patient ID matches. It never
queries all patients or matches by name. Up to 100 rows per scoped lookup are
loaded; duplicate text is collapsed. Alternative reception identifiers without
an authoritative mapping are not guessed. Reports not yet in the local View
Reports repository are not automatically fetched from the remote reception API.

HTML is converted to visible source text with paragraph and table-cell boundaries;
script/style content is excluded. The text is wrapped in a Report JSON field for
compatibility with the existing Correction output renderer. The original HTML
remains unchanged. Results arriving after a study/session change are discarded.

Synthetic guards cover identity filtering, text preservation, duplicate handling
and stale callbacks. The local Test Control endpoint was unavailable, so no live
workflow pass or installed-client update is claimed.

## Eagle Eye saved analysis sources

The same worker now loads exact-study saved Eagle Eye results through existing
`eagle_eye_saved_results` and `eagle_eye_remote.local_results` readers. The selector
labels sources EchoMind, Reception report, and Eagle Eye plus module title.
Preferred source is saved HTML, then a readable text PDF, with structured JSON
fallback for validated JSON-only remote artifacts. PDF extraction runs off-thread;
scanned/encrypted PDFs fail explicitly instead of yielding an empty report.
No analysis job is submitted. Source results remain unchanged. Imported results
carry AI-generated provenance and require physician review. Existing Correction
transport and rendering are reused. Failure of one source does not suppress the
other source; the selector displays a loading error. Remote-only results that
have not been retained locally are not fetched by this adapter.

Validation: 41 focused synthetic tests passed, including exact-study JSON-only
result discovery, HTML measurement/negation preservation, scanned PDF rejection,
reception identities and stale session callbacks. Live GUI acceptance remains
pending; no installed-client build or server deployment was performed.

## Server-owned Correction source parsing (supersedes client extraction above)

The dropdown now retains an opaque, versioned source envelope. Reception HTML
and saved Eagle Eye HTML/PDF/JSON bytes travel as `correction_source` to
`/v1/echomind/process`. The server advertises `correction_sources_v1`, validates
size/format and converts the source before calling the existing company
Correction function. Both normal and Turbo correction retain their server-owned
prompts. Only source selection, identity validation and bounded byte reads remain
client-owned. There is no image inference submission or direct company fallback.
Server parsing accepts JSON, HTML, UTF-8 TXT, DOCX and text PDF; 1 MiB source,
100,000 normalized characters and existing 30-page PDF bound. Scanned PDFs require
OCR and fail explicitly in this version. HTML scripts/styles are excluded; JSON
structure is retained. Source instructions cannot override the correction rules.

65 focused tests passed for original-byte transport, server normalization,
Correction/Turbo dispatch, invalid PDF pre-provider rejection and source identity.
These are source tests, not live provider or deployment acceptance. The running
Razi service still requires a scoped candidate deployment for these changes.
