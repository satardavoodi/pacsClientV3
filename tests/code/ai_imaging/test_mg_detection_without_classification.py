"""Detection artifacts remain usable when optional classification is absent."""
import ast
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.mark.parametrize('method', ['start_process_series', 'switch_series'])
@pytest.mark.parametrize('from_manifest', [True, False])
def test_detection_only_result_is_loaded(method, from_manifest, tmp_path):
    source = Path('modules/ai_imaging/ai_module_ui/overrides/vtk_widget.py')
    tree = ast.parse(source.read_text(encoding='utf-8'))
    original = next(n for n in tree.body if isinstance(n, ast.ClassDef)
                    and any(isinstance(m, ast.FunctionDef) and m.name == method for m in n.body))
    selected = next(m for m in original.body if isinstance(m, ast.FunctionDef) and m.name == method)
    cls = ast.ClassDef(name='Subject', bases=[ast.Name(id='Base', ctx=ast.Load())],
                       keywords=[], body=[selected], decorator_list=[])

    class Base:
        def start_process_series(self, *args, **kwargs):
            return True

        def switch_series(self, *args, **kwargs):
            return True

    detection = tmp_path / 'updated_csv_with_boxes_run.csv'
    detection.write_text('box,scores\n"[[1,2,3,4]]","[0.8]"\n')
    ns = {'Base': Base, 'ATTACHMENT_PATH': tmp_path, '_AI_MG_LOGGER': None,
          '_diagnose_mg_volume': lambda *args: None,
          'enforce_single_image_metadata': lambda metadata, *args: metadata,
          'load_mg_ai_manifest': lambda **kwargs: (detection, None) if from_manifest else (None, None)}
    exec(compile(ast.fix_missing_locations(ast.Module(body=[cls], type_ignores=[])), str(source), 'exec'), ns)
    obj = ns['Subject']()
    obj.csv_details_path = obj.csv_classification = None
    obj.image_viewer = SimpleNamespace(metadata_fixed={'study_uid': '1.2.3'})
    obj._clear_3d_cursor_actors = lambda: None
    obj._fallback_mg_csv_paths = lambda study: (detection, None)
    obj._ensure_ai_prefetch_for_all_series = lambda: None
    obj._schedule_manager_ai_safe = lambda **kwargs: None
    obj._seg_request_token = 0
    metadata = {'series': {'modality': 'MG'}}
    if method == 'start_process_series':
        obj.start_process_series(None, metadata, 0, 0, {'study_uid': '1.2.3'})
    else:
        obj.switch_series(None, metadata, 0, metadata_fixed={'study_uid': '1.2.3'})
    assert obj.csv_details_path == detection
    assert obj.csv_classification is None
