# CD AutoRun Investigation — disc "ZALAGHI MASOOME" (F:\), 2026-07-11

## Verdict (one line)

**Not an AutoRun failure and not a Windows block — the disc was burned WITHOUT a
viewer.** Its `autorun.inf` correctly says *"open the DICOM folder"*, so Windows
did exactly what the disc asked: it opened Explorer. There is no viewer and no
launcher on the media to start.

---

## 1. Contents of the burned CD (F:\, volume `ZALAGHI MASOOME`)

```
07/08/2026  07:14 PM      29,898  AIPACS.ico
07/11/2026  05:20 PM         424  AIPACS_MEDIA_INFO.json
07/11/2026  05:20 PM      29,648  DICOMDIR
07/11/2026  05:20 PM          55  OPEN_DICOM_FOLDER.cmd
07/11/2026  05:20 PM   <DIR>      PT000000            (120 files — patient data OK)
07/11/2026  05:20 PM         158  RUN_VIEWER.cmd
07/11/2026  05:20 PM       1,635  START_HERE.txt
07/11/2026  05:20 PM         173  autorun.inf
```

**MISSING (the whole point):**

| Expected | Present? |
|---|---|
| `VIEWER\` folder (viewer + `_internal` runtime/DLLs) | **NO — absent** |
| `AIPacsViewer.exe` (the double-click launcher) | **NO — absent** |
| Viewer config files | **NO** (they live inside `VIEWER\`) |
| `DICOMDIR` + DICOM images | YES (120 files) |
| `autorun.inf` | YES |
| `AIPACS.ico` | YES |

`AIPACS_MEDIA_INFO.json` states it outright:

```json
"viewer_included": false,
"viewer_launcher": null,
"viewer_launcher_primary": null,
"portable_launchers": ["RUN_VIEWER.cmd", "OPEN_DICOM_FOLDER.cmd"]
```

And `RUN_VIEWER.cmd` is the no-viewer stub:

```
@echo off
echo No portable viewer was included on this media.
echo Please open the DICOM files with any DICOM viewer and use DICOMDIR if supported.
pause
```

## 2. Validation of `autorun.inf`

```ini
[autorun]
open=OPEN_DICOM_FOLDER.cmd
icon=AIPACS.ico
label=ZALAGHI MASOOME
action=Open DICOM media

[Content]
MusicFiles=false
PictureFiles=false
VideoFiles=false
```

* Syntax: **valid**. Encoding: fine. Paths: **valid and relative** (`AIPACS.ico`
  and `OPEN_DICOM_FOLDER.cmd` both exist at the root).
* Icon path: **correct** — the AI-PACS drive icon works.
* Label: **correct** — the patient name is the CD name (`ZALAGHI MASOOME`).
* **BUT `open=` points at `OPEN_DICOM_FOLDER.cmd`** — this is the burner's
  *no-viewer fallback branch*. That script is literally
  `start "" explorer.exe "%~dp0"`.

So the observed symptom — *"double-clicking the drive just opens the CD contents
in File Explorer"* — **is precisely what this disc is configured to do.** The
autorun mechanism most likely *worked*; it just ran "open the folder".

## 3. Validation of the launcher executable

**Cannot be validated — it is not on the disc.** `AIPacsViewer.exe` is absent, as
is the entire `VIEWER\` tree. There is nothing to launch, manually or otherwise.

## 4. Comparison with previous / expected discs

A correctly burned disc has:

```
AIPacsViewer.exe        <- branded double-click launcher (root)
VIEWER\                 <- AIPacsLiteViewer.exe + _internal\ (runtime, DLLs, codecs)
autorun.inf             -> open=AIPacsViewer.exe / shellexecute=AIPacsViewer.exe
AIPACS_MEDIA_INFO.json  -> "viewer_included": true
```

This disc has **none of the viewer side**, yet it **does** carry the newest
features (`AIPACS.ico` drive icon, patient-name volume label, `drive_icon` +
`patient_label` in the manifest). That proves it was burned by the **current**
pipeline — the icon/label/launcher work is *not* the problem. Only the *viewer
inclusion* failed.

## 5. Windows limitation or application regression?

**Neither, strictly — it is a burn-side failure.** Checked on this PC:

* `HKCU\...\Explorer\AutoplayHandlers\DisableAutoplay = 0x0` (AutoPlay enabled)
* `NoDriveTypeAutoRun` — **not set** in HKLM or HKCU (no AutoRun restriction)

So Windows was not blocking anything. The disc simply told it to open a folder.

**Important separate fact (must be understood anyway):** on Windows 7 and later,
optical media does **not** silently auto-*execute* programs. Even a perfect disc
will not "launch the viewer by itself". What actually happens is:
AutoPlay shows a prompt/notification offering the disc's `action=` entry
(e.g. *"Open AI-PACS Lite Viewer"*) which the user clicks once — or the user
double-clicks `AIPacsViewer.exe`. Fully-unattended execution from CD is disabled
by design and cannot be re-enabled from the disc. Our design already accounts for
this: a clearly labelled `AIPacsViewer.exe` at the root plus a friendly AutoPlay
`action=` line.

## 6. Responsible change / root cause

Not the autorun/icon/label code. The root cause is in the burn flow
(`cd_burn_manager.run()`):

```python
if self.light_viewer_path and Path(self.light_viewer_path).exists():
    self._copy_light_viewer(...)          # viewer + launcher onto the disc
else:
    self._write_portable_support_files(...)   # <-- NO-VIEWER disc, silently
```

On the **burning computer**, `light_viewer_path` was empty / unresolvable
(`viewer_locator.resolve_default_viewer()` returned nothing), so the burn took
the `else` branch and produced a viewer-less disc. The dialog only wrote an
`[info] Media launch target: OPEN_DICOM_FOLDER.cmd (no bundled viewer)` line into
the log — **nothing blocked or warned the operator**, so the disc shipped
silently without a viewer.

Why the viewer was unresolvable on that machine (one of):
* its installed AI-PACS has no Lite Viewer in the `run_cd` payload (CD module not
  ticked at install, or an installer built before the viewer was bundled);
* the Light Viewer setting there points at a *custom* exe that no longer exists;
* the "Include viewer" checkbox was off.

**The real defect is the silent fallback**, and that is what I fixed.

## 7. Recommended fix

### Implemented now (code)

`cd_burn_dialog._confirm_viewer_available()` — a blocking guard wired into **both**
the burn and the prepare-folder paths. If "Include viewer" is checked but no
viewer can be resolved, the operator now gets a warning that must be answered:

> **Viewer not found — the disc would have NO viewer**
> If you continue, the disc will contain ONLY the DICOM files and NO viewer.
> Inserting it will just open the folder in Explorer… To fix: Settings → Light
> Viewer… **Burn a disc WITHOUT a viewer anyway?**  `[Cancel (default)] [Yes]`

A viewer-less disc can no longer be produced by accident. (138/138 cd_burner
tests green; mirrors 412/412.)

### Action required on the BURNING computer

1. Open **Settings → Light Viewer** and confirm it reports
   *"AI-PACS Lite Viewer ready (… MB)"*. If it does not, that machine's install
   lacks the viewer — reinstall/update with the **CD Viewer/Writer module**
   selected so the `run_cd` payload ships `lightViewer_dist`.
2. Re-burn the disc.
3. Verify the new disc contains `AIPacsViewer.exe` + `VIEWER\` and that
   `AIPACS_MEDIA_INFO.json` says `"viewer_included": true`.

### Expected behaviour on a correct disc

Insert → AutoPlay offers **"Open AI-PACS Lite Viewer"** (one click) → branded
"Preparing viewer, please wait." popup → viewer opens.
Or simply double-click **`AIPacsViewer.exe`** at the disc root.
It will *not* start with zero clicks — Windows does not allow that from optical
media, and no change to our disc can alter that.
