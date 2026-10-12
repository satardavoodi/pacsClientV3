"""A diagnostic console disconnect must not abandon the application log."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace


def test_closed_host_console_keeps_draining_child_and_records_exit(tmp_path, monkeypatch):
    path = Path(__file__).resolve().parents[3] / 'tools/diagnostics/tee_process_output.py'
    spec = importlib.util.spec_from_file_location('tee_under_test', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    target = tmp_path / 'session.log'
    monkeypatch.setattr(module, 'parse_args', lambda: SimpleNamespace(
        command=['synthetic'], cwd=str(tmp_path), log_file=str(target)))
    child = SimpleNamespace(stdout=iter(['first\n', 'second\n']), wait=lambda: 7)
    monkeypatch.setattr(module.subprocess, 'Popen', lambda *a, **kw: child)
    class ClosedConsole:
        def write(self, value):
            raise BrokenPipeError('Host closed')
        def flush(self):
            raise AssertionError('Failed console must be retired')
    monkeypatch.setattr(module, 'sys', SimpleNamespace(stdout=ClosedConsole()))
    assert module.main() == 7
    assert target.read_text() == 'first\nsecond\n[tee_process_output] ChildExitCode=7\n'
