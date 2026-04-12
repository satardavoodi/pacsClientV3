"""
diagnostic_hooks/
=================
Real-app diagnostic hooks for the FAST viewer.

Only activated when ``AIPACS_DIAG_MODE=1`` is set in the environment.
Never imports or initialises anything that affects production performance
when the env var is absent.

Usage
-----
    AIPACS_DIAG_MODE=1 python main.py

    # then open a CT series and watch the run directory fill with artifacts
    cat user_data/diagnostics/<run_id>/summary.txt
"""
