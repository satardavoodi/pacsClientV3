"""Guard test for the [CPU_BUDGET] priority boost in main.py (fixed 2026-08-23).

Root cause it pins
------------------
`main.py` has always *asked* for ABOVE_NORMAL_PRIORITY_CLASS on Windows, but the
request never landed. `GetCurrentProcess()` returns the pseudo-handle
`(HANDLE)-1` == 0xFFFFFFFFFFFFFFFF. Under ctypes' *default* restype of `c_int`
that value is truncated to a 32-bit -1, and passing that Python int on as an
untyped argument makes the x64 call pass a 32-bit value where a 64-bit HANDLE
is expected. `SetPriorityClass` therefore received a malformed handle and
returned 0 with GetLastError() == 6 (ERROR_INVALID_HANDLE) on EVERY launch,
leaving the app at Normal priority. It was visible the whole time as one
"[CPU_BUDGET] SetPriorityClass failed (err=6)" line per session.

The fix is three ctypes type declarations. They are load-bearing, not
decoration, so they are pinned here along with their ordering: the restype must
be set BEFORE the handle is taken, or the handle is truncated again.

Source-pin guard (no PySide6/QApplication needed) + one read-only behavioural
probe that reproduces the truncation on Windows without touching any priority.

Ref: REGRESSION_CATALOG.md - CPU_BUDGET priority boost never applied.
"""

from __future__ import annotations

import ctypes
import sys
import textwrap
import types
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
MAIN = REPO / "main.py"

_BLOCK_START = "CPU BUDGET: Raise main process priority"
_BLOCK_END = "except Exception as _pri_exc:"


def _priority_block() -> str:
    """Return just the CPU-budget block.

    Bounded by real source markers, never by a fixed character count -- a
    fixed window has silently truncated guards in this repo four times.
    """
    src = MAIN.read_text(encoding="utf-8", errors="replace")
    start = src.index(_BLOCK_START)
    end = src.index(_BLOCK_END, start)
    return src[start:end]


def _code_only(block: str) -> str:
    """Drop comment lines so a guard can never be satisfied by a comment."""
    out = []
    for line in block.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        out.append(line)
    return "\n".join(out)


# ---------------------------------------------------------------- source pins

def test_priority_block_still_exists():
    # Pre-existing behaviour must be preserved, not replaced.
    block = _priority_block()
    assert "ABOVE_NORMAL" in block or "0x00008000" in block
    assert "SetPriorityClass" in block


def test_getcurrentprocess_restype_is_pointer_sized():
    # FAILS pre-fix: the line did not exist.
    code = _code_only(_priority_block())
    assert "_k32.GetCurrentProcess.restype = ctypes.c_void_p" in code, (
        "GetCurrentProcess must declare a pointer-sized restype or the "
        "pseudo-handle truncates to a 32-bit -1"
    )


def test_setpriorityclass_argtypes_declare_a_handle():
    # FAILS pre-fix: the line did not exist.
    code = _code_only(_priority_block())
    assert "_k32.SetPriorityClass.argtypes = [ctypes.c_void_p, ctypes.c_uint]" in code, (
        "SetPriorityClass must declare a pointer-sized first argument"
    )


def test_setpriorityclass_restype_declared():
    # FAILS pre-fix: the line did not exist.
    code = _code_only(_priority_block())
    assert "_k32.SetPriorityClass.restype = ctypes.c_int" in code


def test_restype_is_set_before_the_handle_is_taken():
    # Ordering is the whole point: setting restype after the call is a no-op.
    code = _code_only(_priority_block())
    i_restype = code.index("_k32.GetCurrentProcess.restype")
    i_handle = code.index("_hproc = _k32.GetCurrentProcess()")
    assert i_restype < i_handle, (
        "restype must be declared before GetCurrentProcess() is called"
    )


def test_argtypes_are_set_before_setpriorityclass_is_called():
    code = _code_only(_priority_block())
    i_argtypes = code.index("_k32.SetPriorityClass.argtypes")
    i_call = code.index("if _k32.SetPriorityClass(_hproc, _pri_class):")
    assert i_argtypes < i_call


def test_failure_is_still_reported_not_swallowed():
    # The err=6 line is how this was found. Keep the diagnostic.
    block = _priority_block()
    assert "[CPU_BUDGET] SetPriorityClass failed (err=%d)" in block
    assert "_k32.GetLastError()" in block


def test_success_is_logged():
    block = _priority_block()
    assert "[CPU_BUDGET] Main process priority set to %s" in block


def test_normal_escape_hatch_preserved():
    # AIPACS_PRIORITY=normal must still skip the boost entirely (kill switch).
    # RE-PINNED 2026-08-23, not worked around: the default argument moved from
    # the literal 'above_normal' to the build-type-resolved _pri_default. The
    # property being guarded -- AIPACS_PRIORITY is read and 'normal' skips the
    # call -- is unchanged; only the spelling moved.
    code = _code_only(_priority_block())
    assert "os.environ.get('AIPACS_PRIORITY', _pri_default)" in code
    assert "if _pri_env != 'normal':" in code


def test_high_is_the_default_only_for_installed_builds():
    """RE-PINNED 2026-08-23 — the POLICY changed, deliberately.

    This guard used to assert `_pri_map.get(_pri_env, 0x00008000)`, i.e. "HIGH
    is never the default". The owner asked for HIGH on deployed workstations,
    so the rule is now build-type-dependent. The guard is re-pinned to the NEW
    policy rather than deleted, so a later edit that quietly makes HIGH the
    default for source runs too is still caught.
    """
    code = _code_only(_priority_block())
    assert "_pri_default = 'high' if _pri_frozen else 'above_normal'" in code
    assert "_pri_map.get(_pri_env, _pri_map[_pri_default])" in code
    assert "0x00008000" not in code.split("_pri_map = {")[-1].split("}")[-1], (
        "no hard-coded class may survive after the map — the fallback must be "
        "the resolved default"
    )


def test_block_stays_inside_its_own_try_except():
    # A ctypes/platform surprise must never break startup.
    src = MAIN.read_text(encoding="utf-8", errors="replace")
    start = src.index(_BLOCK_START)
    end = src.index(_BLOCK_END, start)
    assert "try:" in src[start:end]
    assert "if sys.platform == 'win32':" in src[start:end]


# ------------------------------------------------------- behavioural evidence

@pytest.mark.skipif(sys.platform != "win32", reason="Windows pseudo-handle semantics")
def test_untyped_pseudo_handle_is_rejected_by_windows():
    """Reproduce the defect read-only, using GetPriorityClass (no side effects).

    GetPriorityClass takes the same HANDLE as SetPriorityClass and returns 0 on
    failure, so it exercises the identical truncation without changing the
    priority of the test runner.
    """
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)  # fresh, isolated instance
    handle = k32.GetCurrentProcess()                       # default restype -> c_int
    assert handle == -1, "expected the truncated 32-bit pseudo-handle"
    assert k32.GetPriorityClass(handle) == 0, (
        "if this passes, the truncation no longer fails and the guard needs review"
    )
    assert ctypes.get_last_error() == 6  # ERROR_INVALID_HANDLE


@pytest.mark.skipif(sys.platform != "win32", reason="Windows pseudo-handle semantics")
def test_typed_pseudo_handle_is_accepted_by_windows():
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)  # fresh, isolated instance
    k32.GetCurrentProcess.restype = ctypes.c_void_p
    k32.GetPriorityClass.argtypes = [ctypes.c_void_p]
    k32.GetPriorityClass.restype = ctypes.c_uint
    handle = k32.GetCurrentProcess()
    assert handle == 0xFFFFFFFFFFFFFFFF, "expected the full 64-bit pseudo-handle"
    assert k32.GetPriorityClass(handle) != 0, "typed handle must be accepted"


# ------------------------------------------- build-type default (2026-08-23)
#
# "On other PCs use high priority." The rule the app evaluates at startup is
# the build type: a frozen/installed build is a clinical workstation whose
# whole job is this app, so it gets HIGH; a source run is a developer box that
# is also running an IDE, a VM and a compiler, so it stays ABOVE_NORMAL.
#
# These are BEHAVIOURAL, not source pins: the resolution lines are lifted out
# of main.py by anchor and executed against stubbed inputs, so they test what
# the shipped code actually decides. Bounded by real anchors, never by a
# character count.

_RESOLVE_START = "_pri_default = 'high' if _pri_frozen else 'above_normal'"
_RESOLVE_END = "_pri_class = _pri_map.get(_pri_env, _pri_map[_pri_default])"


def _resolution_source() -> str:
    block = _priority_block()
    i = block.rindex("\n", 0, block.index(_RESOLVE_START)) + 1
    j = block.index(_RESOLVE_END) + len(_RESOLVE_END)
    return textwrap.dedent(block[i:j])


def _resolve(frozen: bool, env: dict) -> dict:
    """Execute main.py's own resolution lines against stubbed inputs."""
    ns = {"_pri_frozen": frozen, "os": types.SimpleNamespace(environ=env)}
    exec(compile(_resolution_source(), "<main.py:priority>", "exec"), ns)
    return ns


def test_frozen_builds_default_to_high():
    ns = _resolve(frozen=True, env={})
    assert ns["_pri_default"] == "high"
    assert ns["_pri_env"] == "high"
    assert ns["_pri_class"] == 0x00000080, "HIGH_PRIORITY_CLASS"


def test_source_runs_default_to_above_normal():
    # The developer box must NOT be promoted above the tools used to build it.
    ns = _resolve(frozen=False, env={})
    assert ns["_pri_default"] == "above_normal"
    assert ns["_pri_class"] == 0x00008000, "ABOVE_NORMAL_PRIORITY_CLASS"


def test_env_var_overrides_the_build_type_default_both_ways():
    down = _resolve(frozen=True, env={"AIPACS_PRIORITY": "above_normal"})
    assert down["_pri_class"] == 0x00008000, "env must be able to demote a frozen build"
    up = _resolve(frozen=False, env={"AIPACS_PRIORITY": "high"})
    assert up["_pri_class"] == 0x00000080, "env must be able to promote a source run"


def test_normal_kill_switch_wins_on_a_frozen_build():
    ns = _resolve(frozen=True, env={"AIPACS_PRIORITY": "normal"})
    assert ns["_pri_env"] == "normal"
    # and the source must skip the call entirely for 'normal'
    assert "if _pri_env != 'normal':" in _code_only(_priority_block())


def test_env_value_is_case_and_space_insensitive():
    ns = _resolve(frozen=False, env={"AIPACS_PRIORITY": "  HIGH \n"})
    assert ns["_pri_class"] == 0x00000080


def test_unknown_value_falls_back_to_the_machine_default_not_a_constant():
    # The pre-2026-08-23 code hard-coded 0x00008000 here, so a typo on a
    # clinical workstation silently demoted it from HIGH to ABOVE_NORMAL.
    ns = _resolve(frozen=True, env={"AIPACS_PRIORITY": "turbo"})
    assert ns["_pri_class"] == 0x00000080, (
        "an unrecognised AIPACS_PRIORITY must fall back to the machine's own "
        "default, never to a hard-coded class"
    )
    ns2 = _resolve(frozen=False, env={"AIPACS_PRIORITY": "turbo"})
    assert ns2["_pri_class"] == 0x00008000


def test_frozen_detection_uses_the_canonical_helper():
    code = _code_only(_priority_block())
    assert "from aipacs_runtime import is_frozen" in code, (
        "must use the helper that understands Nuitka's __compiled__, not a "
        "bare sys.frozen check"
    )


def test_a_broken_frozen_probe_degrades_to_the_safe_default():
    # Startup must never fail because the priority probe raised.
    code = _code_only(_priority_block())
    i_import = code.index("from aipacs_runtime import is_frozen")
    tail = code[i_import:]
    assert "except Exception:" in tail
    assert "_pri_frozen = False" in tail, (
        "a failed probe must fall back to the SOURCE default, not to high"
    )


def test_all_three_classes_are_still_reachable():
    code = _code_only(_priority_block())
    for name, value in (("normal", "0x00000020"),
                        ("above_normal", "0x00008000"),
                        ("high", "0x00000080")):
        assert f"'{name}':" in code and value in code


def test_log_line_records_which_default_was_used():
    # On an end-user machine the log is the only way to tell what happened.
    block = _priority_block()
    assert "default=%s, frozen=%s" in block
    assert "_pri_default, _pri_frozen" in block
