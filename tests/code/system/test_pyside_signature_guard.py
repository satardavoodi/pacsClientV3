"""Synthetic import-registry races; no keyring, patient data or live database."""
import importlib.util
import ast
import os
import subprocess
import sys
from pathlib import Path
from types import FunctionType, SimpleNamespace

import pytest
from PySide6.support.signature import mapping as installed_mapping

ROOT = Path(__file__).resolve().parents[3]
GUARD = ROOT / "PacsClient/utils/pyside_signature_guard.py"


def _guard():
    if not GUARD.exists():
        return None  # Run the actual installed algorithm for fail-before proof.
    spec = importlib.util.spec_from_file_location("signature_guard_under_test", GUARD)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ImportRegistry(dict):
    """Model an import failure removing its temporary entry after a snapshot."""
    remove_after_copy = None

    def copy(self):
        result = super().copy()
        if self.remove_after_copy:
            self.pop(self.remove_after_copy, None)
        return result


def _harness():
    registry = ImportRegistry()
    namespace = dict(installed_mapping.Reloader.update.__globals__)
    namespace.update(sys=SimpleNamespace(modules=registry), pyside_modules=set())
    imported = []
    top = SimpleNamespace(__name__="Synthetic")

    def import_existing(name):
        assert name in registry, "Never re-import a vanished candidate"
        imported.append(name)
        return top

    namespace["__import__"] = import_existing
    update = FunctionType(installed_mapping.Reloader.update.__code__, namespace)

    class Reloader:
        sys_module_count = 0
        module_valid = staticmethod(lambda mod: bool(getattr(mod, "binary", False)))

    Reloader.update = update
    owner = Reloader()
    fake = SimpleNamespace(Reloader=Reloader, update_mapping=owner.update)
    # globals() in the installed function needs its own namespace; the adapter
    # uses this namespace too, without replacing process-global sys.modules.
    fake.__dict__.update(namespace)
    fake.Reloader = Reloader
    fake.update_mapping = owner.update
    parser = SimpleNamespace(update_mapping=fake.update_mapping)
    guard = _guard()
    if guard:
        assert guard._install_mapping_guard(fake, parser, "6.10.2")
    return registry, fake, parser, imported, owner


def test_failed_python_import_disappears_after_snapshot():
    registry, mapping, parser, imported, _ = _harness()
    registry["synthetic.failed_backend"] = SimpleNamespace(binary=False)
    registry["Synthetic.binary"] = SimpleNamespace(binary=True)
    registry.remove_after_copy = "synthetic.failed_backend"
    parser.update_mapping()
    assert imported == ["Synthetic.binary"]
    assert "synthetic.failed_backend" not in registry


def test_vanished_binary_candidate_is_not_reimported():
    registry, mapping, parser, imported, _ = _harness()
    registry["Synthetic.vanished"] = SimpleNamespace(binary=True)
    registry["Synthetic.survivor"] = SimpleNamespace(binary=True)
    registry.remove_after_copy = "Synthetic.vanished"
    mapping.update_mapping()
    assert imported == ["Synthetic.survivor"]


def test_unchanged_module_count_remains_a_noop():
    registry, mapping, parser, imported, owner = _harness()
    registry["Synthetic.binary"] = SimpleNamespace(binary=True)
    owner.sys_module_count = len(registry)
    parser.update_mapping()
    assert imported == []


def test_initializers_and_pyside_registration_are_preserved():
    registry, mapping, parser, imported, _ = _harness()
    registry["PySide6.Synthetic"] = SimpleNamespace(binary=True)
    calls = []
    mapping.init_PySide6_Synthetic = lambda: (calls.append(True) or {"sentinel_type": int})
    parser.update_mapping()
    assert mapping.sentinel_type is int
    assert mapping.pyside_modules == {"PySide6.Synthetic"}
    assert calls == [True]
    registry["synthetic.python"] = SimpleNamespace(binary=False)
    parser.update_mapping()
    assert calls == [True]


def test_application_errors_are_not_swallowed():
    registry, mapping, parser, _, _ = _harness()
    registry["Synthetic.binary"] = SimpleNamespace(binary=True)
    def fail():
        raise KeyError("synthetic_initializer_defect")
    mapping.init_Synthetic_binary = fail
    with pytest.raises(KeyError, match="synthetic_initializer_defect"):
        parser.update_mapping()


def test_none_initializer_keeps_original_type_error():
    registry, mapping, parser, _, _ = _harness()
    registry["Synthetic.binary"] = SimpleNamespace(binary=True)
    mapping.init_Synthetic_binary = None
    with pytest.raises(TypeError):
        parser.update_mapping()


def test_install_is_idempotent_and_preserves_owner():
    registry, mapping, parser, _, owner = _harness()
    installed = mapping.update_mapping
    assert _guard()._install_mapping_guard(mapping, parser, "6.10.2")
    assert mapping.update_mapping is parser.update_mapping is installed
    assert installed.__self__ is owner


def test_unreviewed_version_is_not_patched():
    mapping = SimpleNamespace(update_mapping=object())
    parser = SimpleNamespace(update_mapping=mapping.update_mapping)
    original = mapping.update_mapping
    assert not _guard()._install_mapping_guard(mapping, parser, "6.11.0")
    assert mapping.update_mapping is parser.update_mapping is original


def test_unknown_binding_is_not_partially_patched():
    mapping = SimpleNamespace(update_mapping=lambda: None)
    parser = SimpleNamespace(update_mapping=object())
    original = mapping.update_mapping
    assert not _guard()._install_mapping_guard(mapping, parser, "6.10.2")
    assert mapping.update_mapping is original


def test_startup_installs_before_app_handler_import():
    tree = ast.parse((ROOT / "main.py").read_text(encoding="utf-8-sig"))
    install = next(n.lineno for n in tree.body if isinstance(n, ast.Expr)
                   and isinstance(n.value, ast.Call) and isinstance(n.value.func, ast.Name)
                   and n.value.func.id == "install_pyside_signature_guard")
    handler = next(n.lineno for n in tree.body if isinstance(n, ast.ImportFrom)
                   and n.module == "PacsClient.app_handler")
    assert install < handler


@pytest.mark.parametrize("frozen", [False, True])
def test_real_qt_signatures_and_queued_delivery_in_isolated_process(frozen):
    # Isolated Qt loop is not a second source-app instance or a GUI acceptance lap.
    code = f'''
import importlib.util, sys
from pathlib import Path
spec = importlib.util.spec_from_file_location("guard", {str(GUARD)!r})
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)
import PySide6
sys.frozen = {frozen!r}
assert guard.install_pyside_signature_guard()
from PySide6.support.signature import mapping, parser
assert mapping.update_mapping is parser.update_mapping
from PySide6.QtWidgets import QApplication, QPushButton
from PySide6.QtCore import QTimer, QObject, Signal, Slot
from shiboken6 import isValid
from PySide6.support.signature import get_signature
app = QApplication([])
assert get_signature(QTimer.singleShot)
button = QPushButton("Synthetic")
try:
    button.setFixedSize("invalid")
except TypeError:
    pass
else:
    raise AssertionError("Qt argument errors must stay visible")
seen = []
QTimer.singleShot(0, lambda: (seen.append(True), app.quit()))
QTimer.singleShot(2000, app.quit)
app.exec()
assert seen == [True]
assert isValid(button)
assert mapping.update_mapping is parser.update_mapping
print("signature and event-loop smoke passed")
'''
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                            timeout=30, env={**os.environ, "QT_QPA_PLATFORM": "offscreen"})
    assert result.returncode == 0, result.stdout + result.stderr
