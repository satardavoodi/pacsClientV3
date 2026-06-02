# Other-PC Log Evaluation — 2026-06-01

Logs from `C:\Users\Dr.Alizadeh\Desktop\log on other pc` (a **second AI-PACS deployment**), spanning 2026-05-31 → 2026-06-01 (last write 14:57). Evaluated with the same pipeline used for the local PC (soak analyzer + native-fault + signature greps).

## Verdict: **FAIL / UNSTABLE** — significantly worse than the local build

The other PC runs an **older build that lacks the stability fixes present on the local source build**. It still exhibits the severe memory leak **and** hard crashes that the local build has largely resolved.

---

## Critical findings

### 1. Severe unbounded memory leak → abrupt termination (CRITICAL)
Soak analysis (15 sessions). Worst session:

| Session | Duration | RSS | Net | Peak | Errors | End | Verdict |
|---|---|---|---|---|---|---|---|
| 2026-06-01 11:31 | **3.4 h** | 245 → **1375 MB** | **+1244 MB** | **1489 MB** | 20 | **ABRUPT (crash)** | memory-leak=True |
| 2026-05-31 23:09 | 5.3 h | 248 → 161 | (peak 552) | 552 MB | 31 | ABRUPT | memory-leak=True |

This is the **"slows down then auto-closes after a while with heavy images"** symptom — **uncontrolled here**, versus the local build's **~4.5 MB/cycle (controlled, under the 8 MB/cycle threshold)**. **4 of 15 sessions ended abruptly.**
→ **Root:** lacks the local build's **P1** (ThemeManager `themeChanged` disconnects) + **P2** (per-series `ThreadPoolExecutor` shutdown) leak fixes.

### 2. Two hard crashes — access violation `0xC0000005` (CRITICAL)
`native_fault.log` contains **two distinct access-violation crashes**, both in the **loading-overlay show/hide path** during heavy concurrency:

- **Crash 1:** `loading_spinner.show_loading → _vc_switch._show_viewer_loading_all → _pw_pipeline` **while a download subprocess was spawning** (`download_process_worker.py:148 → multiprocessing reduction.dump → popen_spawn_win32`) and **7 `zeta_boost.cache_engine._worker_loop` threads** ran.
- **Crash 2:** `_hp_modules.on_plus_button_clicked → hide_loading → _hp_layout._hide_loading_overlay` **while a socket patient-search was in flight** (`socket_client._recv_exact → search_patients_sync`) and a download was spawning.

Both route through the `QApplication.notify()` override (main.py:891) — its Python `try/except` **cannot catch a C++ access violation**, so the app hard-crashes. The two crashes are from **two different builds** (`_f11_sampler` at main.py:1156 vs 1235), i.e. the PC was updated between them; crash 2 matches the current local build's line numbers.
→ **Root:** a C++ widget-lifetime/threading hazard in the loading overlay (`loading_overlay.py` / `loading_spinner.py` / `_hp_layout._hide_loading_overlay`) when overlay show/hide **races with download-subprocess spawn + socket I/O**. The multiprocessing download-spawn under load is a known crash trigger (cf. the Proxifier spawn-crash operational note).

### 3. `btn_lang_en` AttributeError — the SAME bug fixed locally as F1 (HIGH)
`AttributeError: 'UnifiedComposer' object has no attribute 'btn_lang_en'` in `_pw_metadata.open_report_in_echo_mind`. **This is the exact defect I fixed on the local source (F1).** The other PC lacks the fix → recurring error + broken language-button path.

### 4. 111 FAST stack-drag main-thread stalls (MEDIUM)
Stalls cluster in `modules.viewer.fast.qt_viewer_bridge._log_drag_metrics_summary` during stack-drag (14:43–14:44 burst). Likely the **FAST stack-drag pressure sampler is enabled** — it must be **OFF** by default (it removed 300–500 ms mid-drag stalls); confirm env `AIPACS_FAST_STACK_PRESSURE` is unset.

### 5. `notify()` TypeErrors ×2, 1× 45123 ms socket timeout (LOW)
`TypeError: 'QApplication.notify' called with wrong argument types` (caught + logged, non-fatal). One **45123 ms socket timeout** = the **wrong-port thumbnail-hang** signature — ensure the socket client uses the socket-protocol port from `config/socket_config.json` (e.g. 50052), **not** the DICOM `port` (105) from `servers.json`.

---

## Comparison: other PC vs. local build

| Signal | **Other PC** | Local build (validated) |
|---|---|---|
| Memory leak | **+1244 MB / 3.4 h, peak 1489 MB** | ~4.5 MB/cycle (controlled) |
| Hard crashes (`0xC0000005`) | **2 (loading overlay)** | 0 (only headless VTK tests) |
| Abrupt terminations | **4 / 15 sessions** | 1 / 84 (the live session) |
| `btn_lang_en` | **present** | **fixed (F1)** |
| `0x8001010d` (COM) | 0 | 99 (benign, once/startup) |
| FAST drag stalls | **111** | pressure sampler off |

---

## Recommendation (priority order)

1. **Update the other PC to the current local source build.** It already contains the leak fixes (**P1/P2/P8**), **F1** (`btn_lang_en`), and **F2** (audio stall). This should resolve findings **1 & 3** and substantially reduce crash exposure.
2. **Loading-overlay access-violation (finding 2):** add C++ lifetime guards and defer overlay show/hide via `QTimer.singleShot(0)` so it never runs inside `notify()` event-dispatch while a download subprocess is spawning; pre-warm/serialize the multiprocessing spawn off the UI path. Test-gated.
3. **Confirm `AIPACS_FAST_STACK_PRESSURE` is OFF** (finding 4) and the **socket port config** is correct (finding 5).
4. Re-run the soak analyzer on the other PC after the update to confirm per-session RSS returns toward baseline and abrupt terminations stop.

---

## Are these already fixed in the CURRENT version? (the log is from a previous version)

Verified each finding against the current local source + my live validation:

| # | Problem (previous version) | Current version | Evidence |
|---|---|---|---|
| 1 | Memory leak +1244 MB / 3.4 h → abrupt crash | **✅ SOLVED** | Current source has P1 (theme `themeChanged` disconnects) + P2 (per-series executor shutdown) + P8 (tab-dict pop). My 6-cycle live soak = **~4.5 MB/cycle, threads stable** — the leak that drove the "auto-close" is controlled. |
| 2 | `btn_lang_en` AttributeError | **✅ SOLVED** | The old traceback fails at `ai_chat_widgets.py:2929` in `_update_lang_buttons_visibility` (via `open_report_in_echo_mind → _choose_file → switch_tab`). **My F1 guard sits at that exact method/line** (`if not hasattr(self,"btn_lang_en"): return`). Live-verified: 0 new occurrences. |
| 3 | FAST stack-drag stalls ×111 | **✅ SOLVED** | Current source gates the drag pressure sampler **OFF by default** (`_FAST_STACK_PRESSURE_ENABLED`, opt-in via env). |
| 4 | 2× access-violation crashes (loading overlay during download-spawn + socket) | **✅ NOT REPRODUCED / strongly mitigated** | My heavy live session reproduced the exact conditions (4 tabs, download subprocess spawning, overlays, socket search, rapid close) → **0 native faults**. Current `loading_overlay.hide_overlay` is guarded (try/except + `deleteLater`); `_hp_layout` callers are wrapped in try/except + `singleShot`; and the leak (the documented stressor that *shortens time-to-crash*) is now controlled. **Residual:** the underlying C++ overlay-vs-spawn race isn't *provably* eliminated — recommend a `QTimer.singleShot(0)` guard so overlay show/hide never runs inside `notify()` dispatch during a spawn (full certainty). |
| 5 | 45123 ms socket timeout (wrong port) | **✅ Addressed** | Current `socket_client` resolves the port via `get_socket_config()` + a time-deadline recv (not the DICOM port). Live thumbnails 237–563 ms, no 45 s hang. |
| 6 | `notify()` TypeErrors ×2 | ⚠️ **Still present (minor)** | The `notify` override is unchanged; the TypeErrors are **caught + logged (non-fatal)** — log noise, not a crash. |

**Bottom line:** the four serious problems (memory leak, `btn_lang_en` crash, FAST stalls, socket timeout) **are solved in the current build**, and the access-violation crashes **do not reproduce** under the same heavy workload now that the leak stressor is controlled. The only residual items are the *underlying* overlay C++ race (recommend a one-line `singleShot` hardening for certainty) and the minor caught `notify()` TypeError noise. **→ Updating the other PC to the current build is expected to resolve the crashes and the auto-close behavior.**
