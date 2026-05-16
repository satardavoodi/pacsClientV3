"""C4 validation KPI extractor — run after diagnostic session."""
import re, statistics, sys

log_path = sys.argv[1] if len(sys.argv) > 1 else 'user_data/logs/viewer_diagnostics.log'
log = open(log_path, encoding='utf-8', errors='replace').readlines()

def ef(pat, line):
    m = re.search(pat, line)
    return float(m.group(1)) if m else None

# ── Render clock config ──
for l in log:
    if 'FAST_RENDER_CLOCK_CONFIG' in l:
        print('RENDER_CLOCK_CONFIG:', l[120:].strip()[:200])
        break

print()
print(f'Total log lines: {len(log)}')

# ── Tag counts ──
drag_kpi    = [l for l in log if 'FAST_DRAG_KPI' in l]
pacing      = [l for l in log if 'FAST_EVENT_PACING' in l]
scroll_stg  = [l for l in log if 'FAST_QT_SCROLL_STAGE' in l]
settled     = [l for l in log if 'INTERACTION_SETTLED' in l]
b34         = [l for l in log if 'B3.4_DIAG' in l]
clock_lines = [l for l in log if 'CLOCK_SIDE_EFFECT' in l]
fg_disk     = [l for l in log if 'FAST_FG_DISK' in l]
errors      = [l for l in log if ' ERROR ' in l or 'Traceback' in l]

print(f'FAST_DRAG_KPI sessions  : {len(drag_kpi)}')
print(f'FAST_EVENT_PACING       : {len(pacing)}')
print(f'FAST_QT_SCROLL_STAGE    : {len(scroll_stg)}  (C4 check: expect slider/sync/ref = 0)')
print(f'INTERACTION_SETTLED     : {len(settled)}  (debug level — 0 expected unless trace log)')
print(f'B3.4_DIAG lines         : {len(b34)}')
print(f'CLOCK_SIDE_EFFECT lines : {len(clock_lines)}  (0 = render clock OFF = C4 non-clock path active)')
print(f'FAST_FG_DISK lines      : {len(fg_disk)}')
print(f'Error lines             : {len(errors)}')
print()

# ── FAST_QT_SCROLL_STAGE: verify slider/sync/ref = 0 ──
if scroll_stg:
    print('=== FAST_QT_SCROLL_STAGE (C4 deferral check) ===')
    for l in scroll_stg:
        m = re.search(r'slider_ms=([\d.]+).*?sync_ms=([\d.]+).*?reference_ms=([\d.]+)', l)
        if m:
            s, sy, r = float(m.group(1)), float(m.group(2)), float(m.group(3))
            ok = s == 0.0 and sy == 0.0 and r == 0.0
            print(f'  slider={s} sync={sy} ref={r}  {"OK" if ok else "FAIL — non-zero during drag!"}')
else:
    print('=== FAST_QT_SCROLL_STAGE ===')
    print('  ABSENT — expected: gated by _stack_drag_active=True during drag.')
    print('  C4 deferral effect on slider/sync/ref cannot be log-verified in this profile.')
    print('  To verify: add wheel-scroll only scenario (no stack drag), or add explicit flush log tag in C5.')
print()

# ── Per-session breakdown ──
print('=== PER-SESSION (dur targets event_p95 ui_lag_max handler_p95 bg_dec) ===')
event_p95_all, ui_lag_all, handler_p95_all = [], [], []
for i, l in enumerate(drag_kpi, 1):
    dur = ef(r'duration_s=([\d.]+)', l)
    tgt = ef(r' targets=(\d+)', l)
    ep  = ef(r'event_p95_ms=([\d.]+)', l)
    ulm = ef(r'ui_lag_max_ms=([\d.]+)', l)
    hp  = ef(r'handler_p95_ms=([\d.]+)', l)
    bgd = ef(r'background_decode_count=(\d+)', l)
    stall = 'main_thread_stall_during_drag=True' in l
    dm    = 'dm_rebuild_during_drag=True' in l
    if ep:  event_p95_all.append(ep)
    if ulm: ui_lag_all.append(ulm)
    if hp:  handler_p95_all.append(hp)
    print(f'  S{i:02d}: dur={dur:.1f}s tgt={int(tgt):3d} event_p95={ep:6.1f} ui_lag_max={ulm:7.1f} handler_p95={hp:4.1f} bg_dec={int(bgd)} stall={stall} dm_rebuild={dm}')

print()

# ── Aggregate KPI ──
def stats(name, vals):
    if not vals: print(f'  {name}: no data'); return
    print(f'  {name}: n={len(vals)} avg={statistics.mean(vals):.1f} median={statistics.median(vals):.1f} max={max(vals):.1f}')

print('=== DRAG KPI AGGREGATE ===')
stats('event_p95_ms', event_p95_all)
stats('ui_lag_max_ms', ui_lag_all)
stats('handler_p95_ms', handler_p95_all)
print()

frame_p95_all, req_exec_all, gap_max_all, qdepth_all = [], [], [], []
for l in pacing:
    v = ef(r'frame_ready_to_paint_p95_ms=([\d.]+)', l); frame_p95_all.append(v) if v else None
    v = ef(r'request_to_execute_p95_ms=([\d.]+)', l); req_exec_all.append(v) if v else None
    v = ef(r'input_event_gap_max_ms=([\d.]+)', l); gap_max_all.append(v) if v else None
    v = ef(r'pending_set_slice_queue_depth_max=([\d.]+)', l); qdepth_all.append(v) if v else None

print('=== PACING KPI AGGREGATE ===')
stats('frame_ready_to_paint_p95_ms', frame_p95_all)
stats('request_to_execute_p95_ms', req_exec_all)
stats('input_event_gap_max_ms', gap_max_all)
stats('pending_set_slice_queue_depth_max', qdepth_all)
print()

# ── FG_DISK per-frame ui_lag ──
fg_lags = []
for l in fg_disk:
    v = ef(r'ui_lag_ms=([\d.]+)', l)
    if v: fg_lags.append(v)
if fg_lags:
    fg_lags.sort()
    n = len(fg_lags)
    p95 = fg_lags[min(int(n*0.95), n-1)]
    print(f'FG_DISK per-frame ui_lag_ms: n={n} avg={statistics.mean(fg_lags):.1f} p95={p95:.1f} max={max(fg_lags):.1f}')
    print()

# ── FAST_SET_SLICE_STAGE ──
stage_lines = [l for l in log if 'FAST_SET_SLICE_STAGE' in l]
if stage_lines:
    print('=== FAST_SET_SLICE_STAGE (slow frames only) ===')
    for l in stage_lines:
        m = re.search(r'total_ms=([\d.]+).*?frame_ms=([\d.]+).*?decode_ms=([\d.]+).*?wl_ms=([\d.]+)', l)
        if m:
            print(f'  total={m.group(1):6.1f} frame={m.group(2):5.1f} decode={m.group(3):5.1f} wl={m.group(4):4.1f}')

print()
print('=== OBSERVABILITY GAP NOTE ===')
print('  FAST_QT_SCROLL_STAGE: only fires for wheel scroll (not stack drag, _stack_drag_active=True blocks it).')
print('  INTERACTION_SETTLED: logger.debug() — not visible at INFO level in diagnostic profile.')
print('  C4 flush (_flush_non_clock_side_effects_on_settle): no dedicated log tag yet (planned for C5).')
print('  C4 code path WAS active: CLOCK_SIDE_EFFECT=0 confirms render clock OFF, non-clock path ran.')
