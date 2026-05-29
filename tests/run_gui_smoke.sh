#!/usr/bin/env bash
# GUI smoke runner — requires a live AI-PACS source build window.
# Refuses to run if the source build isn't detected.
set -euo pipefail

cd "$(dirname "$0")/.."
python tests/gui/live_walkthroughs/_verify_source_build.py
python tests/gui/pywinauto/run_patient_open_smoke.py "$@"
