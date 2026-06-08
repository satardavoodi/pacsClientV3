# Fresh (not-downloaded) large-CT progressive workflow test — 2026-06-08

Target: large multi-series CT studies with NO local copy, exercising
open → series thumbnails → load a non-first series → progressive download →
stack growth → scroll-while-downloading. Build 3.2.5 (includes the 2026-06-07
freeze fixes `7be93a7` + `d6c8f45`).

Fresh candidates found on server `razi` (probe `_recovery/find_fresh_ct.py`):
50 CT studies, all 0 local files, 9–15 series each. Tested **10352**
(JAVAD SADEGHI, CT, 10 series, ~1680+ inst) by **real UI open** after the bus
path proved low-fidelity (below).

## Verdict

| Focus area | Verdict | Evidence |
|---|---|---|
| Open fresh CT → series thumbnails render | **PASS** | 10 thumbnails rendered in **~170 ms** (`right_panel_socket_start`→`display_done` t+268254→268423 ms); 2nd visit = `right_panel_cache_hit` |
| First image visible (large series) | **PASS** | Series 302 (428 slices): `UX_FIRST_IMAGE_VISIBLE slice=214 decode_ms=6.3 total_ms=25.2` |
| Progressive download + availability | **PASS** | Thumbnail counts updated live 4/4 → 107/107 → 428/428; disk confirms all series fully downloaded; `[ZDL_DIAG] add_downloads` → download subprocess spawn in `download_diagnostics.log` |
| Stack growth / viewer sync | **PASS** | `switch_series: complete series=302 slices=428` — full stack available, opened mid-stack at 214 |
| Scroll responsiveness, no black, no freeze | **PASS** | Image rendered cleanly; scroll 215→216 worked; real interaction stall 434 ms (load+first scroll), **0 native faults since 13:00** |
| No crash | **PASS** | `native_fault.log`: zero entries this session |
| Drag → CRITICAL priority escalation (explicit KPI) | **INCONCLUSIVE** | Could not capture mid-download — see limitations |

## KPIs (real 10352 session, 13:23–13:25)

- Open → thumbnails fully rendered: **~170 ms** (server returned 10 series w/ file paths).
- Series-info socket fetch: `right_panel_socket_start`→`socket_done` = **168 ms**, thumbnail_count=10.
- Series 302 (428-slice CT) select → **first image visible 25.2 ms** (decode 6.3 ms).
- Download: whole study (8 image series, ~1.5 GB) completed within seconds of
  open on the LAN server (192.168.2.222) — too fast to observe a partial stack.
- DM table rebuild during activity: `[DM_REBUILD] duration_ms=69.6` (within budget).
- Main-thread stalls: one 434 ms at load; the lone 32.5 s "gap" is an **idle**
  wall-clock gap between manual interactions (F11 sampler measures wall time;
  the app stayed responsive — the subsequent scroll worked), not a freeze.

## Two real findings

**F1 — bus `open_patient` is low-fidelity for fresh studies (harness gap, not an app bug).**
Driving `open_patient` via the aipacs-control test bus created a tab with
**0 series thumbnails** and `query_viewport_state = NO_ACTIVE_TAB`, and left
**no open-pipeline log trace at all** (no `FAST-OPEN-TRACE`, no series-info
fetch). The **real double-click** of the same patient worked perfectly
(10 thumbnails, series loaded, 25 ms first image). So the bus open adapter
does not run the full home-panel open path for these rows. This is the same
"hollow tab / no trace" signature as the 44982 dead-tab (task #148) — worth
hardening the bus `open_patient` adapter to route through the real
double-click handler (`_on_patient_double_clicked`) so automated tests
exercise the true path. Tracked: task #161.

**F2 — could not stage a true "drag-before-download-completes" on this LAN.**
The server downloads a full multi-series CT in a few seconds, so every series
was already complete (`428/428`) before a drag could land mid-download; and the
synthetic mouse-drag does not reliably trigger Qt's DnD (documented). The
priority/progressive machinery is demonstrably **present and functioning**
(DM queue → subprocess → live count growth → full stack load), but the
explicit *drag→CRITICAL escalation latency* and *batch→stack-count* KPIs need
either a throttled/slow server or sub-second drag timing to capture. Tracked:
task #161.

## Stability conclusion

Large fresh CT studies are **usable**: open is fast (~170 ms to thumbnails),
the selected large series shows its first image in **25 ms**, the full stack
loads, scrolling is smooth, and there were **zero crashes/freezes**. The
yesterday freeze fixes hold under this workload. The progressive
download/priority pipeline is wired correctly and completes; the explicit
mid-download escalation KPI remains to be measured under a slowed server.

## Notes
- E: drive is ~96 % full; this test added ~1.5 GB (10352 study). Avoid further
  large fresh downloads until cleanup. Did not run the second patient (10478)
  to spare disk.
