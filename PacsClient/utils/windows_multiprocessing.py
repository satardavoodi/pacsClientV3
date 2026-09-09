"""Windows multiprocessing bootstrap policy for the source workstation.

The development entry point can run with the console-subsystem ``python.exe``.
The equivalent direct ``pythonw.exe`` interpreter can hide source-build spawn
children, but a virtual-environment ``Scripts/pythonw.exe`` is a redirector: it
adds another process hop and cannot preserve inherited multiprocessing semaphore
handles.  Supported source runs use a virtual environment, so they must retain
Python's default spawn executable.

Frozen builds already use their packaged executable and must remain unchanged.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Callable, Optional


def configure_hidden_multiprocessing(
    multiprocessing_module: Any,
    *,
    platform: Optional[str] = None,
    executable: Optional[str] = None,
    base_executable: Optional[str] = None,
    frozen: Optional[bool] = None,
    is_file: Callable[[str], bool] = os.path.isfile,
) -> Optional[str]:
    """Select direct ``pythonw.exe`` only when no venv redirector is involved.

    Returns the selected executable path, or ``None`` when no override was
    needed or available.  The function is deliberately fail-safe because it
    runs before the application logging stack is configured.
    """

    try:
        current_platform = sys.platform if platform is None else str(platform)
        executable_was_supplied = executable is not None
        current_executable = sys.executable if executable is None else str(executable)
        if base_executable is not None:
            current_base_executable = str(base_executable)
        elif executable_was_supplied:
            # Synthetic/direct-interpreter callers historically supplied only
            # ``executable``. Treat that as a direct interpreter unless they
            # explicitly provide a different base executable.
            current_base_executable = current_executable
        else:
            current_base_executable = str(
                getattr(sys, "_base_executable", current_executable) or current_executable
            )
        current_frozen = bool(getattr(sys, "frozen", False)) if frozen is None else bool(frozen)

        if not current_platform.startswith("win") or current_frozen:
            return None
        if Path(current_executable).name.casefold() != "python.exe":
            return None

        # CPython's Windows venv launchers are redirectors. Replacing the spawn
        # executable with the sibling pythonw redirector creates a grandchild;
        # multiprocessing Event/Queue semaphore handles are prepared for the
        # direct child and fail there with WinError 5. Preserve the default
        # executable whenever the running interpreter differs from its base.
        if os.path.normcase(os.path.abspath(current_executable)) != os.path.normcase(
            os.path.abspath(current_base_executable)
        ):
            return None

        gui_executable = str(Path(current_executable).with_name("pythonw.exe"))
        if not is_file(gui_executable):
            return None

        multiprocessing_module.set_executable(gui_executable)
        return gui_executable
    except Exception:
        return None
