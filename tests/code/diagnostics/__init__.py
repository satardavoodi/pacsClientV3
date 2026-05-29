"""
AIPacs FAST Viewer — Automated Diagnostic Framework
====================================================
Hybrid diagnostic system covering synthetic simulation, real-app instrumentation,
and event replay to characterise FAST viewer crashes under load.

Modes:
    synthetic   — fully offline, driven by build_fake_metadata / make_dicom_series
    real_app    — AIPACS_DIAG_MODE=1 attaches hooks to running app (see diagnostic_hooks/)
    replay      — reads a saved events.jsonl and re-runs failure-Detection passes

Usage:
    python tests/diagnostics/run_diagnostic.py --scenario s03_large_ct
    python tests/diagnostics/run_diagnostic.py --all
    python tests/diagnostics/run_diagnostic.py --replay /path/to/run_dir
"""
