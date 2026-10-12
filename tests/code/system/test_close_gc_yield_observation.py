"""Measure collection yield before changing native-object reclamation policy."""
import ast
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace


def test_deferred_gc_records_reclaimed_cycles_and_heap_generation_counts():
    source = Path(__file__).resolve().parents[3] / 'PacsClient/pacs/patient_tab/ui/patient_ui/patient_widget_core/_pw_lifecycle.py'
    tree = ast.parse(source.read_text(encoding='utf-8-sig'))
    fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == '_run_deferred_close_gc')
    records = []
    ns = {'_CLOSE_GC_PENDING':[True], '_close_step':lambda _:nullcontext(),
        'gc':SimpleNamespace(collect=lambda:17, get_count=lambda:(2,3,4)),
        'logger':SimpleNamespace(info=lambda *args:records.append(args))}
    exec(compile(ast.Module(body=[fn], type_ignores=[]), str(source), 'exec'),ns)
    ns['_run_deferred_close_gc']()
    assert ns['_CLOSE_GC_PENDING'] == [False]
    assert len(records) == 1
    assert records[0][1:] == (17,(2,3,4))
