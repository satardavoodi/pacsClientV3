# Eagle Eye open freezes the app (~55 s) — the AI-module training-settings folder scan (OPT-27)

**Date:** 2026-07-12
**Reported as:** "I run Eagle Eye on patient 49874 and it doesn't open the patient and the app freezes."
**Status:** FIXED, default-on, **LIVE-VERIFIED** on 49874 (2026-07-12 18:31).
**Files:** `modules/ai_imaging/ai_module_ui/service_tab/training_data_settings_tab.py` (NOT plugin-mirrored)
**Guard:** `tests/code/ai_imaging/test_eagle_eye_training_scan_bounded.py` (8) — full `tests/code/ai_imaging` 18 green.

---

## 1. Symptom

Clicking **Eagle Eye** on a patient froze the whole workstation for ~1 minute; the patient/AI tab
would not paint until it ended. Looked like "the patient doesn't open".

## 2. Evidence (2026-07-12 17:44–17:45 session, patient 49874)

`user_data/logs/viewer_diagnostics.log`:

```
[MAIN_THREAD_STALL] stall_duration_ms=54799.3      ← one contiguous 54.8 s GUI-thread block
```

The F11 stall-trace sampler pinned the same stack on every sample during the freeze:

```
ai_chat_interactorstyle.open_ai_module()                 → switch_right_panel('ai_module')
_hp_modules.add_new_tab_widget()                         → AIMainWindow(study_uid=…)
ai_mainwindow.py:99          ModelTrainingTab()          ← built EAGERLY in AIMainWindow.__init__
model_tab.py:40              TrainingDataSettingsTab()
training_data_settings_tab.py:1091  MammographySettingsWidget()
  → _load_defaults()                    (:887)
  → _auto_detect_and_apply_img_size()   (:949)
  → _detect_mg_dicom_image_size()       (:234)
  → pydicom.dcmread(...)                ← blocking, ON THE GUI THREAD
```

`app.log` corroborates: sustained **8–30 MB/s disk read at 25–55 % CPU for ~55 s** between the
Eagle Eye handoff and `[DataSetTab] Initialized`.

## 3. Root cause (ours — not the AI server)

When the Eagle Eye / AI-module tab is constructed, the **Model Training settings** widget tried to
auto-detect the MG training image size by walking the local DICOM store and `pydicom.dcmread`-ing
every file, **synchronously on the GUI thread**:

* search root = `_default_patients_root()` → `user_data/patients` → **53,250 DICOM files / 31.7 GB**
  on this machine.
* the `max_scan_files=300` cap **only counted MG hits** — a non-MG file `continue`d *before*
  `scanned += 1`, so on a store dominated by CT/MR/DX the cap never tripped and the walk degenerated
  into "open every DICOM on disk".

Not patient-specific: 49874 was simply the first Eagle Eye open of that session. Unrelated to the
502 `run_full_analysis` incident the same day (that was the AI server's PACS backend on
`127.0.0.1:8000` being down — see the 502 note below).

## 4. Fix (flag `AIPACS_AI_TRAINING_SCAN_ASYNC`, default **ON**)

1. **Bounded scan.** `_detect_mg_dicom_image_size(...)` gains `max_examined_files` (files actually
   opened; default 2000, `AIPACS_AI_TRAINING_SCAN_MAX_FILES`) and `deadline_s` (wall clock; default
   3.0 s, `AIPACS_AI_TRAINING_SCAN_DEADLINE_S`). `max_scan_files` (MG hits) is kept but is no longer
   the only stop condition. `0` = unlimited (legacy).
2. **Off the GUI thread.** `_run_scan_off_thread(work, apply_result)` runs the scan on a daemon
   thread and applies the result through the module's existing thread-safe `_run_on_ui` dispatcher
   (swallows `RuntimeError` if the tab was closed mid-scan). Applied to the MG size auto-detect and
   to **both** `_update_file_count()` `os.walk`s (BoneAge + Mammography). The labels show
   "scanning…" / "counting…" until the result lands.
3. **Kill switch.** `AIPACS_AI_TRAINING_SCAN_ASYNC=0` restores the legacy inline, unbounded path
   byte-for-byte (`_scan_limits()` returns `(0, 0.0)` and `_run_scan_off_thread` runs inline).

Nothing clinical changes: this is a *training-settings spinbox default*, no viewer/VTK/geometry/
download path is touched.

## 5. Result (live, same patient, 2026-07-12 18:31)

| | Before (17:44) | After (18:31) |
|---|---|---|
| Worst main-thread stall on Eagle Eye open | **54,799 ms** | **1,444 ms** |
| Stall stacks inside `training_data_settings_tab.py` | ~55 s of `pydicom.dcmread` | **none** |
| Scan itself | GUI thread, unbounded | background thread — `[TrainingUI] background mg-size-detect done in 3002 ms` |
| Same scan re-run against the real 53k-file store | ~55 s | **1.88 s** (hits the 2000-file cap) |

Remaining sub-1.5 s stalls on AI-module open are **unrelated** and inherent to the AI module's
Advanced/VTK viewer on the GUI thread: `ImageViewer2D.__init__` (932 ms),
`add_ai_boxes2viewer → draw_boxes_ijk → ResetCameraClippingRange` (422 ms), segmentation
`create_overlay_box` (450 ms), plus `BoneAgeSettingsWidget._build_ui` pure-Qt construction (438 ms).

## 6. Known trade-off

With the file cap, if no MG DICOM appears within the first 2000 files of `user_data/patients`, the
Training tab shows *"Auto image size: no MG DICOM found (keeping current value)"* instead of a
detected value. A user-selected data path (Browse) is still scanned **first**, so the intended
training-folder case is unaffected. Raise `AIPACS_AI_TRAINING_SCAN_MAX_FILES` if a site wants a
deeper probe — it costs no GUI responsiveness now that it runs off-thread.

## 7. Not done (staged follow-ups)

* **Lazy-build `ModelTrainingTab`** in `AIMainWindow.__init__` (build it when its tab is first
  shown). It is a training/settings surface — a reading workflow never needs it at Eagle Eye open.
  Would also remove the 438 ms pure-Qt construction cost.
* **Surface the AI server's error `detail`** in the Eagle Eye dialog. `MamoWorker.run` calls
  `resp.raise_for_status()`, which discards the server's JSON body. On 2026-07-12 the dialog said
  only *"502 Server Error: Bad Gateway"* while the body actually said
  `PACS request failed: HTTPConnectionPool(host='127.0.0.1', port=8000) … actively refused it` —
  i.e. the AI server (`192.168.2.222:8002`, uvicorn, healthy) could not reach **its own** PACS HTTP
  API on port 8000. A pre-flight `GET /health` + showing `detail` would make that self-diagnosing.
* Move the AI-module's VTK viewer construction cost off the open path (spinner-only today).
