#!/usr/bin/env bash
# CI / local runner for the code-only suite.
# Use this in PR checks: it never needs a display.
set -euo pipefail

export QT_QPA_PLATFORM=offscreen   # headless Qt for tests that touch QWidgets
cd "$(dirname "$0")/.."             # project root
pytest_exit=0
python -m pytest tests/code/ "$@" || pytest_exit=$?

# ── Framework health snapshot ─────────────────────────────────────────
echo
echo "=========================================================="
python tools/kpi_dashboard.py
dash_exit=$?
echo "=========================================================="

# Pytest failure dominates; otherwise dashboard verdict is the exit code.
if [ "$pytest_exit" -ne 0 ]; then
    exit "$pytest_exit"
fi
exit "$dash_exit"
