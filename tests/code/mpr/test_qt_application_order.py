"""MPR QObject-only tests must remain compatible with later QWidget tests."""
import os
import subprocess
import sys

import pytest


@pytest.mark.parametrize('reverse', [False, True])
def test_slicer_tests_share_a_widget_capable_application(reverse):
    cases = [
        'tests/code/mpr/test_slicer_reopen.py::test_reopen_during_shutdown_waits_then_opens_selected_series',
        'tests/code/mpr/test_slicer_resident.py::test_launcher_imports_are_not_runtime_readiness',
        'tests/code/mpr/test_slicer_close_during_load.py::test_close_waits_for_load_reply_before_native_teardown',
    ]
    if reverse:
        cases.reverse()
    result = subprocess.run(
        [sys.executable, '-m', 'pytest', '-p', 'no:debugging', *cases, '--reruns', '0', '-q'],
        env={**os.environ, 'QT_QPA_PLATFORM': 'offscreen'},
        capture_output=True, text=True, timeout=45,
    )
    assert result.returncode == 0, (
        f'Child pytest exit: {result.returncode:#x}\n{result.stdout}\n{result.stderr}'
    )
    assert '3 passed' in result.stdout
