"""Windows source-build multiprocessing bootstrap safety guards."""

import multiprocessing as mp
from pathlib import Path
import sys

import pytest

from PacsClient.utils.windows_multiprocessing import configure_hidden_multiprocessing


def _read_shared_event(event, marker_path: str) -> None:
    """Spawn-safe probe: record whether a shared Event remains accessible."""
    marker = Path(marker_path)
    try:
        value = bool(event.is_set())
    except BaseException as exc:  # child evidence must survive a pythonw console-less run
        marker.write_text(
            f"error:{type(exc).__name__}:{getattr(exc, 'winerror', '')}",
            encoding="utf-8",
        )
        return
    marker.write_text(f"ok:{int(value)}", encoding="utf-8")


def _repo_root() -> Path:
    path = Path(__file__).resolve()
    for parent in path.parents:
        if (parent / "PacsClient").is_dir() and (parent / "main.py").is_file():
            return parent
    raise RuntimeError("repository root not found")


def test_hidden_spawn_helper_exists_and_is_installed_before_freeze_support():
    root = _repo_root()
    helper = root / "PacsClient" / "utils" / "windows_multiprocessing.py"
    assert helper.is_file(), "the source build needs a pythonw spawn authority"

    main_src = (root / "main.py").read_text(encoding="utf-8")
    configure = main_src.find("configure_hidden_multiprocessing(multiprocessing)")
    freeze = main_src.find("multiprocessing.freeze_support()")
    assert -1 < configure < freeze


class _MultiprocessingRecorder:
    def __init__(self):
        self.executable = None

    def set_executable(self, executable):
        self.executable = executable


def test_windows_source_python_uses_gui_subsystem_interpreter():
    recorder = _MultiprocessingRecorder()

    selected = configure_hidden_multiprocessing(
        recorder,
        platform="win32",
        executable=r"C:\Runtime\python.exe",
        frozen=False,
        is_file=lambda path: path == r"C:\Runtime\pythonw.exe",
    )

    assert selected == r"C:\Runtime\pythonw.exe"
    assert recorder.executable == selected


def test_frozen_and_non_windows_runtimes_are_not_overridden():
    for platform, frozen in (("win32", True), ("linux", False)):
        recorder = _MultiprocessingRecorder()
        selected = configure_hidden_multiprocessing(
            recorder,
            platform=platform,
            executable=r"C:\Runtime\python.exe",
            frozen=frozen,
            is_file=lambda _path: True,
        )
        assert selected is None
        assert recorder.executable is None


def test_installed_application_executable_is_never_overridden():
    recorder = _MultiprocessingRecorder()

    selected = configure_hidden_multiprocessing(
        recorder,
        platform="win32",
        executable=r"C:\Program Files\AI-PACS\AIPacs.exe",
        frozen=False,
        is_file=lambda _path: True,
    )

    assert selected is None
    assert recorder.executable is None


def test_missing_pythonw_falls_back_without_breaking_spawn():
    recorder = _MultiprocessingRecorder()
    selected = configure_hidden_multiprocessing(
        recorder,
        platform="win32",
        executable=r"C:\Runtime\python.exe",
        frozen=False,
        is_file=lambda _path: False,
    )
    assert selected is None
    assert recorder.executable is None


def test_virtualenv_redirector_is_never_selected_as_spawn_executable():
    """A venv pythonw redirector adds a launcher hop and breaks inherited IPC
    handles on Windows; supported source runs must retain the default executable.
    """
    recorder = _MultiprocessingRecorder()

    selected = configure_hidden_multiprocessing(
        recorder,
        platform="win32",
        executable=r"C:\Project\.venv\Scripts\python.exe",
        base_executable=r"C:\Python313\python.exe",
        frozen=False,
        is_file=lambda _path: True,
    )

    assert selected is None
    assert recorder.executable is None


@pytest.mark.skipif(sys.platform != "win32", reason="Windows spawn-handle regression")
def test_supported_source_spawn_preserves_shared_event_handle(tmp_path):
    """Behavioral reproduction of the download cancellation Event failure.

    This executes the real source bootstrap policy, creates the same spawn-context
    Event used by DownloadProcessWorker, and dereferences it in a real child.
    """
    from multiprocessing import spawn

    original_executable = spawn.get_executable()
    process = None
    try:
        configure_hidden_multiprocessing(mp)
        ctx = mp.get_context("spawn")
        event = ctx.Event()
        event.set()
        marker = tmp_path / "event-probe.txt"
        process = ctx.Process(
            target=_read_shared_event,
            args=(event, str(marker)),
            name="AIPACS-IPC-guard",
        )
        process.start()
        process.join(timeout=20.0)

        assert not process.is_alive(), "spawn probe did not terminate"
        assert marker.read_text(encoding="utf-8") == "ok:1"
        assert process.exitcode == 0
    finally:
        if process is not None and process.is_alive():
            process.terminate()
            process.join(timeout=5.0)
        mp.set_executable(original_executable)
