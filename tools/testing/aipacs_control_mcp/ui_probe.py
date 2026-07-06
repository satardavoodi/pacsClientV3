# -*- coding: utf-8 -*-
"""ui_probe — fast UI validation: catches sub-second glitches around bus commands.

Problem this solves: external screenshots are ~1/s round-trips; flicker, blank
frames, missing tab thumbnails and transient states vanish before they can be
seen. This module runs a LOCAL capture thread (mss, ~20-30 fps, downscaled
ring buffer) on the app window and, for every test command, persists:

  before.png            last frame before the command was sent
  first_change.png      first frame whose diff vs `before` exceeds threshold
                        (first UI response)
  worst_event.png       frame at the largest transient (flicker/blank candidate)
  stable.png            first frame of the final settled state
  clip.gif              the whole window: ~0.5 s before → stable (or timeout)
  tab_strip.png         crop of the patient-tab header strip (tab-thumbnail check)
  record JSON           timings + per-frame diff/luma series + glitch verdicts

Glitch heuristics (gray frame series):
  first_response_ms     first diff(prev) > NOISE after t_send
  stable_ms             start of the first window of STABLE_K frames with
                        diff(prev) < NOISE (after first response)
  flicker               frame F differs strongly from BOTH neighbours while
                        prev≈next (A→B→A within ~3 frames) → transient artifact
  blank_dip             region mean-luma drops >35% vs before, then recovers
Regions tracked separately: full window, right panel (home thumbnails),
tab strip, viewport area.
"""
from __future__ import annotations

import json
import shutil
import threading
import time
from collections import deque
from pathlib import Path
from typing import Any, Optional

import numpy as np

NOISE = 1.2          # mean-abs-gray-diff considered "no change" (downscaled)
STABLE_K = 8         # consecutive quiet frames = stable
FLICKER_T = 6.0      # transient must exceed this vs both neighbours

# Regions as fractions of the captured window (maximized layout).
REGIONS = {
    "full":      (0.00, 0.00, 1.00, 1.00),
    "tab_strip": (0.08, 0.00, 0.66, 0.075),
    "right_panel": (0.875, 0.12, 1.00, 0.97),
    "viewport":  (0.16, 0.17, 0.58, 0.95),
}


def _now() -> float:
    return time.perf_counter()


class CaptureLoop:
    """Continuous downscaled window capture into a ring buffer."""

    def __init__(self, bbox: dict, fps_target: float = 25.0, keep_s: float = 14.0):
        self.bbox = bbox  # mss monitor dict: left/top/width/height (physical px)
        self.fps_target = fps_target
        maxlen = int(keep_s * fps_target * 1.3)
        self.frames: deque = deque(maxlen=maxlen)  # (t, color[::2] uint8 BGR)
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self.actual_fps = 0.0

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="ui-probe-capture",
                                        daemon=True)
        self._thread.start()

    def _run(self) -> None:
        import mss
        period = 1.0 / self.fps_target
        n, t_fps = 0, _now()
        with mss.mss() as sct:
            while not self._stop.is_set():
                t0 = _now()
                try:
                    raw = sct.grab(self.bbox)  # BGRA
                    arr = np.frombuffer(raw.rgb, dtype=np.uint8).reshape(
                        raw.height, raw.width, 3)[::2, ::2].copy()
                    self.frames.append((t0, arr))
                except Exception:
                    pass
                n += 1
                if t0 - t_fps >= 2.0:
                    self.actual_fps = n / (t0 - t_fps)
                    n, t_fps = 0, t0
                dt = period - (_now() - t0)
                if dt > 0:
                    time.sleep(dt)

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2.0)

    def window(self, t_from: float, t_to: float) -> list:
        return [(t, f) for (t, f) in list(self.frames) if t_from <= t <= t_to]


def _gray(frame: np.ndarray) -> np.ndarray:
    return frame.mean(axis=2)


def _crop(frame: np.ndarray, frac) -> np.ndarray:
    h, w = frame.shape[:2]
    x0, y0, x1, y1 = frac
    return frame[int(y0 * h):int(y1 * h), int(x0 * w):int(x1 * w)]


def _save_png(path: Path, frame: np.ndarray) -> None:
    from PIL import Image
    # mss .rgb is already RGB-ordered — no channel flip.
    Image.fromarray(frame if frame.ndim == 3 else frame.astype(np.uint8)).save(str(path))


def _agent_artifacts_dir() -> Path:
    try:
        from modules.EchoMind.secretary.background.verification import artifacts_dir
        return Path(artifacts_dir())
    except Exception:
        try:
            from PacsClient.utils.data_paths import ECHOMIND_DIR
            d = Path(ECHOMIND_DIR) / "agent_artifacts"
        except Exception:
            d = Path.home() / ".aipacs_agent_artifacts"
        d.mkdir(parents=True, exist_ok=True)
        return d


def _save_gif(path: Path, frames: list, fps: int = 10, max_w: int = 760) -> None:
    from PIL import Image
    if not frames:
        return
    step = max(1, round(len(frames) / (fps * max(0.001, frames[-1][0] - frames[0][0]) or 1)))
    imgs = []
    for t, f in frames[::step]:
        im = Image.fromarray(f)
        if im.width > max_w:
            im = im.resize((max_w, int(im.height * max_w / im.width)))
        imgs.append(im.convert("P", palette=Image.ADAPTIVE, colors=128))
    if imgs:
        imgs[0].save(str(path), save_all=True, append_images=imgs[1:],
                     duration=int(1000 / fps), loop=0, optimize=True)


def analyze(frames: list, t_send: float) -> dict:
    """Per-region diff/luma series + glitch verdicts."""
    out: dict[str, Any] = {"n_frames": len(frames)}
    if len(frames) < 3:
        return out
    grays = {name: [ _gray(_crop(f, frac)) for (_t, f) in frames ]
             for name, frac in REGIONS.items()}
    times = [t for (t, _f) in frames]
    base_i = max([i for i, t in enumerate(times) if t <= t_send] or [0])
    out["pre_frames"] = base_i + 1
    for name in REGIONS:
        g = grays[name]
        diffs = [0.0] + [float(np.abs(g[i] - g[i - 1]).mean()) for i in range(1, len(g))]
        luma = [float(x.mean()) for x in g]
        base_luma = luma[base_i]
        first_resp = None
        stable = None
        quiet = 0
        for i in range(base_i + 1, len(g)):
            if first_resp is None and diffs[i] > NOISE:
                first_resp = i
            if first_resp is not None:
                if diffs[i] < NOISE:
                    quiet += 1
                    if quiet >= STABLE_K and stable is None:
                        stable = i - STABLE_K + 1
                else:
                    quiet = 0
        flickers = []
        for i in range(base_i + 1, len(g) - 1):
            d_prev, d_next = diffs[i], float(np.abs(g[i + 1] - g[i]).mean())
            around = float(np.abs(g[i + 1] - g[i - 1]).mean())
            if d_prev > FLICKER_T and d_next > FLICKER_T and around < FLICKER_T * 0.45:
                flickers.append({"i": i, "ms": round((times[i] - t_send) * 1000, 1),
                                 "mag": round(d_prev, 1)})
        dips = []
        for i in range(base_i + 1, len(g)):
            if base_luma > 8 and luma[i] < base_luma * 0.65:
                dips.append({"i": i, "ms": round((times[i] - t_send) * 1000, 1),
                             "luma": round(luma[i], 1), "base": round(base_luma, 1)})
        out[name] = {
            "first_response_ms": (round((times[first_resp] - t_send) * 1000, 1)
                                  if first_resp is not None else None),
            "stable_ms": (round((times[stable] - t_send) * 1000, 1)
                          if stable is not None else None),
            "flicker_events": flickers[:6],
            "blank_dips": dips[:4],
            "max_diff": round(max(diffs[base_i + 1:] or [0.0]), 1),
            "diffs_ms": [[round((times[i] - t_send) * 1000), round(diffs[i], 1)]
                         for i in range(max(0, base_i - 2), len(g), 2)],
        }
    return out


class UiProbe:
    """Wraps bus commands with capture + analysis + artifact persistence."""

    def __init__(self, client, out_dir: Path, fps: float = 25.0):
        self.client = client
        self.out = Path(out_dir)
        self.out.mkdir(parents=True, exist_ok=True)
        self.artifacts = _agent_artifacts_dir()
        self.records: list[dict] = []
        bbox = self._app_bbox()
        self.loop = CaptureLoop(bbox, fps_target=fps)
        self.loop.start()
        time.sleep(0.6)  # warm the buffer

    @staticmethod
    def _app_bbox() -> dict:
        import lifecycle
        best, area = None, -1
        windows = list(lifecycle._app_windows())
        if not windows:
            try:
                from pywinauto import Desktop
                windows = [
                    w for w in Desktop(backend="uia").windows()
                    if "AIPacs" in (w.window_text() or "")
                    or "AI-PACS" in (w.window_text() or "")
                ]
            except Exception:
                windows = []
        for w in windows:
            try:
                r = w.rectangle()
                a = r.width() * r.height()
                if a > area:
                    best, area = r, a
            except Exception:
                continue
        if best is None:
            raise RuntimeError("app window not found")
        return {"left": best.left, "top": best.top,
                "width": best.width(), "height": best.height()}

    def run(self, label: str, action: str, entities: dict | None = None,
            observe_s: float = 5.0, timeout_ms: int = 60000) -> dict:
        d = self.out / label
        d.mkdir(exist_ok=True)
        t_send = _now()
        wall_send = time.time()
        try:
            reply = self.client.send(action, entities or {}, timeout_ms=timeout_ms)
        except Exception as exc:
            reply = {"ok": False, "error_code": "TRANSPORT", "message": str(exc)}
        t_reply = _now()
        time.sleep(observe_s)
        frames = self.loop.window(t_send - 0.6, t_send + observe_s)
        rec: dict[str, Any] = {
            "label": label, "action": action, "entities": entities or {},
            "wall_send": wall_send,
            "ok": reply.get("ok"), "error_code": reply.get("error_code"),
            "message": reply.get("message"),
            "reply": reply,
            "bus_elapsed_ms": reply.get("elapsed_ms"),
            "reply_roundtrip_ms": round((t_reply - t_send) * 1000, 1),
            "capture_fps": round(self.loop.actual_fps, 1),
        }
        try:
            a = analyze(frames, t_send)
            rec["analysis"] = a
            artifact_paths: dict[str, str] = {}

            def save_named(name: str, frame: np.ndarray) -> Path:
                local = d / f"{name}.png"
                _save_png(local, frame)
                artifact = self.artifacts / f"{time.strftime('%Y%m%d_%H%M%S')}_{label}_{name}.png"
                try:
                    shutil.copy2(str(local), str(artifact))
                    artifact_paths[name] = str(artifact)
                except Exception:
                    artifact_paths[name] = str(local)
                return local

            # artifacts
            times = [t for t, _ in frames]
            base_i = max([i for i, t in enumerate(times) if t <= t_send] or [0])
            save_named("before", frames[base_i][1])
            full = a.get("full", {})
            fr = full.get("first_response_ms")
            if fr is not None:
                i_fr = min(range(len(times)),
                           key=lambda i: abs((times[i] - t_send) * 1000 - fr))
                save_named("first_change", frames[i_fr][1])
            st = full.get("stable_ms")
            i_st = (min(range(len(times)),
                        key=lambda i: abs((times[i] - t_send) * 1000 - st))
                    if st is not None else len(frames) - 1)
            save_named("stable", frames[i_st][1])
            ev = (full.get("flicker_events") or full.get("blank_dips") or [])
            if ev:
                save_named("worst_event", frames[ev[0]["i"]][1])
            save_named("tab_strip", _crop(frames[i_st][1], REGIONS["tab_strip"]))
            ts_crop = _gray(_crop(frames[i_st][1], REGIONS["tab_strip"]))
            rec["tab_strip_std"] = round(float(ts_crop.std()), 1)
            rec["agent_artifacts"] = artifact_paths
            _save_gif(d / "clip.gif", frames, fps=10)
        except Exception as exc:  # noqa: BLE001
            rec["analysis_error"] = repr(exc)
        self.records.append(rec)
        with open(self.out / "records.json", "w", encoding="utf-8") as f:
            json.dump(self.records, f, indent=1, default=str)
        return rec

    def close(self) -> None:
        self.loop.stop()


__all__ = ["UiProbe", "CaptureLoop", "analyze", "REGIONS"]
