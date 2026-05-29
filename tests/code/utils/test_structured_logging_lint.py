"""Source-scan lint test (Phase 0.1 of ARCHITECTURE_REVIEW_2026-04-30 plan).

Detects the silent-log-drop bug class that R13 / R19 / R22 all share:

    logger.info(..., extra={"component": "download", ...})  # BUG: dropped

Because ``download`` component threshold is WARNING in
``PacsClient/utils/diagnostic_logging.py``, an INFO emit with that
component is silently dropped at the queued listener.

Rule:
    For every Python file under ``modules/`` and ``PacsClient/``, any
    ``logger.<level>(...)`` call that includes ``extra={"component": "<X>"}``
    must use a level ≥ MIN_LEVEL_BY_COMPONENT[X].

The test scans source text rather than parsing the AST; this is
intentional so the rule is debuggable by ``grep`` and survives partial
refactors. Multi-line ``extra=`` blocks ARE supported.

To suppress a known-OK call site, append a comment:
    logger.info("...", extra={"component": "download"})  # noqa: structured-logging

Run:
    .venv\\Scripts\\python.exe -m pytest tests/utils/test_structured_logging_lint.py -v
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Iterator

import pytest

from PacsClient.utils.structured_logging import MIN_LEVEL_BY_COMPONENT


REPO_ROOT = Path(__file__).resolve().parents[3]


# Folders to scan. Plugin-package mirrors are excluded so we do not
# double-count the same violation twice (canonical files are the source
# of truth; mirrors are checked by SHA equality elsewhere).
SCAN_ROOTS = [
    REPO_ROOT / "modules",
    REPO_ROOT / "PacsClient",
]

EXCLUDE_PATH_FRAGMENTS = (
    "builder/plugin package/",
    "builder\\plugin package\\",
    "tests/",
    "tests\\",
    "__pycache__",
    ".venv",
    ".venv_build",
)

# Specific files to exclude (e.g. the structured_logging module itself,
# whose docstring contains an example of the bad pattern for documentation
# purposes).
EXCLUDE_FILES = {
    str(REPO_ROOT / "PacsClient" / "utils" / "structured_logging.py"),
}


# Map textual level → numeric level for comparison vs MIN_LEVEL_BY_COMPONENT.
_LEVEL_BY_NAME = {
    "debug": logging.DEBUG,
    "info": logging.INFO,
    "warning": logging.WARNING,
    "warn": logging.WARNING,
    "error": logging.ERROR,
    "critical": logging.CRITICAL,
    "exception": logging.ERROR,
}

# Regex: capture ``<logger>.<level>(`` callsites. We keep the pattern simple
# and rely on a follow-up search for the matching ``component=`` token within
# the next ~600 characters of source.
_CALL_RE = re.compile(
    r"""
    (?P<full>
        (?P<obj>(?:self\._?)?(?:\w+\.)?logger|logger)
        \.
        (?P<level>debug|info|warning|warn|error|exception|critical|log)
        \s*\(
    )
    """,
    re.VERBOSE,
)

_COMPONENT_RE = re.compile(
    r"""extra\s*=\s*\{[^{}]*?["']component["']\s*:\s*["'](?P<component>\w+)["']""",
    re.DOTALL,
)

_NOQA_RE = re.compile(r"#\s*noqa\s*:?\s*structured-logging", re.IGNORECASE)


def _iter_source_files() -> Iterator[Path]:
    for root in SCAN_ROOTS:
        if not root.exists():
            continue
        for path in root.rglob("*.py"):
            s = str(path)
            if any(frag in s for frag in EXCLUDE_PATH_FRAGMENTS):
                continue
            if s in EXCLUDE_FILES:
                continue
            yield path


def _find_call_end(text: str, open_paren_pos: int) -> int:
    """Return index just past the matching close paren, or len(text) on failure."""
    depth = 0
    i = open_paren_pos
    n = len(text)
    in_str = None
    while i < n:
        ch = text[i]
        if in_str is not None:
            if ch == "\\":
                i += 2
                continue
            if ch == in_str:
                in_str = None
        else:
            if ch in ("'", '"'):
                in_str = ch
            elif ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    return i + 1
        i += 1
    return n


def _scan_file(path: Path) -> list[dict]:
    violations: list[dict] = []
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return violations

    for match in _CALL_RE.finditer(text):
        level_name = match.group("level").lower()
        if level_name == "log":
            # logger.log(level, ...) — level is a runtime expression; skip.
            continue
        level = _LEVEL_BY_NAME.get(level_name)
        if level is None:
            continue

        open_paren_pos = match.end() - 1  # position of '(' captured by regex
        call_end = _find_call_end(text, open_paren_pos)
        call_text = text[open_paren_pos:call_end]

        # Check noqa on the same source line (search forward to next \n).
        line_end = text.find("\n", call_end)
        if line_end == -1:
            line_end = len(text)
        following = text[call_end:line_end]
        if _NOQA_RE.search(following):
            continue

        comp_match = _COMPONENT_RE.search(call_text)
        if not comp_match:
            continue

        component = comp_match.group("component")
        min_level = MIN_LEVEL_BY_COMPONENT.get(component)
        if min_level is None:
            continue

        # Policy: DEBUG is always permitted regardless of component threshold —
        # DEBUG is explicit "verbose only, do not surface in production". The
        # silent-drop bug class is INFO+ calls developers expected to surface
        # in production but were dropped by the queued listener threshold. Only
        # flag levels at or above INFO that fall below the component minimum.
        if level >= logging.INFO and level < min_level:
            line_num = text.count("\n", 0, match.start()) + 1
            try:
                rel_path = str(path.relative_to(REPO_ROOT))
            except ValueError:
                rel_path = str(path)
            violations.append(
                {
                    "path": rel_path,
                    "line": line_num,
                    "level": logging.getLevelName(level),
                    "component": component,
                    "min_level": logging.getLevelName(min_level),
                    "snippet": text[match.start() : match.start() + 120].replace(
                        "\n", " "
                    ),
                }
            )
    return violations


def _all_violations() -> list[dict]:
    all_v: list[dict] = []
    for path in _iter_source_files():
        all_v.extend(_scan_file(path))
    return all_v


def test_no_silent_drop_violations():
    """No ``logger.info(..., extra={"component": "download"})`` style calls."""
    violations = _all_violations()
    if violations:
        details = "\n".join(
            f"  {v['path']}:{v['line']}  level={v['level']}<{v['min_level']} "
            f"component={v['component']!r}\n    {v['snippet']!r}"
            for v in violations
        )
        pytest.fail(
            "Silent-drop log violations found "
            f"({len(violations)} site(s)). Each call uses a log level lower "
            "than the component's minimum threshold and will be silently "
            "dropped by the queued listener. Use the typed helpers in "
            "``PacsClient/utils/structured_logging.py`` (emit_download_event "
            "etc.), bump the level explicitly, or append "
            "``# noqa: structured-logging`` to the offending line.\n" + details
        )


def test_scanner_finds_synthetic_violation(tmp_path):
    """Self-test: the scanner detects a known violation pattern."""
    bad = tmp_path / "bad.py"
    bad.write_text(
        'logger.info("hi", extra={"component": "download"})\n',
        encoding="utf-8",
    )
    violations = _scan_file(bad)
    assert len(violations) == 1
    assert violations[0]["component"] == "download"
    assert violations[0]["level"] == "INFO"


def test_scanner_respects_noqa(tmp_path):
    bad = tmp_path / "ok.py"
    bad.write_text(
        'logger.info("hi", extra={"component": "download"})  # noqa: structured-logging\n',
        encoding="utf-8",
    )
    violations = _scan_file(bad)
    assert violations == []


def test_scanner_accepts_warning_level(tmp_path):
    ok = tmp_path / "ok2.py"
    ok.write_text(
        'logger.warning("hi", extra={"component": "download"})\n',
        encoding="utf-8",
    )
    violations = _scan_file(ok)
    assert violations == []


def test_scanner_accepts_info_for_viewer(tmp_path):
    ok = tmp_path / "ok3.py"
    ok.write_text(
        'logger.info("hi", extra={"component": "viewer"})\n',
        encoding="utf-8",
    )
    violations = _scan_file(ok)
    assert violations == []


def test_scanner_handles_multiline_extra(tmp_path):
    bad = tmp_path / "bad2.py"
    bad.write_text(
        'logger.info(\n'
        '    "hi",\n'
        '    extra={\n'
        '        "component": "download",\n'
        '        "study": "X",\n'
        '    },\n'
        ')\n',
        encoding="utf-8",
    )
    violations = _scan_file(bad)
    assert len(violations) == 1
    assert violations[0]["component"] == "download"
