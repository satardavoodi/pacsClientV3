import ast
from pathlib import Path
from types import SimpleNamespace


def test_late_startup_title_uses_current_version_instead_of_native_baseline(monkeypatch):
    import os
    monkeypatch.setenv("AIPACS_VIEWER_TITLE", "AI-PACS Advanced Viewer v3.6.9")
    captured = {}
    window = SimpleNamespace(setWindowTitle=lambda title: captured.update(title=title))
    app = SimpleNamespace(setApplicationDisplayName=lambda title: captured.update(display=title))
    source = Path("modules/mpr/advanced_3d_slicer/slicer_custom_app/startup_script.py")
    tree = ast.parse(source.read_text(encoding="utf-8"))
    method = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "set_window_title")
    namespace = {"os": os, "slicer": SimpleNamespace(util=SimpleNamespace(mainWindow=lambda: window), app=app)}
    exec(compile(ast.Module(body=[method], type_ignores=[]), str(source), "exec"), namespace)
    namespace["set_window_title"]()
    assert captured["title"] == "AI-PACS Advanced Viewer v3.6.9"
    namespace["set_window_title"]()
    assert captured["title"].count("AI-PACS") == 1
    assert captured["display"] == captured["title"]


def test_native_promotion_targets_active_modal_not_blocked_parent(monkeypatch):
    import ctypes
    calls = []
    foreground = lambda handle: calls.append(handle) or True
    monkeypatch.setattr(ctypes, "WinDLL", lambda *args, **kwargs:
                        SimpleNamespace(SetForegroundWindow=foreground))
    window = SimpleNamespace(showNormal=lambda: None, raise_=lambda: None,
                             activateWindow=lambda: None, winId=lambda: 42)
    modal = SimpleNamespace(isVisible=lambda: True, raise_=lambda: None,
                            activateWindow=lambda: None, winId=lambda: 84)
    source = Path("modules/mpr/advanced_3d_slicer/slicer_custom_app/startup_script.py")
    tree = ast.parse(source.read_text(encoding="utf-8"))
    method = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "promote_window")
    namespace = {"os": SimpleNamespace(name="nt"), "slicer": SimpleNamespace(
        util=SimpleNamespace(mainWindow=lambda: window),
        app=SimpleNamespace(activeModalWidget=lambda: modal))}
    exec(compile(ast.Module(body=[method], type_ignores=[]), str(source), "exec"), namespace)
    assert namespace["promote_window"]()
    assert calls == [84]
