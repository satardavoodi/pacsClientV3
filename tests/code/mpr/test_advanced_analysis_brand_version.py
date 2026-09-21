"""Keep custom native and Python display versions aligned with the workstation."""
import ast
from pathlib import Path
import re
from types import SimpleNamespace
import tomllib

import pytest

ROOT = Path(__file__).resolve().parents[3]
CUSTOM = ROOT / 'modules/mpr/advanced_3d_slicer/slicer_custom_app'
NATIVE = CUSTOM / 'NewMPR2Slicer/Applications/NewMPR2SlicerApp'
VERSION = tomllib.loads((ROOT / 'pyproject.toml').read_text(encoding='utf-8'))['project']['version']
TITLE = 'AI-PACS Advanced Viewer v' + VERSION


@pytest.mark.parametrize('patient,study', [(None, None), ('synthetic-person', None),
                                         ('synthetic-person', 'synthetic-study')])
def test_runtime_title_is_short_and_excludes_case_identifiers(patient, study):
    tree = ast.parse((CUSTOM / 'startup_script.py').read_text(encoding='utf-8'))
    function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'set_window_title')
    titles = []
    window = SimpleNamespace(setWindowTitle=titles.append)
    namespace = {'slicer': SimpleNamespace(util=SimpleNamespace(mainWindow=lambda: window))}
    exec(compile(ast.Module(body=[function], type_ignores=[]), '<title guard>', 'exec'), namespace)
    namespace['set_window_title'](patient, study)
    assert titles == [TITLE]


def test_native_application_properties_match_workstation_version():
    properties = (NATIVE / 'slicer-application-properties.cmake').read_text(encoding='utf-8')
    values = [re.search(r'set\(VERSION_' + part + r'\s+(\d+)\s*\)', properties).group(1)
              for part in ('MAJOR', 'MINOR', 'PATCH')]
    assert '.'.join(values) == VERSION


@pytest.mark.parametrize('path', [CUSTOM / 'startup_script.py', CUSTOM / 'launch_slicer.py', NATIVE / 'Main.cxx'])
def test_every_declared_display_version_matches_workstation(path):
    versions = re.findall(r'AI-PACS Advanced Viewer v([0-9.]+)', path.read_text(encoding='utf-8'))
    assert versions
    assert set(versions) == {VERSION}
