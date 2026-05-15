import re
from pathlib import Path
from statistics import median

viewer_extract = Path(r"c:\Users\Dr.Alizadeh\AppData\Roaming\Code\User\workspaceStorage\bac41359a2fce62d128365c243864dda\GitHub.copilot-chat\chat-session-resources\e56871da-d73d-4c97-80f2-1e815d28f015\call_MEXWi4zGCjknIVM3uUJjhRNN__vscode-1778655853519\content.txt")
download_extract = Path(r"c:\Users\Dr.Alizadeh\AppData\Roaming\Code\User\workspaceStorage\bac41359a2fce62d128365c243864dda\GitHub.copilot-chat\chat-session-resources\e56871da-d73d-4c97-80f2-1e815d28f015\call_FvMsdp677xLajmEoUR8Hkruo__vscode-1778655853516\content.txt")

vtxt = viewer_extract.read_text(encoding="utf-8", errors="ignore") if viewer_extract.exists() else ""
dtxt = download_extract.read_text(encoding="utf-8", errors="ignore") if download_extract.exists() else ""

def vals(pat, txt):
    out = []
    for m in re.finditer(pat, txt):
        try:
            out.append(float(m.group(1)))
        except Exception:
            pass
    return out

def p95(a):
    if not a:
        return None
    s = sorted(a)
    return s[int(round((len(s)-1)*0.95))]

def fm(x):
    return "n/a" if x is None else f"{x:.3f}"

print("41189 viewer hits:", len(re.findall(r"41189", vtxt)))
print("41189 download hits:", len(re.findall(r"41189", dtxt)))

print("series=203 in viewer extract:", len(re.findall(r"series=203", vtxt)))
print("series=203 in download extract:", len(re.findall(r"series=203", dtxt)))

ui_lag_max = vals(r"\[FAST_DRAG_KPI\].*?ui_lag_max_ms=([0-9.]+)", vtxt)
handler_p95 = vals(r"\[FAST_DRAG_KPI\].*?handler_p95_ms=([0-9.]+)", vtxt)
ej_p95 = vals(r"\[FAST_EVENT_PACING\].*?event_jitter_p95_ms=([0-9.]+)", vtxt)
fp_p95 = vals(r"\[FAST_EVENT_PACING\].*?frame_present_interval_p95_ms=([0-9.]+)", vtxt)
iq_p95 = vals(r"\[FAST_EVENT_PACING\].*?implied_queue_wait_p95_ms=([0-9.]+)", vtxt)
fg_ui = vals(r"\[FAST_FG_DISK\].*?ui_lag_ms=([0-9.]+)", vtxt)
fg_frame = vals(r"\[FAST_FG_DISK\].*?frame_total_ms=([0-9.]+)", vtxt)

print("FAST_DRAG_KPI count:", len(ui_lag_max))
print("ui_lag_max_ms p50/p95/max:", fm(median(ui_lag_max) if ui_lag_max else None), fm(p95(ui_lag_max)), fm(max(ui_lag_max) if ui_lag_max else None))
print("handler_p95_ms p50/p95/max:", fm(median(handler_p95) if handler_p95 else None), fm(p95(handler_p95)), fm(max(handler_p95) if handler_p95 else None))
print("event_jitter_p95_ms p50/p95/max:", fm(median(ej_p95) if ej_p95 else None), fm(p95(ej_p95)), fm(max(ej_p95) if ej_p95 else None))
print("frame_present_interval_p95_ms p50/p95/max:", fm(median(fp_p95) if fp_p95 else None), fm(p95(fp_p95)), fm(max(fp_p95) if fp_p95 else None))
print("implied_queue_wait_p95_ms p50/p95/max:", fm(median(iq_p95) if iq_p95 else None), fm(p95(iq_p95)), fm(max(iq_p95) if iq_p95 else None))
print("FAST_FG_DISK ui_lag_ms p50/p95/max:", fm(median(fg_ui) if fg_ui else None), fm(p95(fg_ui)), fm(max(fg_ui) if fg_ui else None))
print("FAST_FG_DISK frame_total_ms p50/p95/max:", fm(median(fg_frame) if fg_frame else None), fm(p95(fg_frame)), fm(max(fg_frame) if fg_frame else None))

retro_capped = len(re.findall(r"RETRO_META_SYNC_CAPPED", vtxt))
retro_throttled = len(re.findall(r"RETRO_META_SYNC_THROTTLED", vtxt))
old_pg = vals(r"phase=deferred_meta_sync.*?post_grow_signal_ms=([0-9.]+)", vtxt)

print("RETRO_META_SYNC_CAPPED count:", retro_capped)
print("RETRO_META_SYNC_THROTTLED count:", retro_throttled)
print("deferred_meta_sync post_grow_signal_ms max:", fm(max(old_pg) if old_pg else None))

dm_dur = vals(r"\[DM_REBUILD\].*?event=exit.*?duration_ms=([0-9.]+)", dtxt)
series_dl = vals(r"series-summary series=203 downloaded=([0-9.]+)", dtxt)
series_tot = vals(r"series-summary series=203 .*? total=([0-9.]+)", dtxt)

print("DM_REBUILD exit count:", len(dm_dur))
print("DM_REBUILD duration max:", fm(max(dm_dur) if dm_dur else None))
print("series-summary downloaded last/max:", (int(series_dl[-1]), int(max(series_dl))) if series_dl else "n/a")
print("series-summary total last/max:", (int(series_tot[-1]), int(max(series_tot))) if series_tot else "n/a")
