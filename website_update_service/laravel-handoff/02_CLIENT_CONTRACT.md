# AI-PACS Update Client — EXACT HTTP CONTRACT (v1, 2026-07-16)

The AI-PACS workstation client is ALREADY SHIPPED. The website must serve this
contract byte-for-byte; the schema cannot be redesigned server-side. Client
source of truth (workstation repo, read-only for you):
`E:\ai-pacs\ai-pacs codes\ai-pacs beta version\modules\auto_update\` and
`aipacs_runtime.py` (`load_update_feed`, `resolve_update_artifact_source`).

## 1. Base URL and feed resolution

Each center configures ONE URL, e.g. `https://ai-pacs.com/updates/aipacs/stable`
(local: `http://localhost:8080/updates/aipacs/stable`).

- If the URL does NOT end in `.json`: client GETs `<url>/update_feed.json`;
  base for all relative paths = `<url>/`.
- If it DOES end in `.json`: that file is the feed; base = its directory.
- Multiple sources in the client act as mirrors (active first, then others).

## 2. Requests the client makes (GET only, no auth, no cookies)

| Step | URL | Timeout |
|---|---|---|
| Check | `<base>/update_feed.json` | 30 s |
| Manifest | `<base>/<core.delta.manifest_path>` (e.g. `core/manifest-3.5.4.json`) | 30 s |
| Blobs | `<base>/<core.delta.files_base><hh>/<sha256>.gz` (e.g. `files/ab/ab12….gz`) | 60 s, 3 retries |
| Fallback installer | `<base>/<core.artifact_path>` | 60 s |

- User-Agent: `AIPacs-Updater` (blob/installer downloads).
- Paths are percent-encoded by the client (spaces in installer names arrive as
  `%20`). No Range/HEAD requests — plain full GETs. HTTP and HTTPS both accepted.
- No auth: adding authentication to these GET endpoints breaks every client.

## 3. `update_feed.json` (the availability API)

```json
{
  "app_name": "AIPacs",            // REQUIRED — client REJECTS any other value
  "channel": "stable",
  "generated_at_utc": "2026-07-16T00:00:00+00:00",
  "core": {
    "module_id": "core_app",
    "title": "AIPacs Core",
    "release_version": "3.5.4",     // dotted numeric; update offered when installed < this
    "artifact_type": "installer",
    "artifact_path": "core/ai-pacs installer v3.5.4.exe",   // fallback path (may contain spaces)
    "sha256": "<sha256 of installer>",
    "size": 850000000,               // bytes; used for the delta-vs-installer decision
    "available": true,
    "required": false,               // true = client nags more visibly (still consent-gated)
    "min_version": "",
    "release_notes": "short text shown in the popup",
    "release_notes_path": "core/notes-3.5.4.md",
    "delta": {                       // ABSENT ⇒ client uses the full-installer path
      "manifest_path": "core/manifest-3.5.4.json",
      "manifest_sha256": "<sha256 of the manifest file bytes>",
      "files_base": "files/",
      "compression": "gzip"
    }
  },
  "components": []                   // optional-module packages (existing system)
}
```

## 4. `core/manifest-<version>.json`

Lists every file of the installed app (`AIPacs.exe` + `engine/**` + `Qss/**`)
with `path`, `size`, `sha256`, `stored_size`. **Byte fidelity is mandatory:** the
client hashes the EXACT response body and compares to `manifest_sha256`.
Therefore: serve VERBATIM — no minification, no template pass, no charset
re-encoding, no BOM, no newline translation, no transparent compression that
alters stored bytes.

## 5. Blob store `files/<hh>/<sha256>.gz`

- `<sha256>` = hash of the UNCOMPRESSED file content; `<hh>` = its first 2 hex
  chars. The payload is a gzip of the raw file.
- Content-addressed and immutable: a blob's content never changes; new releases
  only ADD new hashes. Safe to cache forever.
- The client downloads the raw `.gz` bytes itself and gunzips locally, so:
  - `Content-Type: application/octet-stream`
  - NEVER `Content-Encoding: gzip` (a proxy/CDN "helpfully" decoding or
    re-encoding the body corrupts the hash check),
  - disable server gzip/brotli for `*.gz` (already compressed),
  - large bodies must stream fine (single blobs can exceed 100–200 MB).

## 6. Required response behavior (summary)

| Path | Content-Type | Cache-Control |
|---|---|---|
| `update_feed.json` | application/json | `no-cache, max-age=60` (going live = the release moment) |
| `core/manifest-*.json` | application/json | `max-age=300` |
| `core/notes-*.md` | text/markdown | `max-age=300` |
| `core/*.exe` | application/octet-stream | `max-age=31536000` (versioned filename) |
| `files/**/*.gz` | application/octet-stream | `public, max-age=31536000, immutable` |

`404` on a missing blob/manifest simply fails that update attempt client-side
(logged, retried on next check) — never substitute an HTML error page body
with a 200 status (hash check would fail with a confusing error).

## 7. Publish ordering (operational rule)

Upload `files/` and `core/` artifacts FIRST, `update_feed.json` LAST — the feed
going live is the moment every client sees the release, so everything it
references must already exist. The workstation build machine produces the whole
tree; `tools/build/publish_update.py --site-root <web root>` merges it in
(creates `<web root>/updates/aipacs/<channel>/…`).

## 8. Verification data

A sample feed is in this folder (`sample_update_feed.json`). For an end-to-end
local test the workstation repo can generate a REAL release tree:
`python "tools/build/generate_update_manifest.py" --stage-dir <staged tree> --version 99.0.0 --updates-root <tmp>`
then `publish_update.py --site-root <laravel public root>`.
