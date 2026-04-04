"""Tiny wrapper — runs DB test and captures output to a file."""
import sys
import os

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(os.path.dirname(_THIS_DIR))

if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)
if _THIS_DIR not in sys.path:
    sys.path.insert(0, _THIS_DIR)

out_path = os.path.join(_THIS_DIR, "db_results.txt")

with open(out_path, "w", encoding="utf-8") as f:
    old_stdout, old_stderr = sys.stdout, sys.stderr
    sys.stdout = f
    sys.stderr = f
    try:
        import test_database
        rc = test_database.main()
    except Exception as e:
        import traceback
        traceback.print_exc(file=f)
        rc = 99
    finally:
        sys.stdout, sys.stderr = old_stdout, old_stderr

print(f"Done - results written to {out_path} (exit code {rc})")
