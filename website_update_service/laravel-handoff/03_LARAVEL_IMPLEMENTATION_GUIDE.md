# Laravel Implementation Guide — AI-PACS Update Service (local Laragon first)

Target workspace: `D:\laragon-www` (WordPress site at `ai-pacs\public_html`,
local URL `http://localhost:8080`, live = Hostinger `ai-pacs.com` behind
Cloudflare). A Laravel 12 sub-app already exists at
`public_html/consult-form/laravel-back/` — mirror its integration pattern.

## Architecture decision (pick A unless told otherwise)

The client only needs static files (see `02_CLIENT_CONTRACT.md`). Laravel adds
value for publishing/administration, not for serving bytes.

**Option A — RECOMMENDED (hybrid):**
- The update tree is plain files under the web root:
  `public_html/updates/aipacs/stable/…`. Apache serves an existing directory
  BEFORE WordPress's rewrite rules, so `/updates/...` bypasses WP automatically.
  Drop in the provided `.htaccess` (this folder) for MIME/cache/no-re-encoding.
- A small Laravel app (new sibling, e.g. `public_html/updates-app/laravel-back/`,
  NOT inside consult-form) provides the OPTIONAL niceties:
  - `GET /updates-api/health` — checks the tree exists + feed parses,
  - `GET /updates-api/releases` — lists versions found in `core/manifest-*.json`,
  - Phase 2 (later): token-protected publish API (upload blobs/manifest, swap
    feed atomically) so releases can be pushed over HTTPS instead of FTP.
- Day-1 publishing = the workstation's `publish_update.py --site-root
  D:\laragon-www\ai-pacs\public_html` (it creates `updates/aipacs/stable/`).

**Option B — fully routed through Laravel:** every GET handled by a controller
streaming from `storage/app/updates/…`. More control, but you must get large-
file streaming right. If chosen:

```php
Route::get('/updates/aipacs/{channel}/{path}', UpdateFileController::class)
    ->where(['channel' => 'stable|beta', 'path' => '.*']);
```

```php
// UpdateFileController essentials
$full = realpath($base . '/' . $path);
abort_unless($full && str_starts_with($full, realpath($base)), 404); // no traversal
$mime = str_ends_with($path, '.json') ? 'application/json'
      : (str_ends_with($path, '.md') ? 'text/markdown' : 'application/octet-stream');
$cache = str_ends_with($path, 'update_feed.json') ? 'no-cache, max-age=60'
       : (str_contains($path, '/files/') ? 'public, max-age=31536000, immutable' : 'max-age=300');
return response()->file($full, ['Content-Type' => $mime, 'Cache-Control' => $cache]);
// response()->file → BinaryFileResponse (streams; no memory blow-up).
// Ensure PHP output_buffering/zlib.output_compression do NOT re-encode .gz,
// and php max_execution_time tolerates a multi-hundred-MB download.
```

## Hard requirements whatever you choose

1. Byte-verbatim responses (hash-verified by the client) — no minify/BOM/
   charset/newline transforms on `.json`, no `Content-Encoding: gzip` and no
   server gzip/brotli on `.gz`.
2. Correct MIME + Cache-Control per the table in `02_CLIENT_CONTRACT.md`.
3. Filenames with spaces (`core/ai-pacs installer v3.5.4.exe`) must resolve
   (requests arrive percent-encoded).
4. Anonymous GET (no auth/cookies/CSRF on the read path).
5. Never break the existing WordPress site or `/consult-form/`.

## Local (Laragon) bring-up

1. Create the tree: `public_html/updates/aipacs/stable/` and copy
   `sample_update_feed.json` in as `update_feed.json` (placeholder), plus the
   provided `.htaccess` into `updates/aipacs/stable/` (or the `updates/` root).
2. Restart Apache via Laragon if you add vhost-level config (folder-level
   .htaccess needs no restart; local Apache runs on port 8080).
3. Smoke tests (PowerShell):
   - `curl.exe -sI http://localhost:8080/updates/aipacs/stable/update_feed.json`
     → `200`, `Content-Type: application/json`, `Cache-Control: no-cache, max-age=60`
   - put any file at `files/ab/test.gz` →
     `curl.exe -sI .../files/ab/test.gz` → `application/octet-stream`,
     `immutable`, and NO `Content-Encoding: gzip` header.
   - `curl.exe -s .../update_feed.json | Get-FileHash` twice → identical
     (byte-stable responses).

## End-to-end acceptance (with the real workstation, on this PC)

1. On the workstation repo, generate a real release tree (any temp stage works;
   a real build's `builder/output/updates/` is better) and publish:
   `python "tools/build/publish_update.py" --site-root "D:\laragon-www\ai-pacs\public_html"`.
2. In the AI-PACS source build: Settings → Installation & Modules →
   Set Update URL → `http://localhost:8080/updates/aipacs/stable` → Check
   Updates: the release row must appear with the delta artifact.
3. Byte fidelity: `Get-FileHash` of the served `core/manifest-<v>.json`
   (downloaded via curl) must equal `delta.manifest_sha256` in the feed.
4. Feed-last rule respected by your publish/health tooling.

## Production notes (later phase — do NOT touch live now)

- Follow the workspace's Hostinger runbooks; upload `files/` + `core/` first,
  `update_feed.json` last. Second site = same tree (mirror).
- Cloudflare: add a Cache Rule for `/updates/*` honoring origin headers;
  ensure no Brotli/gzip transform is applied to `.gz`/`.exe` (octet-stream is
  normally left alone); the feed must not be cached beyond ~60 s.
- Large blobs (100–200 MB+) must stream through the proxy — verify one big
  blob end-to-end before announcing a release.
