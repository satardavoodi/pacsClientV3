# Paste-ready prompt for the WEBSITE agent (Laravel update service, local first)

---

You are working in the AI-PACS website workspace `D:\laragon-www` (Laragon,
Windows). Follow this workspace's own rules first: read `AGENTS.md`,
`CLAUDE.md`, and `PROJECT_CONTEXT_AI_PACS_WEBSITE.md` at the workspace root.
LOCAL ONLY: never write to the production host (Hostinger/ai-pacs.com), never
touch payment links, WordPress core, or `/consult-form/` behavior.

## Mission

Build and deploy — locally first — the **AI-PACS Update Service**: the website
side of the workstation's new automatic incremental update system. The
workstation client is ALREADY SHIPPED; your job is to serve its exact HTTP
contract at `/updates/aipacs/stable/…`, implemented with Laravel per the
implementation guide, on the local site (`D:\laragon-www\ai-pacs\public_html`,
`http://localhost:8080`).

## Read these FIRST (in order) — they are in `D:\laragon-www\workspace-docs\aipacs-update-service\`

1. `01_PROCESS_OVERVIEW.md` — what the update system is, the full
   build→publish→website→client pipeline, and the trust model.
2. `02_CLIENT_CONTRACT.md` — the EXACT byte-level HTTP contract (URLs, feed
   and manifest schemas, blob store, MIME/caching/no-re-encoding rules).
   This contract is FROZEN — the client is installed at medical centers; do
   not redesign any format or path.
3. `03_LARAVEL_IMPLEMENTATION_GUIDE.md` — architecture options (A hybrid
   static+Laravel = recommended; B fully-routed), Laravel code sketches,
   Laragon bring-up, smoke tests, and the end-to-end acceptance checklist.
4. Supporting files in the same folder: `sample_update_feed.json`,
   `static.htaccess` (Apache header/MIME rules), `static-web.config` (IIS
   equivalent), `04_STATIC_STRUCTURE_README.md` (the static-host reference).

## Deliverables

1. The `/updates/aipacs/stable/` tree served locally with correct headers
   (Option A unless the user says otherwise): existing-directory bypass of
   WordPress + the provided `.htaccess`, seeded with `sample_update_feed.json`
   renamed to `update_feed.json` as a placeholder.
2. A small Laravel app (sibling of the existing `consult-form` pattern, e.g.
   `public_html/updates-app/laravel-back/`) providing `GET /updates-api/health`
   (tree exists + feed parses + returns version) and
   `GET /updates-api/releases` (lists `core/manifest-*.json` versions).
   Keep it independent of the consult-form app.
3. All smoke tests in the guide passing (paste the curl outputs as evidence):
   correct Content-Type/Cache-Control per path, NO `Content-Encoding: gzip`
   on `.gz`, byte-stable JSON responses, space-containing filenames resolve.
4. A short `DEPLOY_NOTES.md` in the docs folder recording what you created,
   how to re-run the checks, and what remains for the production phase.

## Acceptance (end-to-end, coordinated with the user)

The user will publish a REAL release tree from the workstation build machine
into the local web root (`publish_update.py --site-root
"D:\laragon-www\ai-pacs\public_html"`) and point the AI-PACS workstation at
`http://localhost:8080/updates/aipacs/stable`. Success = the workstation's
"Check Updates" lists the release with the delta artifact, and the served
`core/manifest-<v>.json` hash equals `delta.manifest_sha256` from the feed.

## Out of scope (do NOT do)

- Any production/Hostinger/Cloudflare change (later phase, separate approval).
- Modifying the workstation repo (`E:\ai-pacs\…`) — it is read-only reference.
- Changing feed/manifest/store formats, adding auth to the GET paths, or
  transforming served bytes (minify/BOM/re-encode) — all break shipped clients.
- The token-protected upload/publish API (phase 2 — design notes welcome,
  implementation only when asked).

Work step by step: read the docs, propose your plan (A vs B + exact paths),
then implement, then run every smoke test and report evidence.

---
