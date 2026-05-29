"""pywinauto smoke runner for the patient-open path (Scenario 1).

Drives the AI-PACS *source build* — refuses to run otherwise.

Workflow:
    1. Pre-flight: confirm source build via mtime + foreground process.
    2. Attach to the AI-PACS Python window by title.
    3. Click 5 different patient rows in the table.
    4. Wait for the right panel to update.
    5. Snapshot the logs delta and forward to extract_2026_05_27_kpis.py.

Usage:
    python tests/gui/pywinauto/run_patient_open_smoke.py
    python tests/gui/pywinauto/run_patient_open_smoke.py --rows 0 3 7 11 15

Install once:
    pip install pywinauto
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

# Local helpers — keep paths repo-relative so this script works from any cwd.
_THIS = Path(__file__).resolve()
PROJECT_ROOT = _THIS.parents[3]
sys.path.insert(0, str(PROJECT_ROOT / "tests" / "gui" / "live_walkthroughs"))
from _verify_source_build import require_source_build, WrongBuildError  # noqa: E402


def _connect_pywinauto():
    """Import pywinauto lazily and connect to the AI-PACS window."""
    try:
        from pywinauto import Application
    except ImportError as exc:
        raise SystemExit(
            "pywinauto is not installed. Run:  pip install pywinauto\n"
            f"(import error: {exc})"
        )

    # Match either spelled-out title or any "AI-Pacs" variant.
    # The source build sets WindowTitle = "AI-Pacs".
    try:
        app = Application(backend="uia").connect(title_re=r"AI[ -]?[Pp]acs.*")
    except Exception as exc:
        raise SystemExit(
            f"Could not find an open AI-PACS window: {exc}\n"
            "Launch the source build from VS Code (Play on main.py) first."
        )

    window = app.window(title_re=r"AI[ -]?[Pp]acs.*")
    window.wait("ready", timeout=10)
    return app, window


def click_patient_row(window, row_index: int):
    """Click a row in the patient table.

    The patient table is a QTableView. pywinauto's UIA backend can address
    rows by their accessibility index OR by the cell's child_window. The
    cleanest path is via the table descendant; if that fails, fall back
    to a coordinate click computed from the table client_rect.
    """
    try:
        table = window.child_window(class_name_re=r"QTableView|PatientTable.*")
        cell = table.children()[row_index]
        cell.click_input()
        return
    except Exception:
        pass

    # Coordinate fallback (less robust). Each row is ~38 px tall in the
    # current layout; the column starts at ~x=389 in the home tab.
    rect = window.rectangle()
    row_y = rect.top + 130 + 38 * row_index + 19
    window.click_input(coords=(rect.left + 389, row_y))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rows", nargs="+", type=int, default=[0, 3, 7, 11, 15],
                        help="Row indices to click (0-based).")
    parser.add_argument("--wait", type=float, default=3.0,
                        help="Seconds to wait between clicks.")
    parser.add_argument("--skip-build-check", action="store_true",
                        help="(NOT recommended) skip the source-build pre-flight.")
    args = parser.parse_args(argv)

    if not args.skip_build_check:
        try:
            require_source_build()
        except WrongBuildError as exc:
            print(f"PRE-FLIGHT FAIL: {exc}", file=sys.stderr)
            return 2

    pre_t = time.time()
    print(f"[{time.strftime('%H:%M:%S')}] connecting to AI-PACS window...")
    _, window = _connect_pywinauto()

    print(f"[{time.strftime('%H:%M:%S')}] driving {len(args.rows)} clicks...")
    for i, row in enumerate(args.rows, 1):
        print(f"  click {i}/{len(args.rows)}  row={row}")
        try:
            click_patient_row(window, row)
        except Exception as exc:
            print(f"    WARN: click failed: {exc}")
        time.sleep(args.wait)

    post_t = time.time()
    print(f"[{time.strftime('%H:%M:%S')}] done. elapsed={post_t - pre_t:.1f}s")

    # Forward to KPI extractor for the post-mortem.
    kpi_extractor = PROJECT_ROOT / "tests" / "gui" / "live_walkthroughs" / "extract_2026_05_27_kpis.py"
    if kpi_extractor.exists():
        print(f"\n[{time.strftime('%H:%M:%S')}] running KPI extractor...")
        since_str = time.strftime("%Y-%m-%d %H:%M:%S",
                                  time.localtime(pre_t - 5))
        subprocess.run(
            [sys.executable, str(kpi_extractor), "--since", since_str],
            check=False,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
