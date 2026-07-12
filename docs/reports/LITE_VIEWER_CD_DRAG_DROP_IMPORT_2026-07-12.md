# Portable CD viewer: DICOM could not be dragged in from the disc

**Date:** 2026-07-12
**Evidence:** `…\logs roshana\CT TEST CD roshana\New folder (2)` (a real burned CT test disc)
**Status:** FIXED + verified end-to-end against that disc. Needs a re-burn to reach patients.

---

## 1. Root cause — external drag-and-drop was never implemented

The burned disc was **completely correct**. What was missing was code:

`ImageCanvas.dragEnterEvent` accepted **only** the viewer's *internal* MIME type
(`application/x-aipacs-series-index` — a series dragged from its own series list):

```python
def dragEnterEvent(self, event):
    if event.mimeData().hasFormat(_SERIES_MIME):   # internal drag only
        event.accept()
    else:
        event.ignore()                              # ← every Explorer drop landed here
```

A drop from File Explorer arrives as **`text/uri-list`**. It matched nothing, hit
`event.ignore()`, and Windows showed the "no entry" cursor. `LiteViewerWindow` never
called `setAcceptDrops()` at all, so the rest of the window rejected drops too.
There was no `hasUrls()` handling anywhere in the portable viewer.

**Everything else on the investigation list was already correct** — I verified each
against the real disc rather than assuming:

| Suspected cause | Reality |
|---|---|
| Viewport accepts drops? | Yes — `setAcceptDrops(True)`, but only for the internal MIME |
| Elevation / integrity-level mismatch | **Not the cause.** The exe manifest is `requestedExecutionLevel level="asInvoker"`, and `RUN_VIEWER.cmd` does not elevate |
| Extension filter rejecting the files | **No.** The disc stores extension-less `IM000000`; `_iter_candidate_files` already accepts suffix-less files, and discovery is by content |
| Read-only optical media rejected / write attempted | **No.** `optical_io.read_bytes` reads into RAM with retries; nothing is written to the source |
| Path resolved relative to the exe instead of the disc root | **No.** `discover_media_root` walks exe-dir → **parent**, finds `<root>/DICOMDIR` |
| DICOMDIR unsupported | **No.** `pydicom.fileset.FileSet` path works |
| Folder vs file drops differ | Moot — neither was accepted |

Live proof that discovery was never the problem — running the existing scanner against the actual disc:

```
discover_media_root(exe_dir=…\VIEWER) -> …\New folder (2)
source = dicomdir | series = 2 | images = 127 | errors = []
   CT 2 — (1 img)   patient GORJI^HADIS
   CT 3 — (126 img) patient GORJI^HADIS
```

---

## 2. The fix

### `media_scan.scan_paths(paths)` — one import entry point for any dropped shape

Refactored the existing per-file grouping into `_group_files_into_series()` so the
recursive media scan and the new drop import share **exactly one** discovery
implementation. `scan_paths` accepts, in any combination:

- a single DICOM file, **with or without** a `.dcm` extension
- several files from one or more series
- a series / study / patient folder
- a disc root containing `DICOMDIR` (fast path via `FileSet`)
- the `DICOMDIR` file itself

Discovery is **by content, never by extension** — a patient CD writes `IM000000`, so an
extension filter would find nothing. Junk (`autorun.inf`, `START_HERE.txt`) and the
`VIEWER/` folder are skipped. Nothing is ever written to the source media.

### Qt layer

- `local_paths_from_mime()` / `_drop_payload_kind()` — pure helpers; `"series"` (internal
  drag) vs `"paths"` (external files) vs `None`.
- `ImageCanvas` now accepts **both** payloads. An external drop calls the new
  `on_paths_dropped` hook → the series loads into **that pane**.
- `LiteViewerWindow.setAcceptDrops(True)` — dropping anywhere on the window works, not
  just over a pane.
- `_ImportTask` (QRunnable) runs the scan **off the GUI thread**, so slow optical I/O
  never freezes the viewer.
- `_on_import_done` **merges** by `series_uid` (re-dropping the same series does not
  duplicate it), repopulates the series list, and loads the first imported series into
  the target pane.

### Logging (per the spec — the failing stage is now obvious in the log)

```
[LITE-DROP] drop_received count=1 pane=0 optical=True first=D:\PT000000\ST000000\SE000001
[LITE-DROP] dicomdir_import root=D:\ series=2 images=127
[LITE-DROP] filescan_import files=126 valid_dicom=126 invalid=0 series=1
[LITE-DROP] import_done source=filescan series_found=1 new=1 images=126 target_pane=0
[LITE-DROP] import_failed: <message>
```

---

## 3. Verification

**Against the real disc** — every drop shape in the spec:

| Dropped | Result |
|---|---|
| disc root (has DICOMDIR) | `dicomdir` · 2 series · 127 images |
| the `DICOMDIR` file itself | `dicomdir` · 2 series · 127 images |
| ONE extension-less file `IM000000` | `filescan` · 1 series · 1 image |
| three files of one series | `filescan` · 1 series · 3 images |
| a series folder | `filescan` · 1 series · 126 images |
| a study folder | `filescan` · 2 series · 127 images |
| a patient folder | `filescan` · 2 series · 127 images |
| `autorun.inf` (junk) | clear error, no crash |

**End-to-end, real window + real disc** — an empty viewer, then an Explorer-style
`text/uri-list` drop of a CD series folder onto the left pane:

```
before drop: series in list = 0 | pane0 image = None
drop accepted = True
after drop : series in list = 1 · pane0 series_index = 0 · slices = 126
             pane0 IMAGE = (512, 512)
             status = Imported 1 series · 126 images · GORJI^HADIS [14532] · source: filescan
RESULT: PASS
```

**Tests:** `tests/code/cd_burner/test_lite_viewer_external_drop.py` — 16 new
(every drop shape, no-write-to-source, the URI payload is recognized instead of ignored,
the internal series drag still works, the window is a drop target).
`tests/code/cd_burner` = **153 passed**.

**Build:** `tools/build/build_lite_viewer.py` rebuilt — frozen-bundle `--selftest`
**PASSED**, 106.2 MB, codecs intact. Mirrors 412/412 (`portable_viewer` mirrors into the
run_cd payload).

---

## 4. What still has to happen

The viewer **on the existing disc is the old build**. The fix reaches patients only after
the CD is **re-burned** with the rebuilt `lightViewer_dist` bundle. Existing discs keep
the old behaviour (the images are still readable there via **Open Folder…**, which always
worked).

## 5. Follow-ups (not done)

- `optical_io.stage_files_to_temp()` / `is_optical_path()` exist but are **not wired** —
  slices are read straight off the disc (with retries) on every scroll. Staging a series to
  local temp on first use would make scrolling from a real CD much snappier. This is a
  performance improvement, not a correctness one, so I left it out of this fix.
- A "Recently imported" indicator when a drop merges into an already-loaded study.
