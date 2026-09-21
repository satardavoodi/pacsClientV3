"""Guard the observation boundary without changing VTK startup/camera semantics."""
import ast
import re
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[3]


def test_constructor_separates_native_bind_first_render_and_fit():
    tree = ast.parse((ROOT / 'modules/viewer/advanced/viewer_2d.py').read_text(encoding='utf-8'))
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'ImageViewer2D')
    init = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == '__init__')
    phases = [(n.lineno, n.args[0].value) for n in ast.walk(init)
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
              and isinstance(n.func.value, ast.Name) and n.func.value.id == '_startup_timing'
              and n.func.attr == 'mark']
    assert [p for _, p in sorted(phases)] == [
        'vtk_base', 'object_setup', 'preprocess', 'direction', 'geometry',
        'window_setup', 'reslice', 'input_bind', 'display_setup', 'overlays',
        'first_render', 'fit_render',
    ]
    marks = {name: line for line, name in phases}
    calls = [(n.lineno, n.func.attr) for n in ast.walk(init)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
             and isinstance(n.func.value, ast.Name) and n.func.value.id == 'self']
    render = next(line for line, name in calls if name == 'Render')
    fit = next(line for line, name in calls if name == 'zoom_to_fit')
    assert marks['overlays'] < render < marks['first_render'] < fit < marks['fit_render']
    assert all(marks['reslice'] < line < marks['input_bind']
               for line, name in calls if name == 'SetInputData')


def test_elapsed_phases_are_nonoverlapping_and_emit_once(monkeypatch):
    from modules.viewer.advanced import startup_timing as timing
    ticks = iter([10.0, 10.002, 10.007, 10.010])
    monkeypatch.setattr(timing, 'perf_counter', lambda: next(ticks))
    records = []

    class Logger:
        def info(self, fmt, *args, **kwargs):
            records.append((fmt % args, kwargs))

    timer = timing.AdvancedStartupTiming(Logger())
    timer.mark('reslice')
    timer.mark('first_render')
    assert records == []
    timer.finish()
    timer.finish()
    timer.mark('ignored')
    assert len(records) == 1
    message, kwargs = records[0]
    numbers = {k: float(v) for k, v in re.findall(r'(\w+_ms)=([\d.]+)', message)}
    assert numbers == pytest.approx({'total_ms': 10, 'reslice_ms': 2,
                                     'first_render_ms': 5, 'finalize_ms': 3})
    assert kwargs['extra']['component'] == 'viewer'
    assert 'outcome=complete' in message


def test_log_sink_failure_cannot_break_constructed_viewer():
    from modules.viewer.advanced.startup_timing import AdvancedStartupTiming

    class BrokenLogger:
        def info(self, *_args, **_kwargs):
            raise OSError('synthetic unavailable sink')

    timer = AdvancedStartupTiming(BrokenLogger())
    timer.mark('first_render')
    timer.finish()


def test_incomplete_construction_does_not_claim_completion():
    from modules.viewer.advanced.startup_timing import AdvancedStartupTiming
    records = []

    class Logger:
        def info(self, *args, **kwargs):
            records.append(args)

    timer = AdvancedStartupTiming(Logger())
    timer.mark('vtk_base')
    del timer
    assert records == []
