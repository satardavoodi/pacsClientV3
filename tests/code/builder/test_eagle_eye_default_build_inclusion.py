"""Build guards for the default Eagle Eye runtime path."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[3]
NUITKA_SPEC = ROOT / "builder nuitka" / "AIPacs_nuitka.spec.py"
NUITKA_STAGED = ROOT / "builder nuitka" / "build_nuitka_release.py"
PYINSTALLER_SPEC = ROOT / "builder" / "spec" / "appA_workstation.spec"
INTERACTOR = (
    ROOT
    / "modules"
    / "viewer"
    / "interactor_styles"
    / "ai_chat_interactorstyle.py"
)
VIEWER_PAYLOAD = (
    ROOT
    / "builder"
    / "plugin package"
    / "packages"
    / "viewer"
    / "payload"
    / "python"
    / "modules"
    / "viewer"
    / "interactor_styles"
    / "ai_chat_interactorstyle.py"
)


def test_both_nuitka_build_paths_force_include_ai_imaging():
    spec_source = NUITKA_SPEC.read_text(encoding="utf-8")
    staged_source = NUITKA_STAGED.read_text(encoding="utf-8")
    full_core = staged_source.split('elif profile == "full_core":', 1)[1]
    full_core = full_core.split('if profile == "full_core":', 1)[0]

    assert '"modules.ai_imaging",' in spec_source
    assert '"modules.ai_imaging",' in full_core


def test_default_and_packaged_viewer_use_the_context_handoff_without_a_flag():
    pyinstaller_source = PYINSTALLER_SPEC.read_text(encoding="utf-8")
    canonical = INTERACTOR.read_text(encoding="utf-8-sig")
    packaged = VIEWER_PAYLOAD.read_text(encoding="utf-8-sig")

    assert 'collect_submodules(package_name' in pyinstaller_source
    assert 'for package_name in ["modules", "database", "PacsClient"]' in pyinstaller_source
    assert "session_request.with_study_context(" in canonical
    assert "candidates=resolution.candidates" in canonical
    assert canonical == packaged
    handoff_block = canonical.split("payload = session_request.with_study_context(", 1)[1]
    handoff_block = handoff_block.split("session_request.stash(", 1)[0]
    assert "getenv" not in handoff_block
    assert "environ" not in handoff_block


def test_staged_full_core_command_contains_the_ai_imaging_package():
    module_spec = importlib.util.spec_from_file_location(
        "eagle_eye_nuitka_build_guard",
        NUITKA_STAGED,
    )
    assert module_spec is not None and module_spec.loader is not None
    build_module = importlib.util.module_from_spec(module_spec)
    sys.modules[module_spec.name] = build_module
    try:
        module_spec.loader.exec_module(build_module)
    finally:
        sys.modules.pop(module_spec.name, None)

    context = SimpleNamespace(
        version="3.6.3",
        args=SimpleNamespace(compiler="auto"),
        spec=SimpleNamespace(
            WINDOWS_CONSOLE_MODE="attach",
            ICON="",
            LTO="no",
            JOBS=0,
            C_COMPILER="auto",
            NOFOLLOW_IMPORTS=[],
            OPTIONAL_DATA=[],
        ),
    )
    stage = SimpleNamespace(number=6, key="full_core")

    command, _report, _output = build_module.create_nuitka_command(
        context,
        stage,
        profile="full_core",
        entrypoint="main.py",
    )

    assert "--include-package=modules.ai_imaging" in command
