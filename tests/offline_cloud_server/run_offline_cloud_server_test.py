"""Run the Offline Cloud Server test suite and capture KPI output to a text file."""

import os
import sys

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(os.path.dirname(_THIS_DIR))

if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)
if _THIS_DIR not in sys.path:
    sys.path.insert(0, _THIS_DIR)

out_path = os.path.join(_THIS_DIR, "offline_cloud_server_results.txt")

with open(out_path, "w", encoding="utf-8") as fh:
    fh.write("=== OFFLINE CLOUD SERVER TEST STARTING ===\n")

with open(out_path, "w", encoding="utf-8") as fh:
    old_stdout, old_stderr = sys.stdout, sys.stderr
    sys.stdout = fh
    sys.stderr = fh
    try:
        import test_offline_cloud_server

        rc = test_offline_cloud_server.main()
    except Exception:
        import traceback

        traceback.print_exc(file=fh)
        rc = 99
    finally:
        sys.stdout, sys.stderr = old_stdout, old_stderr

print(f"Done - results written to {out_path} (exit code {rc})")
