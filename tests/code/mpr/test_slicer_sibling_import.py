"""The installed Slicer module can import its sibling analysis package."""

from pathlib import Path
import shutil
import subprocess
import sys


SOURCE = Path("modules/mpr/advanced_3d_slicer/slicer_modules")


def test_resident_module_exposes_sibling_package_when_loaded_by_file(tmp_path):
    module_dir = tmp_path / "installed" / "slicer_modules"
    package_dir = module_dir / "aipacs_lumen"
    package_dir.mkdir(parents=True)
    shutil.copy2(SOURCE / "AIPacsBackgroundRuntime.py", module_dir)
    for name in ("__init__.py", "routing.py"):
        shutil.copy2(SOURCE / "aipacs_lumen" / name, package_dir)

    probe = """
import importlib
import importlib.util
from pathlib import Path
import sys
import types

root = Path(sys.argv[1])
qt = types.ModuleType('qt')
qt.QObject = object
sys.modules['qt'] = qt
slicer = types.ModuleType('slicer')
slicer.__path__ = []
sys.modules['slicer'] = slicer
scripted = types.ModuleType('slicer.ScriptedLoadableModule')
scripted.ScriptedLoadableModule = object
sys.modules[scripted.__name__] = scripted
spec = importlib.util.spec_from_file_location('AIPacsBackgroundRuntime', root / 'AIPacsBackgroundRuntime.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
routing = importlib.import_module('aipacs_lumen.routing')
assert Path(routing.__file__).resolve() == (root / 'aipacs_lumen' / 'routing.py').resolve()
assert routing.validate(None) is None
"""
    result = subprocess.run(
        [sys.executable, "-I", "-c", probe, str(module_dir)],
        cwd=tmp_path, capture_output=True, text=True, timeout=20,
    )
    assert result.returncode == 0, result.stderr
