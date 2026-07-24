"""QtWebEngine cold-boot benchmark (OPT-41 follow-up, 2026-07-23).

Measures the REAL cost phases of the Chromium boot that froze the GUI thread
(prewarm `_construct_warm_view`): DLL import, QApplication, first
QWebEngineView construction + setUrl (the synchronous GUI-thread block), and
first loadFinished (full readiness) — per flag variant, each in a FRESH
process (Chromium global init is once-per-process, so in-process A/B is
impossible).

Usage:
  parent:  python tools/dev/bench_webengine_boot.py --out results.json
  child:   python tools/dev/bench_webengine_boot.py --child --flags "..." [--nosandbox]

The child never shows a window (identical to the prewarm path).
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def child_main(flags: str, nosandbox: bool) -> None:
    result = {"flags": flags, "nosandbox": bool(nosandbox)}
    if flags:
        os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = flags
    if nosandbox:
        os.environ["QTWEBENGINE_DISABLE_SANDBOX"] = "1"

    t0 = time.perf_counter()
    from PySide6.QtCore import Qt, QTimer, QUrl  # noqa: E402
    from PySide6.QtWidgets import QApplication  # noqa: E402
    result["qtwidgets_import_ms"] = round((time.perf_counter() - t0) * 1000, 1)

    t1 = time.perf_counter()
    import PySide6.QtWebEngineCore  # noqa: F401,E402
    import PySide6.QtWebEngineWidgets  # noqa: F401,E402
    result["webengine_dll_import_ms"] = round((time.perf_counter() - t1) * 1000, 1)

    t2 = time.perf_counter()
    try:
        QApplication.setAttribute(Qt.AA_ShareOpenGLContexts, True)
    except Exception:
        pass
    app = QApplication(sys.argv)
    result["qapplication_ms"] = round((time.perf_counter() - t2) * 1000, 1)

    from PySide6.QtWebEngineWidgets import QWebEngineView  # noqa: E402

    t3 = time.perf_counter()
    view = QWebEngineView()          # hidden — never shown (same as prewarm)
    view.setUrl(QUrl("about:blank"))
    result["construct_seturl_ms"] = round((time.perf_counter() - t3) * 1000, 1)

    state = {"done": False}

    def _on_load(ok):
        if not state["done"]:
            state["done"] = True
            result["load_finished_ms"] = round((time.perf_counter() - t3) * 1000, 1)
            result["ok"] = bool(ok)
            QTimer.singleShot(100, app.quit)

    view.loadFinished.connect(_on_load)

    def _timeout():
        if not state["done"]:
            state["done"] = True
            result["load_finished_ms"] = -1
            result["ok"] = False
            app.quit()

    QTimer.singleShot(90_000, _timeout)
    app.exec()
    result["total_ms"] = round((time.perf_counter() - t0) * 1000, 1)
    print("BENCH_JSON:" + json.dumps(result), flush=True)


VARIANTS = [
    # (name, flags, nosandbox)
    ("warmup_discard", "", False),  # first run pays OS file-cache cold; discarded
    ("baseline", "", False),
    ("baseline2", "", False),
    ("nogpu", "--disable-gpu --disable-gpu-compositing", False),
    ("slim", ("--disable-gpu --disable-gpu-compositing --disable-extensions "
              "--disable-background-networking --disable-sync --disable-breakpad "
              "--disable-component-update --disable-domain-reliability --no-pings "
              "--disable-speech-api --renderer-process-limit=2 "
              "--disable-features=MediaRouter,DialMediaRouteProvider,Translate,"
              "OptimizationHints,InterestFeedContentSuggestions"), False),
    ("slim_keepgpu", ("--disable-extensions --disable-background-networking "
                      "--disable-sync --disable-breakpad --disable-component-update "
                      "--disable-domain-reliability --no-pings --disable-speech-api "
                      "--renderer-process-limit=2 "
                      "--disable-features=MediaRouter,DialMediaRouteProvider,Translate,"
                      "OptimizationHints,InterestFeedContentSuggestions"), False),
    ("slim_nosandbox", ("--disable-gpu --disable-gpu-compositing --disable-extensions "
                        "--disable-background-networking --disable-sync --disable-breakpad "
                        "--disable-component-update --disable-domain-reliability --no-pings "
                        "--disable-speech-api --renderer-process-limit=2"), True),
]


def parent_main(out_path: str) -> None:
    py = sys.executable
    results = []
    for name, flags, nosandbox in VARIANTS:
        cmd = [py, os.path.abspath(__file__), "--child", "--flags", flags]
        if nosandbox:
            cmd.append("--nosandbox")
        t0 = time.perf_counter()
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120,
                                  cwd=REPO)
            wall = round((time.perf_counter() - t0) * 1000, 1)
            data = None
            for line in (proc.stdout or "").splitlines():
                if line.startswith("BENCH_JSON:"):
                    data = json.loads(line[len("BENCH_JSON:"):])
                    break
            entry = {"variant": name, "wall_ms": wall,
                     "returncode": proc.returncode, "data": data}
            if data is None:
                entry["stderr_tail"] = (proc.stderr or "")[-500:]
        except subprocess.TimeoutExpired:
            entry = {"variant": name, "wall_ms": -1, "returncode": None,
                     "data": None, "error": "timeout 120s"}
        results.append(entry)
        print(f"[bench] {name}: {json.dumps(entry.get('data') or entry)}", flush=True)
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(results, fh, indent=2)
    print(f"[bench] wrote {out_path}", flush=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--child", action="store_true")
    ap.add_argument("--flags", default="")
    ap.add_argument("--nosandbox", action="store_true")
    ap.add_argument("--out", default="webengine_bench.json")
    a = ap.parse_args()
    if a.child:
        child_main(a.flags, a.nosandbox)
    else:
        parent_main(a.out)
