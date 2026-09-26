"""Both frozen cores retain the shared Settings UI and role resolver."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace

from builder.source_identity import input_paths


ROOT = Path(__file__).resolve().parents[3]
ROLE_MODULES = (
    "PacsClient.pacs.workstation_ui.settings_ui.settings_ui",
    "PacsClient.pacs.workstation_ui.settings_ui.server_settings",
    "PacsClient.pacs.workstation_ui.settings_ui.eagle_eye_settings",
    "modules.ai_imaging.eagle_eye_remote.administration",
)


def test_role_settings_sources_enter_canonical_snapshot():
    paths = set(input_paths(ROOT))
    for module in ROLE_MODULES:
        assert module.replace(".", "/") + ".py" in paths


def test_pyinstaller_explicitly_keeps_role_settings():
    spec = (ROOT / "builder/spec/appA_workstation.spec").read_text(encoding="utf-8")
    for module in ROLE_MODULES:
        assert f'"{module}"' in spec


def test_nuitka_full_core_explicitly_keeps_role_settings(monkeypatch):
    name = "role_settings_packaging_nuitka"
    spec = importlib.util.spec_from_file_location(
        name, ROOT / "builder nuitka/build_nuitka_release.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "existing_modules", lambda names: set(names))
    context = SimpleNamespace(version="3.6.7", spec=SimpleNamespace(),
                              args=SimpleNamespace(compiler="msvc"))
    command, _, _ = module.create_nuitka_command(
        context, module.STAGES[6], profile="full_core", entrypoint="main.py"
    )
    for name in ROLE_MODULES:
        assert "--include-module=" + name in command
