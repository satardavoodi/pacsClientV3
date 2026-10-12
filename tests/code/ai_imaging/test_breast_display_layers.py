"""Breast layer visibility, label provenance and native-coordinate guards."""
import ast
import importlib.util
import logging
from pathlib import Path
from types import SimpleNamespace

import pytest

# Load the leaf module without booting the entire GUI/audio stack via __init__.
# This is a component test, not a source application acceptance test.
_spec = importlib.util.spec_from_file_location(
    'breast_display_contract', Path('modules/ai_imaging/ai_module_ui/breast_display.py'))
_display = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_display)
CalciumDisplayLayer = _display.CalciumDisplayLayer
calcium_record_for_view = _display.calcium_record_for_view
parenchymal_display_items = _display.parenchymal_display_items
validated_calcium_points = _display.validated_calcium_points


def test_legacy_calcium_is_not_relabelled_or_dropped_as_a_detection():
    original = [dict(box=[1, 2, 3, 4], score=.6, classification=['Suspicious Calcification']),
                dict(box=[5, 6, 7, 8], classification=['Mass', 'Calcification']),
                dict(classification=['Focal Asymmetry', 'Architectural Distortion']),
                dict(source_kind='human', classification=['Calcification'])]
    result = parenchymal_display_items(original)
    assert result[0]['box'] == original[0]['box']
    assert result[0]['classification'] == []
    assert result[1]['classification'] == ['Mass']
    assert result[2]['classification'] == original[2]['classification']
    assert result[3] == original[3]
    assert original[0]['classification'] == ['Suspicious Calcification']


def source_viewer():
    return SimpleNamespace(metadata={'series': {'series_uid': '1.2.3'},
                                     'instances': [{'sop_uid': '1.2.4'}]},
                           metadata_fixed={'study_uid': '1.2'},
                           vtk_image_data=SimpleNamespace(GetDimensions=lambda: (600, 800, 1)))


def record():
    return dict(series_uid='1.2.3', sop_uid='1.2.4', shape_hw=[800, 600], points_xy=[[23, 47]])


@pytest.mark.parametrize('field,value', [('sop_uid', '9'), ('series_uid', '9'),
                                         ('shape_hw', [600, 800]), ('points_xy', [[float('nan'), 1]]),
                                         ('points_xy', [[600, 0]])])
def test_wrong_identity_geometry_and_invalid_points_are_rejected(field, value):
    data = record()
    data[field] = value
    with pytest.raises(ValueError):
        validated_calcium_points(data, '1.2', source_viewer())


def test_empty_valid_result_is_distinct_from_unavailable():
    data = record()
    data['points_xy'] = []
    assert validated_calcium_points(data, '1.2', source_viewer()) == []
    assert CalciumDisplayLayer().available is False


@pytest.mark.parametrize('status,space', [('unavailable', 'native_source_pixels_xy'),
                                         ('success', 'resized_pixels'), ('success', None)])
def test_legacy_or_failed_branch_is_not_a_calcium_result(status, space):
    with pytest.raises(ValueError):
        calcium_record_for_view(dict(status=status, coordinate_space=space, study_id='1.2',
                                     files=[record()]), source_viewer())


def test_duplicate_result_is_rejected_and_single_result_is_bound():
    result = dict(status='success', coordinate_space='native_source_pixels_xy', study_id='1.2', files=[record()])
    assert calcium_record_for_view(result, source_viewer()) == record()
    result['files'].append(record())
    with pytest.raises(ValueError):
        calcium_record_for_view(result, source_viewer())


class Actor:
    def __init__(self):
        self.visibility = 1

    def SetVisibility(self, value):
        self.visibility = value


@pytest.fixture
def widget():
    from PySide6.QtWidgets import QApplication, QWidget
    app = QApplication.instance() or QApplication([])
    tree = ast.parse(Path('modules/ai_imaging/ai_module_ui/overrides/vtk_widget.py').read_text(encoding='utf-8'))
    names = {'_create_boxes_toggle_button', '_position_boxes_toggle_button', '_toggle_ai_boxes',
             '_apply_ai_boxes_visibility', '_clear_microcalcifications', '_update_microcalcification_button',
             '_toggle_microcalcifications'}
    methods = [n for cls in tree.body if isinstance(cls, ast.ClassDef) for n in cls.body
               if isinstance(n, ast.FunctionDef) and n.name in names]
    assert len(methods) == len(names)
    node = ast.ClassDef(name='Subject', bases=[ast.Name(id='QWidget', ctx=ast.Load())],
                        keywords=[], body=methods, decorator_list=[])
    scope = dict(QWidget=QWidget, _AI_MG_LOGGER=logging.getLogger(__name__))
    exec(compile(ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[])), '<production-methods>', 'exec'), scope)
    obj = scope['Subject']()
    obj.resize(280, 400)
    obj._ai_boxes_visible = True
    obj._calcium_toggle_btn = None
    obj._calcium_layer = CalciumDisplayLayer()
    obj.render_calls = []
    obj.image_viewer = SimpleNamespace(_box_actors=[Actor()], _box_text_actors=[Actor()],
                                      _overlays=[(None, None, Actor())],
                                      render_window=SimpleNamespace(Render=lambda: obj.render_calls.append(True)))
    yield obj
    obj.close()
    obj.deleteLater()
    app.processEvents()


def test_two_buttons_do_not_control_each_others_actors(widget):
    widget._create_boxes_toggle_button()
    assert not widget._calcium_toggle_btn.isEnabled()
    calcium = Actor()
    widget._calcium_layer.actors = [calcium]
    widget._calcium_layer.available = True
    widget._update_microcalcification_button()
    widget._boxes_toggle_btn.click()
    assert widget.image_viewer._box_actors[0].visibility == 0
    assert widget.image_viewer._overlays[0][2].visibility == 0
    assert calcium.visibility == 1
    widget._calcium_toggle_btn.click()
    assert calcium.visibility == 0
    widget._boxes_toggle_btn.click()
    assert widget.image_viewer._box_actors[0].visibility == 1
    assert calcium.visibility == 0


def test_switch_clear_does_not_reenable_calcium_or_touch_tissue(widget):
    widget._create_boxes_toggle_button()
    actor = Actor()
    removed = []
    widget._calcium_layer.renderer = SimpleNamespace(RemoveActor=removed.append)
    widget._calcium_layer.actors = [actor]
    widget._calcium_layer.available = True
    widget._clear_microcalcifications()
    assert removed == [actor]
    assert not widget._calcium_layer.available
    assert not widget._calcium_toggle_btn.isEnabled()
    assert widget.image_viewer._box_actors[0].visibility == 1
    assert widget.render_calls, 'Removed points must disappear immediately, including on rejected results.'


def test_other_modalities_keep_existing_toggle(widget):
    widget._breast_display_controls = False
    widget._create_boxes_toggle_button()
    assert widget._calcium_toggle_btn is None
    assert widget._boxes_toggle_btn.text() == 'Hide Boxes'
    widget._boxes_toggle_btn.click()
    assert widget._boxes_toggle_btn.text() == 'Show Boxes'


def test_native_overlay_uses_existing_geometry_and_owns_separate_actor():
    import vtk
    viewer = source_viewer()
    viewer.renderer = vtk.vtkRenderer()
    calls = []
    def world(x, y, k, y_flip):
        calls.append((x, y, k, y_flip))
        return x * .1, (799 - y) * .1, 0
    viewer.ijk_to_world = world
    layer = CalciumDisplayLayer()
    layer.set_visible(False)
    layer.apply_result(record(), '1.2', viewer)
    assert calls == [(23., 47., None, True)]
    assert layer.available
    assert layer.actors[0].GetVisibility() == 0
    assert viewer.renderer.GetActors().GetNumberOfItems() == 1
    layer.clear()
    assert viewer.renderer.GetActors().GetNumberOfItems() == 0
