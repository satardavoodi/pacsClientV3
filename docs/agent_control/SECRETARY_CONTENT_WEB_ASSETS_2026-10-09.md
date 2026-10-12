# Secretary conversational content and server web assets

## Scope

This slice implements end-user content requests from the OCD course session through the existing shared CommandBus/MCP. It does not redesign Education, add another MCP brain or change clinical viewer rendering.

Implemented: inspect saved course content; rename/reorder/insert slides; change presenter/title/text/safe rich text/layout/colors; preserve attached media; server public web search/read/download; server-configured image generation; checksum-verified session file delivery; image/PDF/cover/slide-thumbnail attachment; exact PACS study selection and complete series import with per-series thumbnails. Source attribution stays in private session receipts; the planner must also retain it in lecture notes/references. DICOM and patient identifiers stay on the existing clinical socket path.

## Execution and trust

`content_assets.py` schemas are shared by client/server validators and MCP discovery. `ContentAssetsAdapter` registers ten commands when a real Secretary session owner is available. All network/file/database work is on a worker. Status is conversation-scoped; queue acceptance is not success. Workflow verification binds actual completed digest/checksum/selection receipts, never fabricated paths or IDs. Writes require editable local courses and optimistic snapshot digests and respect unsaved editor state.

`POST /v1/secretary/assets` uses the existing authenticated, certificate-pinned Eagle Eye connection and server license gate. Request bodies are bounded at 32 KiB. Server company model/credentials/prompt own search and generation; no client-direct provider route or automatic fallback. Downloads use public HTTPS only, checked destination IPs pinned through TLS, redirect revalidation, verified PNG/JPEG or PDF signatures, an 8 MiB file limit and owner/session storage. Client independently checks bytes/hash/type and the existing 12-file/8 MiB session quota. No arbitrary write paths, shell code, login automation or executable downloads are exposed.

The optional browser performs a fresh headless session per page, routes HTTP through the same checked fetcher and blocks uploads, native downloads, service workers and WebSockets. Scripts are site code inside the browser sandbox; the only application evaluation is fixed DOM extraction. No generated code is executed. This is public research, not a general remote desktop or an authenticated website agent. Access-denied or unsupported dynamic pages fail honestly.

DICOM import is bounded to selected actual study UIDs, maximum five resources per slide, 10,000 instances per study, unambiguous nonnegative series numbers. Every downloaded header is checked against the selected patient/study/series plus unique SOP instances and exact counts. A mismatch prevents database attachment. Existing configured socket downloads are reused. Thumbnail decoding occurs on a worker using the existing Education renderer. Native drag-and-drop and clinical stability interpretation remain separate acceptance checks.

## Server administrator configuration

The existing server `secretary` configuration accepts:

```json
{
  "web_backend": "static_https",
  "web_browser_channel": "msedge",
  "image_model": null
}
```

Default static reading is usable without a new dependency. To select dynamic reading set web_backend to playwright in the staged server configuration and provide the optional runtime from `modules/ai_imaging/eagle_eye_remote/secretary/requirements-web-browser.txt` in its isolated deployment environment. The browser channel must be msedge, chrome or chromium. Edge/Chrome must already exist; do not install/overwrite a managed browser globally. Chromium requires its matching Playwright binary. Missing runtime fails explicitly. Image generation requires an administrator-selected `gpt-image-*` model supported by the existing company gateway. This session does not select a paid production model or change credentials.

Capabilities report backend, dynamic runtime availability, image configuration and limits. Driver presence does not prove browser binary launch, upstream provider availability or live acceptance. No source parity receipt implies activation.

References: [Playwright browsers](https://playwright.dev/python/docs/browsers), [network interception](https://playwright.dev/python/docs/network), [Images API](https://developers.openai.com/api/reference/resources/images).

## Typical workflow

1. Inspect the actual saved course and retain its slide IDs and digest.
2. Reorganize the full slide sequence while preserving all existing IDs; insert new slide entries without an ID. Use explicit presenter data from the physician.
3. For public visuals, search/read and choose an actual original image URL, then download or generate a conceptual visual. Await content_asset_status. Attach the delivered checksum with the latest course digest. Reinspect after changes. For PDFs, use the separate full-width resource.
4. For clinical cases, search exact patient codes, review returned studies, then import exact UIDs into the intended stable/unstable slide. Await all-series and thumbnail verification. Never infer stability or age from monitor photographs.
5. Use the existing load_course_draft and preview_course/open_course_editor tools to load fresh saved content. Existing PowerPoint import/conversion remains local; arbitrary video/audio creation and arbitrary binary downloads are outside this implementation.

## Verification and activation ledger

Fail-before: five new web contract tests failed because the service/schema did not exist. Focused guards cover public URL rejection, inert reads, original byte/provenance delivery, active content rejection, typed client/server validation, negotiated actual-result binding, MCP handler discovery, optional-browser capability honesty, authenticated/license-gated HTTP delivery, isolated course editing and DICOM incomplete/wrong-identity rejection. Tests use synthetic identifiers and isolated database fixtures.

Source checks, mirror parity and two-way Developer hash receipts are recorded in the protected task receipt. Live source GUI, real server browser launch, real company search/image generation, native DICOM drag-and-drop and activated client/server transport acceptance remain pending. Playwright was absent in the inspected Razi environment; no executing revision or runtime was modified. Build/release handoff remains blocked until required live gates pass. This is implementation evidence, not a claim of production availability.

Inactive user-auth candidate reconciliation (2026-10-09) found missing content
dependencies and four omitted existing EchoMind session/course mirrors. A bounded
256-file local/base/candidate audit records exact hashes and preserves Education
ownership separately. The existing headless Secretary snapshot guard failed on
stale validator/catalog hashes; refreshing its existing source entries and adding
the four web-content source receipts restored both packaging guards. No active
source or service was changed by this reconciliation. The protected supplement is
`generated-files/eagle-eye/windows-human-session-20261009/reconcile/secretary-overlay-manifest.json`;
full combined parity and activation remain separate gates.


Razi verification found Windows WinError 3 when a long temporary-root plus owner/session/hash filename exceeded the legacy path limit. Server asset storage now uses extended Windows paths without changing the registry or shortening identity hashes; the long-path guard and original-byte delivery verify this boundary. The first candidate and failure log are retained privately. Razi's wider builder checks also reported four pre-existing missing configuration-template failures under the declared configuration exclusion; these remain a build-readiness limitation, not a content-service pass. The combined local suite geometry failure passes when Education is run separately. Receipts distinguish these results.
