"""
Temporary script: parse series=7 drag diagnostics from viewer_diagnostics.log
"""
import re

log = r'e:\ai-pacs\ai-pacs codes\ai-pacs beta version\user_data\logs\viewer_diagnostics.log'
with open(log, encoding='utf-8', errors='replace') as f:
    lines = f.readlines()

print("=== Series 7 FAST_EVENT_PACING ===")
for i, l in enumerate(lines):
    if 'series=7' in l and 'FAST_EVENT_PACING' in l:
        def g(p): m = re.search(p, l); return m[1] if m else '?'
        dur = g(r'duration_s=([\d.]+)')
        tgts = g(r' targets=(\d+) ')
        gap50 = g(r'input_event_gap_p50_ms=([\d.]+)')
        gap95 = g(r'input_event_gap_p95_ms=([\d.]+)')
        same = g(r'same_slice_rejected=(\d+)')
        sched = g(r'scheduler_rejected=(\d+)')
        rep50 = g(r'qt_repaint_delay_p50_ms=([\d.]+)')
        rep95 = g(r'qt_repaint_delay_p95_ms=([\d.]+)')
        cls = g(r'queue_wait_classification=(\S+)')
        raw = g(r'raw_input_event_count=(\d+)')
        acc = g(r'accepted_input_event_count=(\d+)')
        print(f"  Ln{i+1}: dur={dur}s tgts={tgts} raw={raw} acc={acc} same_rej={same} sched_rej={sched}")
        print(f"         gap_p50={gap50}ms gap_p95={gap95}ms repaint_p50={rep50}ms repaint_p95={rep95}ms class={cls}")

print()
print("=== Series 7 B3.8_SCROLL (every 20th frame) ===")
for i, l in enumerate(lines):
    if 'series=7' in l and 'B3.8_SCROLL' in l:
        def g(p): m = re.search(p, l); return m[1] if m else '?'
        frame = g(r'frame=(\d+)')
        sl = g(r'slice=(\d+)')
        tot = g(r'total_ms=([\d.]+)')
        px = g(r'px_cache=(\d+)')
        print(f"  Ln{i+1}: frame={frame} slice={sl} total_ms={tot} px_cache={px}")
