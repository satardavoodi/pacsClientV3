"""Architectural lint enforcing R22 combo-signal hygiene.

R22 (v2.4.7) root cause: ``priority_combo.setCurrentText("Normal")`` inside
``_DmDetailsMixin._clear_details_panel`` ran while a ``currentTextChanged``
slot was connected, fired the slot synchronously, and silently demoted the
just-promoted CRITICAL study back to NORMAL via ``state_store.update`` while
also recursively reentering ``_refresh_table_order``. The fix wraps every
programmatic combo write in::

    try:
        widget.blockSignals(True)
        widget.setCurrentText(...)
    finally:
        widget.blockSignals(False)

This lint enforces that discipline as code, not memory.

Scope: ``modules/download_manager/ui/widget/_dm_*.py`` — the canonical DM UI
mixins (and their plugin-package mirrors via the same scan).

Rule: any ``self.<name>.setCurrentText(...)`` / ``setCurrentIndex(...)`` /
``setCurrentData(...)`` call on a combo widget that also has a
``.currentTextChanged.connect``, ``.currentIndexChanged.connect``, or
``.activated.connect`` somewhere in the same file MUST satisfy ONE of:

1. The call appears in source-order BEFORE the ``.connect(...)`` line for
   that widget — init/setup time, no signal handler is attached yet.
2. The call is bracketed by ``self.<name>.blockSignals(True)`` / ``False``
   within a small window of surrounding lines.
3. The call line ends with ``# noqa: combo-signal`` (explicit opt-out).

Anything else is a violation.

Companion to R23 silent-drop lint: same architecture (line-based scan),
same opt-out style, same per-line precision.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable, List, Tuple

import pytest


REPO_ROOT = Path(__file__).resolve().parents[3]
TARGET_DIRS = [
    REPO_ROOT / "modules" / "download_manager" / "ui" / "widget",
]

# A "signaled widget" is one whose signal is wired in the same file.
_SIGNAL_NAMES = (
    "currentTextChanged",
    "currentIndexChanged",
    "activated",
    "highlighted",
)
_WRITE_METHODS = (
    "setCurrentText",
    "setCurrentIndex",
    "setCurrentData",
)
# Receiver pattern: self.<name> or just <name> (local var).
_RECEIVER = r"(?:self\.)?([A-Za-z_][A-Za-z0-9_]*)"

_CONNECT_RE = re.compile(
    rf"{_RECEIVER}\.(?:{'|'.join(_SIGNAL_NAMES)})\.connect\("
)
_WRITE_RE = re.compile(rf"{_RECEIVER}\.(?:{'|'.join(_WRITE_METHODS)})\(")
_BLOCK_SIGNALS_RE = re.compile(
    rf"{_RECEIVER}\.blockSignals\(\s*(True|False)\s*\)"
)
_NOQA_RE = re.compile(r"#\s*noqa:\s*combo-signal\b", re.IGNORECASE)

# Window of context lines around a write to look for a blockSignals(True)
# before and a blockSignals(False) after. Five lines is generous given the
# canonical try/finally pattern uses 4-5 lines.
_CONTEXT_WINDOW = 6


def _iter_target_files() -> Iterable[Path]:
    for d in TARGET_DIRS:
        if not d.exists():
            continue
        for path in sorted(d.glob("_dm_*.py")):
            if path.is_file():
                yield path


def _find_violations_in_file(path: Path) -> List[Tuple[int, str]]:
    """Return list of ``(line_number_1based, source_line)`` violations."""
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()

    # Step 1: index every signal connect by widget name -> first connect line.
    connect_lines: dict[str, int] = {}
    for i, line in enumerate(lines, start=1):
        m = _CONNECT_RE.search(line)
        if m:
            name = m.group(1)
            # Keep the FIRST connect for each widget (earliest in source).
            connect_lines.setdefault(name, i)

    if not connect_lines:
        return []  # No signaled widgets in this file.

    # Step 2: scan for combo writes; classify each.
    violations: List[Tuple[int, str]] = []
    for i, line in enumerate(lines, start=1):
        m = _WRITE_RE.search(line)
        if not m:
            continue
        widget = m.group(1)
        if widget not in connect_lines:
            # Widget has no signal connection in this file — safe by default.
            continue
        if _NOQA_RE.search(line):
            continue
        # Init-time exception: write appears strictly BEFORE the connect line.
        if i < connect_lines[widget]:
            continue
        # blockSignals window check.
        if _is_wrapped_in_blocksignals(lines, i, widget):
            continue
        violations.append((i, line.rstrip()))
    return violations


def _is_wrapped_in_blocksignals(
    lines: List[str], idx_1based: int, widget: str
) -> bool:
    """True if the line at ``idx_1based`` is bracketed by
    ``widget.blockSignals(True)`` before and ``widget.blockSignals(False)``
    after, both within ``_CONTEXT_WINDOW`` lines."""
    start = max(1, idx_1based - _CONTEXT_WINDOW)
    end = min(len(lines), idx_1based + _CONTEXT_WINDOW)

    # Look BEFORE for blockSignals(True) on this widget.
    saw_true = False
    for j in range(idx_1based - 1, start - 1, -1):
        line = lines[j - 1]
        m = _BLOCK_SIGNALS_RE.search(line)
        if m and m.group(1) == widget and m.group(2) == "True":
            saw_true = True
            break
        if m and m.group(1) == widget and m.group(2) == "False":
            # An earlier False before any True is suspicious; bail out.
            return False
    if not saw_true:
        return False

    # Look AFTER for blockSignals(False) on this widget.
    for j in range(idx_1based + 1, end + 1):
        line = lines[j - 1]
        m = _BLOCK_SIGNALS_RE.search(line)
        if m and m.group(1) == widget and m.group(2) == "False":
            return True
    return False


# ---------------------------------------------------------------------------
# Production scan — must be empty.
# ---------------------------------------------------------------------------


def test_no_combo_signal_violations_in_dm_widget():
    """Every programmatic combo write in DM UI mixins must be safe.

    Safety = blockSignals-wrapped OR pre-connect init OR explicit
    ``# noqa: combo-signal`` opt-out. R22 regression alarm.
    """
    all_violations: List[Tuple[Path, int, str]] = []
    for path in _iter_target_files():
        for line_no, source in _find_violations_in_file(path):
            all_violations.append((path, line_no, source))

    if all_violations:
        msg = ["R22 combo-signal hygiene violations:"]
        for path, line_no, source in all_violations:
            try:
                rel = path.relative_to(REPO_ROOT)
            except ValueError:
                rel = path
            msg.append(f"  {rel}:{line_no}: {source.strip()}")
        msg.append(
            "\nFix: wrap programmatic combo writes in "
            "blockSignals(True)/setCurrentText(...)/blockSignals(False), "
            "or add '# noqa: combo-signal' with rationale."
        )
        pytest.fail("\n".join(msg))


# ---------------------------------------------------------------------------
# Self-tests for the scanner.
# ---------------------------------------------------------------------------


def test_scanner_flags_unwrapped_post_connect_write(tmp_path: Path):
    src = tmp_path / "_dm_synth.py"
    src.write_text(
        "from PySide6.QtWidgets import QComboBox\n"
        "class W:\n"
        "    def __init__(self):\n"
        "        self.priority_combo = QComboBox()\n"
        "        self.priority_combo.currentTextChanged.connect(self.on_change)\n"
        "    def reset(self):\n"
        "        self.priority_combo.setCurrentText('Normal')\n"
        "    def on_change(self, _):\n"
        "        pass\n",
        encoding="utf-8",
    )
    violations = _find_violations_in_file(src)
    assert len(violations) == 1
    assert violations[0][0] == 7  # line of the unwrapped write


def test_scanner_accepts_blocksignals_wrap(tmp_path: Path):
    src = tmp_path / "_dm_synth.py"
    src.write_text(
        "class W:\n"
        "    def __init__(self):\n"
        "        self.priority_combo.currentTextChanged.connect(self.f)\n"
        "    def reset(self):\n"
        "        try:\n"
        "            self.priority_combo.blockSignals(True)\n"
        "            self.priority_combo.setCurrentText('Normal')\n"
        "        finally:\n"
        "            self.priority_combo.blockSignals(False)\n",
        encoding="utf-8",
    )
    assert _find_violations_in_file(src) == []


def test_scanner_accepts_init_time_write_before_connect(tmp_path: Path):
    src = tmp_path / "_dm_synth.py"
    src.write_text(
        "class W:\n"
        "    def __init__(self):\n"
        "        self.priority_combo = QComboBox()\n"
        "        self.priority_combo.setCurrentText('Normal')\n"
        "        self.priority_combo.currentTextChanged.connect(self.f)\n",
        encoding="utf-8",
    )
    assert _find_violations_in_file(src) == []


def test_scanner_accepts_noqa(tmp_path: Path):
    src = tmp_path / "_dm_synth.py"
    src.write_text(
        "class W:\n"
        "    def __init__(self):\n"
        "        self.priority_combo.currentTextChanged.connect(self.f)\n"
        "    def reset(self):\n"
        "        self.priority_combo.setCurrentText('Normal')  # noqa: combo-signal\n",
        encoding="utf-8",
    )
    assert _find_violations_in_file(src) == []


def test_scanner_ignores_widget_without_signal_in_file(tmp_path: Path):
    src = tmp_path / "_dm_synth.py"
    # priority_combo has no .connect anywhere in this file -> not signaled
    # -> writes are safe by default.
    src.write_text(
        "class W:\n"
        "    def reset(self):\n"
        "        self.priority_combo.setCurrentText('Normal')\n",
        encoding="utf-8",
    )
    assert _find_violations_in_file(src) == []


def test_scanner_handles_setCurrentIndex(tmp_path: Path):
    src = tmp_path / "_dm_synth.py"
    src.write_text(
        "class W:\n"
        "    def __init__(self):\n"
        "        self.combo.currentIndexChanged.connect(self.f)\n"
        "    def reset(self):\n"
        "        self.combo.setCurrentIndex(0)\n",
        encoding="utf-8",
    )
    violations = _find_violations_in_file(src)
    assert len(violations) == 1


def test_scanner_handles_activated_signal(tmp_path: Path):
    src = tmp_path / "_dm_synth.py"
    src.write_text(
        "class W:\n"
        "    def __init__(self):\n"
        "        self.combo.activated.connect(self.f)\n"
        "    def reset(self):\n"
        "        self.combo.setCurrentText('x')\n",
        encoding="utf-8",
    )
    violations = _find_violations_in_file(src)
    assert len(violations) == 1
