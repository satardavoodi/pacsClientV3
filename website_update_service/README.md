# AI-PACS Update Service — Website Structure

This folder is the deployable template for hosting AI-PACS updates on any
website. It is **pure static files** — no server code, no database. Any host
that can serve files over **HTTPS** works: the ai-pacs.com hosting, a WordPress
site (as a plain subfolder next to `wp-content/`), a second mirror site, or a
LAN file share for offline centers.

Design + client behavior: `docs/plans/architecture/AUTO_UPDATE_SYSTEM_2026-07-16.md`.

## Directory layout (per app + channel)

```
<site root>/updates/aipacs/stable/
    update_feed.json                  ← the availability API (clients poll this)
    core/
        manifest-<version>.json       ← file-level manifest (path, size, sha256)
        notes-<version>.md            ← release notes (optional)
        ai-pacs installer v<version>.exe   ← full installer (fallback path)
        SHA256.txt / SHA256_FA.txt / INSTALL_NOTES*.txt
    modules/
        module_package_feed.json      ← optional-module packages (existing system)
        <module zips / dirs>
    files/
        <hh>/<sha256>.gz              ← content-addressed store: gzip blobs named
                                        by the SHA-256 of their UNCOMPRESSED bytes.
                                        Grows across releases; only NEW hashes are
                                        ever added. Old releases keep working.
```

`update_feed.json` doubles as the "update availability API": the client
compares its installed version with `core.release_version`. `required: true`
marks a mandatory release (the client nags more visibly; it still never
installs without user consent).

## Publishing a release (from the build machine)

1. Build as usual — `builder/build_release.py` produces the delta artifacts
   under `builder/output/updates/` (manifest + `files/` store + feed with the
   `delta` block). Kill switch: `AIPACS_UPDATE_DELTA_PUBLISH=0`.

2. **Automatic INCREMENTAL remote publish (recommended).** Copy
   `builder/publish_targets.template.json` → `builder/publish_targets.json`
   (GITIGNORED — credentials stay on the build machine) and fill in each
   site's FTP/FTPS host, username, password and web root. Then either:
   - set `"auto": true` on a target → every successful release build
     publishes there automatically (kill switch
     `AIPACS_UPDATE_REMOTE_PUBLISH=0`), or
   - run it manually:

     ```
     python "tools/build/publish_update.py" --target ai-pacs-com --target mirror-site
     python "tools/build/publish_update.py" --all-targets --dry-run   # preview
     ```

   The publisher lists the server's content-addressed store first and uploads
   ONLY the blobs of this release that the server does not already have —
   unchanged DLLs are never re-transferred (a typical release = tens of MB,
   not 2 GB). Order is safety-enforced: blobs → manifest/notes → modules →
   `update_feed.json` LAST, then the feed is downloaded back and byte-verified.
   The ~600 MB full installer is NOT uploaded unless the target sets
   `"with_installer": true` or you pass `--with-installer` (upload it at least
   once so the fallback path works).

3. Legacy folder mode (local Laragon site / staging a mirror by hand):

   ```
   python "tools/build/publish_update.py" --site-root "D:\laragon-www\ai-pacs\public_html"
   ```

   If you upload manually afterwards, keep the order: `files/` and
   `core/manifest-*.json` FIRST, `update_feed.json` LAST.

## Hosting notes

- **HTTPS is required** (client downloads are hash-verified, but transport
  should still be TLS).
- Ensure the host serves `.json` (application/json), `.gz` (raw bytes — it
  must NOT be transparently re-encoded), `.md`, and `.exe`. On Apache/WordPress
  hosting, the included `.htaccess` covers this; on IIS use the included
  `web.config`.
- The `files/` store grows over time. It is safe to prune blobs no longer
  referenced by any manifest you still serve — keep at least the manifests of
  the versions centers may still be running from.
- WordPress: do NOT upload through the media library (it renames files).
  Upload the `updates/` folder verbatim via FTP/file manager next to
  `wp-content/`, e.g. `https://ai-pacs.com/updates/aipacs/stable/update_feed.json`.

## Client configuration (per center, once)

In AI-PACS: **Settings → Installation & Modules → Update Source** — set the
update URL, e.g. `https://ai-pacs.com/updates/aipacs/stable`. Extra sources in
`update_sources.json` act as mirrors — the client tries the active source
first, then the others:

```json
{
  "app_name": "AIPacs",
  "active_source_id": "primary",
  "auto_check_on_startup": true,
  "sources": [
    {"id": "primary", "title": "AI-PACS Website", "type": "url",
     "location": "https://ai-pacs.com/updates/aipacs/stable", "channel": "stable"},
    {"id": "mirror",  "title": "Mirror",          "type": "url",
     "location": "https://<second-site>/updates/aipacs/stable", "channel": "stable"}
  ]
}
```

Offline/LAN centers can instead use a `type: "file"` source pointing at a
network share that carries the same folder layout.

## Security model

- Every downloaded file is verified against its SHA-256 from the manifest;
  the manifest itself is verified against `manifest_sha256` in the feed.
- Transport security = HTTPS. (Staged, not yet implemented: detached Ed25519
  signature on the feed for defense against a compromised host.)
- Nothing in this tree contains center data; the payload is the sanitized
  build (the release gate blocks center IPs/secrets from ever shipping).
