# Privacy And Data Policy (Packaging)

Last updated (UTC): `2026-02-23T23:03:54.106807+00:00`

## Purpose

This repository contains medical-imaging workflows and runtime paths that may store DICOMs, thumbnails, attachments, logs, caches, and local databases. Packaging must exclude all runtime/patient/user data.

## Never Package

- Real patient DICOM files or study folders
- Runtime downloads/caches/thumbnails/attachments
- Local databases (`*.db`, `*.sqlite`, `*.sqlite3`)
- Logs (`*.log`)
- Generated files (`generated-files/**`)
- Local source/staging DICOM folders (`source/**`, `Education/**` when containing DICOM content)
- Secrets (`.env`, `.env.*`, tokens, API keys)

Detected project-specific exclusions (audit):
- `Education`
- `Education/**`
- `PacsClient/pacs/patient_tab/advance_mpr_3d_slicer/slicer_custom_app/logs/**`
- `PacsClient/pacs/patient_tab/viewers/.env`
- `Segments`
- `app_output.log`
- `attachment`
- `attachment/**`
- `build_final.log`
- `database`
- `database/**`
- `debug.log`
- `dicom.db`
- `download_manager_test.log`
- `generated-files`
- `generated-files/**`
- `generated-files/live_sync2_err.log`
- `generated-files/live_sync2_out.log`
- `generated-files/live_sync3_err.log`
- `generated-files/live_sync3_out.log`
- `generated-files/live_sync_err.log`
- `generated-files/live_sync_out.log`
- `generated-files/viewer_stress_live.log`
- `generated-files/zeta_boost_cache/manifest.db`
- `source`
- `source/**`
- `source/thumbnails/**`
- `thumbnails`
- `thumbnails/**`


Baseline exclusion patterns:
- `Education/**`
- `database/**`
- `generated-files/**`
- `thumbnails/**`
- `attachment/**`
- `downloads/**`
- `cache/**`
- `logs/**`
- `**/*.db`
- `**/*.sqlite`
- `**/*.sqlite3`
- `**/*.log`
- `**/*.dcm`
- `**/*.dicom`
- `**/.env`
- `**/.env.*`


## Runtime Storage Rules (Windows)

- Use `%LOCALAPPDATA%\AIPacs` as the writable root
- Recommended subfolders:
  - `cache`
  - `downloads`
  - `dicom`
  - `thumbnails`
  - `attachments`
  - `logs`
  - `db`
  - `tmp`
- Do not write to:
  - `dist/`
  - PyInstaller `_internal` / `_MEIPASS`
  - repository root (development-only behavior must be redirected in frozen builds)

## Config & Secrets Rules

- Ship only non-sensitive default config templates
- Load secrets from environment variables or external config in LocalAppData
- Do not include `.env` files in PyInstaller datas
- Sanitize logs and crash reports to avoid PHI/token leakage

## Audit Evidence

- Entrypoints and imports: `builder/inventory/entrypoints.json`, `builder/inventory/imports_summary.json`
- Runtime path risks: `builder/inventory/runtime_data_paths_inventory.json`
- Human summary: `builder/audit/reports/AUDIT_SUMMARY.md`
