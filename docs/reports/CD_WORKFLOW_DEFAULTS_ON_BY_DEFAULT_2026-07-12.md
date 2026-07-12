# CD burn + portable viewer: correct behaviour by DEFAULT on a clean install

**Date:** 2026-07-12
**Goal:** Install → Burn CD → Open Portable Viewer → Import DICOM → Display, with **zero** manual setup.
**Status:** Done. Verified against a real burned CT disc with the **frozen** viewer.

---

## 1. What was already correct (verified, not assumed)

| Requirement | State |
|---|---|
| Fresh install → recommended viewer selected | ✅ `get_viewer_mode()` returns `default` when no config exists; the shipped `config/lightviewer_settings.json` is `{"viewer_mode": "default", "light_viewer_path": ""}` |
| Viewer included at the Write/Burn step | ✅ `include_viewer_cb.setChecked(True)` whenever a viewer path resolves |
| Drag-and-drop import | ✅ **unconditional** — no flag (2026-07-12 fix) |
| DICOMDIR detection | ✅ unconditional |
| Files without `.dcm` | ✅ unconditional (discovery is by content) |
| Read-only optical media | ✅ `optical_io.read_bytes` → RAM + retries; nothing written to the disc |
| `asInvoker`, not administrator | ✅ confirmed in the rebuilt exe's PE manifest; the build passes no `--uac-admin` |
| Installer ships the NEW viewer | ✅ the legacy `lightViewer/` folder is **excluded** from the build; `lightViewer_dist` is materialized into the `run_cd` payload, and the build **fails hard** if the lite viewer is missing |
| Codecs | ✅ pylibjpeg + rle + openjpeg + libjpeg (import name **and** dist metadata) |

## 2. What was actually broken — four real defects fixed

### D1 — CLINICAL SAFETY: the viewer could show **another patient's test images**

The PyInstaller bundle ships pydicom, and pydicom's package data contains **25 sample
`.dcm` files**. `RUN_VIEWER.cmd` copies the viewer to `%TEMP%\AIPacsLiteViewer` and runs
it from there, so the exe's own folder is a media-root candidate. If `--import-folder`
was ever lost or malformed, `discover_media_root`'s fallback probe ("does this folder
contain any DICOM?") found **pydicom's samples** and the viewer happily presented them
as the patient's study.

This was not theoretical — it is exactly what the new log showed on the first frozen run:

```
[LITE-START] media_root=…\lightViewer_dist\AIPacsLiteViewer optical=False
[LITE-SCAN]  root=…\AIPacsLiteViewer source=filescan series=13 images=15
[LITE-SCAN]  series uid=1.3.6.1.4.1.5962.1.3.0.1.1175775772.5720.0 modality=OT …
```

Thirteen series of pydicom test data, offered to the user as a patient study.

**Fix:** `_is_viewer_bundle_dir()` — a directory holding the viewer executable or a
PyInstaller `_internal` payload is the *program*, never the *media*, and is rejected
outright as a media root. `_internal` is also added to `_SKIP_DIR_NAMES` so the file
walk can never descend into it. After the fix:

```
[LITE-START] Skipping the viewer's own program folder as a media root candidate: …
[LITE-START] media_root=(none)                       ← correct: shows the empty state
```

and with a real disc:

```
[LITE-SCAN] root=…\CT TEST CD… source=dicomdir series=2 images=127 errors=none
```

### D2 — Every diagnostic line was being discarded

`main()` called `logging.basicConfig(...)` only, which writes to **stderr**. The shipped
viewer is built `--windowed`, so there is no console and **nothing was ever recorded**.
When a patient CD misbehaved on a client PC there was nothing to read.

**Fix:** new `portable_viewer/viewer_log.py` — a rotating **file** log at the first
writable location (`%LOCALAPPDATA%\AIPacsLiteViewer\logs\lite_viewer.log` →
`%TEMP%\…` → none). **Never the media** (the CD is read-only), never raises.
Stages now logged end-to-end:

```
[LITE-START]  version, exe, frozen, media_root, optical, ELEVATED, log file, pydicom
[LITE-SCAN]   root, source (dicomdir|filescan), series + images, every series UID
[LITE-DROP]   drop_received / dicomdir_import / filescan_import / import_done / import_failed
[LITE-DECODE] failed path + error   ← load_slice never raises, so this was invisible before
```

The banner also **warns if the viewer is running elevated**, because Windows UIPI then
blocks drag-and-drop from a normal File Explorer — the exact class of failure that was
suspected in the original investigation.

### D3 — A stale custom-viewer setting burned a disc with **no viewer at all**

`get_viewer_selection()` returned `path=None` when the configured custom viewer no
longer existed (uninstalled, moved, or a path carried over from an old install). The
burn dialog then disabled the "Include viewer" checkbox and the patient got a disc they
could not open — silently.

**Fix:** a missing/invalid custom viewer now **falls back to the recommended AI-PACS
portable viewer** (`fell_back_from_custom: True`, surfaced in the checkbox tooltip). An
explicit, still-valid custom choice is preserved untouched. This implements the required
priority exactly:

```
no saved preference        → recommended defaults
explicit valid preference  → preserved
missing / uninitialized    → MUST NOT disable the fixes → recommended defaults
```

The pre-existing test `test_custom_mode_with_missing_path_resolves_none` asserted the
old (broken) contract and has been rewritten to the new one, with the reason recorded.

### D4 — `viewer_log.py` was missing from the shipped payload

A new module is **not** picked up by `sync_plugin_mirrors.py` automatically. Added via
`--add` (run_cd payload: 413 pairs match) and to the PyInstaller `--hidden-import` list,
which the build requires explicitly (it does not honour the entry script's runtime
`sys.path.insert`).

---

## 3. Verification

**Frozen viewer, real disc** — the two cases that matter:

| Run | Result |
|---|---|
| No `--import-folder` (argument lost) | `Skipping the viewer's own program folder…` → `media_root=(none)` → empty state. **No test images.** |
| `--import-folder <CD>` | `source=dicomdir series=2 images=127`, both CT series listed by UID |

- Manifest of the rebuilt exe: `requestedExecutionLevel level="asInvoker"` ✅
- Frozen-bundle `--selftest`: **PASSED**; 106.6 MB; all four codecs present ✅
- Log file written to `%LOCALAPPDATA%\AIPacsLiteViewer\logs\lite_viewer.log` ✅

**Tests:** `tests/code/cd_burner` **169 passed** (new: `test_cd_defaults_on_fresh_install.py`
— 11 checks pinning fresh-install defaults, the stale-custom fallback, the unconditional
import fixes, and the log location; plus 2 new clinical-safety checks in
`test_lite_viewer_external_drop.py`). `tests/code/builder` 64 passed, 1 pre-existing
failure (`test_release_gate_stage_config_parity_against_current_stage` — fails on a clean
baseline too). Mirrors 413/413.

> Build hygiene note: the lite-viewer build's warm-up self-test can leave an
> `AIPacsLiteViewer.exe` process alive, which then **locks** `generated-files/build/lite_viewer/`
> and makes the next build fail with `PermissionError [WinError 5/32]`. If a build or the
> `test_plugin_package_builder` tests fail that way, kill stray `AIPacsLiteViewer` processes
> and delete `pyi_dist`/`pyi_work`. Worth fixing in the build script.

---

## 4. Still open — needs a decision

**`config/lightviewer_settings.json` ships one center's identity:**

```json
"center_name": "alizadeh imaging center",
"center_address": "tehran",
"center_phone": "02155906157"
```

This template is seeded on **every fresh install**, so a new center (e.g. Roshana) that
burns a disc before editing the setting stamps **the wrong imaging center** onto the
patient's media and into `AIPACS_MEDIA_INFO.json`. Recommended: ship the template with
empty center fields so each install must fill in its own. Not changed — this is a
product decision, not a bug fix.

## 5. Clean-client validation checklist (for the next build)

1. Install the new build on a clean machine.
2. Open the CD Burn module → "Include viewer: AI-PACS Lite Viewer **(Recommended)**" is already ticked.
3. Burn a patient CD without changing any setting.
4. Confirm the disc has `DICOMDIR`, `PT…/ST…/SE…/IM…`, `VIEWER/`, `autorun.inf`, `RUN_VIEWER.cmd`.
5. Start the viewer from the disc → the study loads automatically.
6. Drag a file / a folder / the DICOMDIR from the disc onto a viewport → it imports and displays.
7. Check `%LOCALAPPDATA%\AIPacsLiteViewer\logs\lite_viewer.log` — `[LITE-START] elevated=False`,
   `[LITE-SCAN] source=dicomdir`, no `[LITE-DECODE] failed`.
8. Restart the app → defaults unchanged.
