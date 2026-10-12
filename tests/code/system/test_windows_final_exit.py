"""Exercise the actual final-exit primitive without launching the workstation."""
import ast
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[3]


class _Stopped(BaseException):
    pass


class _NativeFunction:
    def __init__(self, invoke):
        self.invoke = invoke

    def __call__(self, *args):
        return self.invoke(*args)


def test_windows_exit_targets_only_current_process_and_preserves_code(monkeypatch):
    from PacsClient.utils import process_exit
    calls = []
    def terminate(handle, code):
        calls.append((handle, code))
        raise _Stopped
    kernel = SimpleNamespace(
        GetCurrentProcess=_NativeFunction(lambda: -1),
        TerminateProcess=_NativeFunction(terminate),
    )
    monkeypatch.setattr(process_exit, 'os', SimpleNamespace(name='nt'))
    monkeypatch.setattr(process_exit, 'ctypes', SimpleNamespace(
        WinDLL=lambda name, **kwargs: kernel))
    with pytest.raises(_Stopped):
        process_exit.hard_exit(7)
    assert calls == [(-1, 7)]
    assert len(kernel.TerminateProcess.argtypes) == 2
    assert kernel.GetCurrentProcess.restype is not None


def test_windows_native_failure_does_not_fall_through(monkeypatch):
    from PacsClient.utils import process_exit
    kernel = SimpleNamespace(
        GetCurrentProcess=_NativeFunction(lambda: -1),
        TerminateProcess=_NativeFunction(lambda *args: 0),
    )
    monkeypatch.setattr(process_exit, 'os', SimpleNamespace(name='nt'))
    monkeypatch.setattr(process_exit, 'ctypes', SimpleNamespace(
        WinDLL=lambda *args, **kwargs: kernel,
        get_last_error=lambda: 5, WinError=lambda code: OSError(code, 'synthetic')))
    with pytest.raises(OSError) as error:
        process_exit.hard_exit(0)
    assert error.value.errno == 5


def test_non_windows_retains_existing_exit(monkeypatch):
    from PacsClient.utils import process_exit
    codes = []
    def exit_(code):
        codes.append(code)
        raise _Stopped
    monkeypatch.setattr(process_exit, 'os', SimpleNamespace(name='posix', _exit=exit_))
    with pytest.raises(_Stopped):
        process_exit.hard_exit(3)
    assert codes == [3]


def _final_exit_expression():
    tree = ast.parse((ROOT / 'main.py').read_text(encoding='utf-8-sig'))
    calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)
             and ast.unparse(node.func) in ('os._exit', 'hard_exit')]
    assert calls, 'The final shutdown boundary must retain its explicit exit'
    return ast.unparse(max(calls, key=lambda node: node.lineno).func)


@pytest.mark.skipif(os.name != 'nt', reason='Windows loader-detach contract')
def test_final_exit_does_not_reenter_dll_destructors(tmp_path):
    # An opt-in locally compiled synthetic DLL writes a marker ONLY on process
    # detach. It contains no patient data and does not load the workstation.
    dll = os.environ.get('AIPACS_EXIT_PROBE_DLL')
    if not dll:
        pytest.skip('Set AIPACS_EXIT_PROBE_DLL to the synthetic detach probe DLL')
    marker = tmp_path / 'dll-detach.marker'
    expression = _final_exit_expression()
    script = ('import ctypes, os\n'
              + ('from PacsClient.utils.process_exit import hard_exit\n'
                 if expression == 'hard_exit' else '')
              + f'probe = ctypes.WinDLL({str(Path(dll).resolve())!r})\n'
              + f'{expression}(7)\n')
    result = subprocess.run(
        [sys.executable, '-c', script], cwd=ROOT,
        env=dict(os.environ, AIPACS_EXIT_DETACH_MARKER=str(marker)),
        capture_output=True, timeout=15,
    )
    assert result.returncode == 7
    assert not marker.exists(), 'Final exit reentered DLL process-detach destructors'
