"""Tiny wrapper to run the DM test and capture output to a file."""
import sys
import os

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(os.path.dirname(_THIS_DIR))

# Ensure project root is on sys.path
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)
# Ensure tests dir is on sys.path for the import
if _THIS_DIR not in sys.path:
    sys.path.insert(0, _THIS_DIR)

out_path = os.path.join(_THIS_DIR, "dm_results.txt")

# Write a marker first so we know the file was at least opened
with open(out_path, "w", encoding="utf-8") as f:
    f.write("=== DM TEST STARTING ===\n")

# redirect stdout + stderr to a file
with open(out_path, "w", encoding="utf-8") as f:
    old_stdout, old_stderr = sys.stdout, sys.stderr
    sys.stdout = f
    sys.stderr = f
    try:
        import test_download_manager
        rc = test_download_manager.main()
    except Exception as e:
        import traceback
        traceback.print_exc(file=f)
        rc = 99
    finally:
        sys.stdout, sys.stderr = old_stdout, old_stderr

print(f"Done - results written to {out_path} (exit code {rc})")
