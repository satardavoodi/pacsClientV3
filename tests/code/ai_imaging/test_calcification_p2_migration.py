"""Guard strict FPN migration without a workstation Torch/GPU dependency."""
import ast
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest


class Tensor:
    def __init__(self, value):
        self.value = np.asarray(value)
        self.shape = self.value.shape

    def clone(self):
        return Tensor(self.value.copy())


class Model:
    def __init__(self, state):
        self.state = state

    def state_dict(self):
        return self.state

    def load_state_dict(self, state, strict):
        assert strict and set(state) == set(self.state)
        self.loaded = state


def functions():
    path = Path(__file__).resolve().parents[3] / 'tools/eagle_eye/calcification_p2_model.py'
    tree = ast.parse(path.read_text())
    nodes = [node for node in tree.body if isinstance(node, ast.FunctionDef)
             and node.name in ('migrated_key', 'migrate_p3_to_p2')]
    namespace = {'torch': SimpleNamespace(zeros_like=lambda t: Tensor(np.zeros_like(t.value)))}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(path), 'exec'), namespace)
    return namespace


def states():
    source = {'head.weight': Tensor([7])}
    for level, channels in enumerate((4, 8, 16)):
        source[f'backbone.fpn.inner_blocks.{level}.0.weight'] = Tensor(np.ones((2, channels, 1, 1)))
        source[f'backbone.fpn.inner_blocks.{level}.0.bias'] = Tensor(np.ones(2))
        source[f'backbone.fpn.layer_blocks.{level}.0.weight'] = Tensor(np.ones((2, 2, 3, 3)))
        source[f'backbone.fpn.layer_blocks.{level}.0.bias'] = Tensor(np.ones(2))
    target = {functions()['migrated_key'](key): value.clone() for key, value in source.items()}
    for block, shape in [('inner_blocks', (2, 2, 1, 1)), ('layer_blocks', (2, 2, 3, 3))]:
        target[f'backbone.fpn.{block}.0.0.weight'] = Tensor(np.ones(shape))
        target[f'backbone.fpn.{block}.0.0.bias'] = Tensor(np.ones(2))
    return source, Model(target)


def test_shifted_existing_levels_and_head_are_exactly_preserved():
    source, model = states()
    f = functions(); f['migrate_p3_to_p2'](source, model)
    for key, value in source.items():
        assert np.array_equal(model.loaded[f['migrated_key'](key)].value, value.value)
    assert not model.loaded['backbone.fpn.inner_blocks.0.0.weight'].value.any()
    assert np.array_equal(model.loaded['backbone.fpn.layer_blocks.0.0.weight'].value,
                          source['backbone.fpn.layer_blocks.0.0.weight'].value)


def test_missing_source_state_is_not_silently_initialized():
    source, model = states(); source.pop('head.weight')
    with pytest.raises(ValueError, match='schema'):
        functions()['migrate_p3_to_p2'](source, model)


def test_incompatible_source_shape_is_rejected():
    source, model = states(); source['head.weight'] = Tensor([1, 2])
    with pytest.raises(ValueError, match='shape'):
        functions()['migrate_p3_to_p2'](source, model)


def test_unexpected_source_fpn_index_is_rejected():
    with pytest.raises(ValueError, match='level'):
        functions()['migrated_key']('backbone.fpn.inner_blocks.3.0.weight')
