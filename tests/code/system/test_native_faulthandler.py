"""Guard tests — OPT-21 production faulthandler -> native_fault.log (2026-07-07).

The frozen build previously had NO faulthandler, so a native crash (VTK/OpenGL
driver access violation — PC2 Standard-MPR crash) left ZERO trace. main.py now
enables faulthandler early via ``PacsClient/utils/native_fault_log.py``
(flag ``AIPACS_NATIVE_FAULT_LOG``, default ON).
"""

from __future__ import annotations

import faulthandler
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PacsClient.utils import native_fault_log as nfl  # noqa: E402


def test_flag_off_disables_and_creates_nothing(tmp_path, monkeypatch):
    monkeypatch.setenv("AIPACS_NATIVE_FAULT_LOG", "0")
    nfl.reset_for_tests()
    assert nfl.enable_native_fault_log(tmp_path) is None
    assert not (tmp_path / "native_fault.log").exists()
    nfl.reset_for_tests()


def test_enable_writes_marker_and_enables_faulthandler(tmp_path, monkeypatch):
    monkeypatch.delenv("AIPACS_NATIVE_FAULT_LOG", raising=False)
    nfl.reset_for_tests()
    try:
        path = nfl.enable_native_fault_log(tmp_path)
        assert path is not None
        log = Path(path)
        assert log.name == "native_fault.log"
        assert log.parent == tmp_path
        assert faulthandler.is_enabled()
        content = log.read_text(encoding="utf-8")
        assert "session start" in content
        assert f"pid=" in content

        # Idempotent: second call returns the same path, no second marker.
        again = nfl.enable_native_fault_log(tmp_path)
        assert again == path
        assert log.read_text(encoding="utf-8").count("session start") == 1
    finally:
        handle = nfl._handle
        nfl.reset_for_tests()
        # Restore faulthandler to stderr (pytest's default) before closing our file,
        # so faulthandler never points at a closed fd.
        try:
            faulthandler.enable()
        except Exception:
            pass
        if handle is not None:
            try:
                handle.close()
            except Exception:
                pass


def test_never_raises_on_unwritable_dir(monkeypatch):
    monkeypatch.delenv("AIPACS_NATIVE_FAULT_LOG", raising=False)
    nfl.reset_for_tests()
    # A path that cannot be a directory (parent is a file) must fail gracefully.
    bogus = Path(__file__)  # a file, not a dir
    result = nfl.enable_native_fault_log(bogus / "sub")
    assert result is None
    nfl.reset_for_tests()


def test_flag_default_is_on_and_mainpy_wired():
    src = (ROOT / "PacsClient" / "utils" / "native_fault_log.py").read_text(encoding="utf-8")
    assert 'os.getenv("AIPACS_NATIVE_FAULT_LOG", "1")' in src

    main_src = (ROOT / "main.py").read_text(encoding="utf-8", errors="replace")
    assert "enable_native_fault_log" in main_src, "main.py must enable the native fault log at startup"
    # Early wiring: before the heavy Qt application bootstrap begins.
    assert main_src.index("enable_native_fault_log") < main_src.index("def _maybe_nuitka_smoke_test_exit")
