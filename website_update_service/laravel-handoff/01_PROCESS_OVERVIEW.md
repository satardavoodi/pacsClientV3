# AI-PACS Automatic Update System — End-to-End Overview (for the website agent)

Read this first; then `02_CLIENT_CONTRACT.md` (the byte-level rules you must
satisfy) and `03_LARAVEL_IMPLEMENTATION_GUIDE.md` (how to build it here).

## Why this exists

AI-PACS is a clinical DICOM workstation installed at imaging centers. Until
now every release meant hand-carrying a ~1 GB installer to each center and
reinstalling. The workstation now ships an auto-updater (OPT-38, 2026-07-16):
it checks a website feed at startup, notifies the user, downloads ONLY the
files that changed, applies them with automatic rollback, and restarts.
**The website is the distribution server** — and it is deliberately dumb:
static files over HTTPS. No database, no dynamic logic is required for v1.

## The full pipeline

```
BUILD MACHINE (workstation repo, E:\ai-pacs\ai-pacs codes\ai-pacs beta version)
  builder/build_release.py
    → builds the app, stamps engine/version.json
    → generates core/manifest-<v>.json  (path+size+sha256 of every app file)
    → populates files/<hh>/<sha256>.gz  (content-addressed store: gzip blobs
      named by the sha256 of the UNCOMPRESSED file — only NEW hashes appear
      per release; unchanged DLLs are never re-published)
    → writes update_feed.json (version, notes, required flag, delta block,
      full-installer fallback entry)
  tools/build/publish_update.py --site-root <web root> [--site-root <mirror>]
    → merges builder/output/updates/ into <web root>/updates/aipacs/stable/

WEBSITE (your job)
  serves  /updates/aipacs/stable/{update_feed.json, core/*, files/**}
  exactly per 02_CLIENT_CONTRACT.md (MIME, caching, no re-encoding, verbatim
  bytes). Two sites may host the same tree (primary + mirror).

CLIENT (already shipped in the workstation)
  startup (off-thread) → GET update_feed.json → version newer? → popup →
  user clicks Update → GET manifest (sha-verified) → hash local files →
  download only differing blobs (sha-verified, resumable) → app restarts via
  a helper that backs up + applies + AUTO-ROLLS-BACK on any failure.
  If the feed has no delta block → downloads the full installer instead.
```

## Trust model

- Integrity = SHA-256 end-to-end: feed → manifest hash → per-file hashes.
  The website is not trusted to be correct, only to be available; any
  corruption/tampering makes the client abort BEFORE touching the install.
- Transport = HTTPS in production (local Laragon HTTP is fine for testing).
- Privacy: the tree contains only the sanitized application build — the
  workstation's release gate blocks any center IP/credential from shipping.

## What already exists on the workstation side (do NOT redesign)

- Feed/manifest formats + client behavior: FROZEN (client is shipped).
- `website_update_service/` in the workstation repo contains the static-host
  reference: `README.md`, sample feed, `.htaccess` (Apache) and `web.config`
  (IIS) with the exact header rules — copies are in this folder.
- The publish tool writes the finished tree; your service only has to SERVE it
  (plus, optionally, a nicer publish/upload path later — see the guide).

## Local-first deployment (current phase)

Everything is validated on this machine before any production upload:
Laragon workspace `D:\laragon-www`, site root `D:\laragon-www\ai-pacs\public_html`,
local URL `http://localhost:8080`. The AI-PACS source build on this PC will be
pointed at the local URL for the end-to-end test. Production (Hostinger +
Cloudflare at ai-pacs.com) comes later and follows the workspace's existing
deployment runbooks — never write to production directly.
