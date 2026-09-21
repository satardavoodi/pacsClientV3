"""Synthetic offscreen cost audit; not a GUI, clinical, or release acceptance gate.

Compare the two thumbnail classes at HEAD with the current worktree in memory.
No checkout changes, DICOM inputs, database access, downloads, or live-app control.
The surrounding helpers are shared current code, so this is a class-level comparison,
not a historical application benchmark. Run from the repository root with its venv.
"""
from __future__ import annotations

import ast
import gc
import json
import logging
import os
from pathlib import Path
import statistics
import subprocess
import sys
import time

os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["AIPACS_SLOT_TIMING_TRACE"] = "0"
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QCoreApplication, QEvent, QObject, QTimer, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QApplication
from shiboken6 import isValid
from PacsClient.pacs.patient_tab.utils import thumbnail_manager as current


class Theme(QObject):
    themeChanged = Signal(dict)

    def current_theme(self):
        return {}


def summarize(values):
    return {"n": len(values), "median_ms": round(statistics.median(values), 3),
            "max_ms": round(max(values), 3)}


def elapsed_ms(start):
    return (time.perf_counter() - start) * 1000


def drain():
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    QApplication.processEvents()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)


def card_run(cls, count, pixmap):
    manager = cls(lambda key: None)
    cards, card_times = [], []
    start = time.perf_counter()
    for i in range(count):
        before = time.perf_counter()
        card = manager.create_thumbnail_widget(
            pixmap, str(i + 1), thumbnail_index=str(i + 1),
            series_info={"study_uid": "synthetic-study", "series_uid": f"synthetic-{i}",
                         "image_count": 2, "display_image_count": 420})
        assert card is not None and "420" in card.count_label.text()
        cards.append(card)
        card_times.append(elapsed_ms(before))
    build = elapsed_ms(start)
    timer_count = sum(len(card.findChildren(QTimer)) for card in cards)
    start = time.perf_counter()
    manager.reset_all_states()
    reset = elapsed_ms(start)
    assert not manager.series_widgets
    if hasattr(manager, "dispose"):
        manager.dispose()
    start = time.perf_counter()
    for card in cards:
        card.deleteLater()
    manager.deleteLater()
    drain()
    deletion = elapsed_ms(start)
    assert all(not isValid(card) for card in cards)
    return build, reset, deletion, max(card_times), timer_count


def burst_run(cls):
    manager = cls(lambda key: None)
    delivered = []
    manager.update_series_progress = lambda *a, **kw: delivered.append(a)
    start = time.perf_counter()
    for i in range(10000):
        key = str(i % 200)
        manager._progress_update_pending[key] = (key, i, "synthetic")
        manager._schedule_progress_flush(0)
    submit = elapsed_ms(start)
    pending_series = len(manager._progress_update_pending)
    timers = len(manager.findChildren(QTimer))
    start = time.perf_counter()
    QApplication.processEvents()
    delivery = elapsed_ms(start)
    assert len(delivered) == 200
    assert {item[1] for item in delivered} == set(range(9800, 10000))
    if hasattr(manager, "dispose"):
        manager.dispose()
    manager.deleteLater()
    drain()
    return {"submit_ms": round(submit, 3), "dispatch_ms": round(delivery, 3),
            "retained_series": pending_series, "delivered": len(delivered),
            "native_child_timers_before_dispatch": timers}


def main():
    logging.disable(logging.CRITICAL)
    app = QApplication.instance() or QApplication([])
    theme = Theme()
    current.get_theme_manager = lambda: theme
    source_path = "PacsClient/pacs/patient_tab/utils/thumbnail_manager.py"
    historical = subprocess.check_output(
        ["git", "show", f"HEAD:{source_path}"], cwd=ROOT, encoding="utf-8")
    tree = ast.parse(historical)
    classes = [n for n in tree.body if isinstance(n, ast.ClassDef)
               and n.name in {"CircularProgressborder", "ThumbnailManager"}]
    assert len(classes) == 2
    namespace = dict(vars(current))
    exec(compile(ast.Module(body=classes, type_ignores=[]), "<HEAD-thumbnail-classes>", "exec"), namespace)
    variants = {"HEAD_classes": namespace["ThumbnailManager"],
                "worktree_classes": current.ThumbnailManager}
    pixmap = QPixmap(160, 120)
    pixmap.fill()
    baseline = subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT,
                                       encoding="utf-8").strip()
    print(json.dumps({"baseline": baseline, "kind": "offscreen synthetic class cost",
                      "live_gui": False, "log_emission": False}))
    for cls in variants.values():
        card_run(cls, 8, pixmap)  # unmeasured warmup for both implementations
    for count in (8, 50, 200):
        samples = {name: [] for name in variants}
        for repeat in range(5):
            order = list(variants.items())
            if repeat % 2:
                order.reverse()
            for name, cls in order:
                samples[name].append(card_run(cls, count, pixmap))
                gc.collect()  # isolated probe only, outside measured runtime work
        for name, values in samples.items():
            print(json.dumps({"variant": name, "cards": count,
                              "build": summarize([v[0] for v in values]),
                              "reset": summarize([v[1] for v in values]),
                              "qt_deletion": summarize([v[2] for v in values]),
                              "slowest_card_ms": round(max(v[3] for v in values), 3),
                              "card_timers": values[-1][4]}))
    for name, cls in variants.items():
        print(json.dumps({"variant": name, "burst_10000": burst_run(cls)}))


if __name__ == "__main__":
    main()
