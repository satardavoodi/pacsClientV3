"""Audit ``setFixed*`` calls across the codebase.

This tool is the ongoing CI signal for the responsive-UI convention
(see ``docs/conventions/RESPONSIVE_UI_CONVENTION.md``). It greps for
``setFixedSize`` / ``setFixedWidth`` / ``setFixedHeight`` calls in
``PacsClient/`` and ``modules/`` and classifies each one against the seven
archetypes from
``docs/plans/RESPONSIVE_UI_STRUCTURAL_PATTERN_2026-05-26.md``.

Usage
=====
Project-wide audit:

    python tools/dev/audit_fixed_sizes.py

Per-file audit:

    python tools/dev/audit_fixed_sizes.py PacsClient/pacs/workstation_ui/mainwindow_ui.py

Diff mode — list only the lines added by a branch (useful in PR review):

    python tools/dev/audit_fixed_sizes.py --diff main..HEAD

Output columns
==============
- file path : line
- the matched call
- a heuristic archetype guess (1..7 or "leaf")

The archetype guess is a hint, not a verdict. A reviewer must still confirm.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional


# Pattern matches setFixedSize / setFixedWidth / setFixedHeight calls.
_FIXED_RE = re.compile(r"\bsetFixed(Size|Width|Height)\b\s*\(([^)]*)\)")

# Heuristic archetype hints. None is conclusive — they are starting points.
_LEAF_CONTEXT_HINTS = (
    "icon", "badge", "separator", "divider", "indicator", "dot", "spacer",
)
_CHIP_CONTEXT_HINTS = ("chip", "tab", "tabwidget", "title_bar", "titlebar")
_TOOLBAR_CONTEXT_HINTS = ("toolbar", "button_row", "btn_row")
_FORM_CONTEXT_HINTS = ("edit", "combo", "spin", "line_edit", "lineedit", "form")
_LABEL_CONTEXT_HINTS = ("label", "header", "title", "badge_text")
_PANEL_CONTEXT_HINTS = ("panel", "pane", "sidebar", "container")


@dataclass(frozen=True)
class Hit:
    """A single ``setFixed*`` call site."""
    path: str
    line: int
    snippet: str
    archetype_hint: str


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""


def _guess_archetype(snippet: str, context_above: str) -> str:
    """Heuristic — what archetype does this call likely belong to?

    Returns one of: "1", "2", "3", "4", "5", "6", "7", "leaf", "?"
    """
    low = (snippet + " " + context_above).lower()

    if any(h in low for h in _LEAF_CONTEXT_HINTS):
        return "leaf"

    # Width-only with small numbers (≤16) often = leaf icon.
    m = re.search(r"setFixed(?:Width|Height|Size)\s*\(\s*(\d+)", snippet)
    if m and int(m.group(1)) <= 16:
        return "leaf"

    if any(h in low for h in _CHIP_CONTEXT_HINTS):
        return "1"
    if any(h in low for h in _TOOLBAR_CONTEXT_HINTS):
        return "1"
    if any(h in low for h in _LABEL_CONTEXT_HINTS):
        return "3"  # likely single-line elision candidate
    if any(h in low for h in _FORM_CONTEXT_HINTS):
        return "5"
    if any(h in low for h in _PANEL_CONTEXT_HINTS):
        return "4"
    return "?"


def _scan_text(path: Path, text: str) -> list[Hit]:
    hits: list[Hit] = []
    lines = text.splitlines()
    for i, line in enumerate(lines, start=1):
        for match in _FIXED_RE.finditer(line):
            snippet = match.group(0)
            # 2 lines of context above, for variable name hints.
            ctx = "\n".join(lines[max(0, i - 3): i - 1])
            hits.append(
                Hit(
                    path=str(path),
                    line=i,
                    snippet=snippet.strip(),
                    archetype_hint=_guess_archetype(snippet, ctx),
                )
            )
    return hits


def _gather_files(root: Path, scope: Iterable[str]) -> list[Path]:
    files: list[Path] = []
    for sub in scope:
        sub_path = root / sub
        if sub_path.is_file() and sub_path.suffix == ".py":
            files.append(sub_path)
            continue
        if not sub_path.is_dir():
            continue
        files.extend(sub_path.rglob("*.py"))
    return files


def _git_diff_lines(diff_range: str, root: Path) -> list[tuple[Path, int, str]]:
    """Return added lines from ``git diff <range>`` as (path, line, content)."""
    try:
        out = subprocess.check_output(
            ["git", "diff", diff_range, "--", "*.py"],
            cwd=str(root),
            text=True,
            stderr=subprocess.PIPE,
        )
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        print(f"[audit] could not run git diff: {exc}", file=sys.stderr)
        return []

    added: list[tuple[Path, int, str]] = []
    current_path: Optional[Path] = None
    new_line_no = 0
    for raw in out.splitlines():
        if raw.startswith("+++ b/"):
            current_path = root / raw[6:]
            continue
        if raw.startswith("@@"):
            # Parse the +n,m hunk header to track new-file line numbers.
            m = re.search(r"\+(\d+)", raw)
            if m:
                new_line_no = int(m.group(1)) - 1
            continue
        if raw.startswith("+") and not raw.startswith("+++"):
            new_line_no += 1
            if current_path is not None:
                added.append((current_path, new_line_no, raw[1:]))
        elif not raw.startswith("-"):
            new_line_no += 1
    return added


def run(
    paths: Iterable[Path] | None,
    *,
    diff: Optional[str],
    root: Path,
) -> int:
    """Main entry. Returns 0 on success, non-zero on error."""
    if diff:
        added = _git_diff_lines(diff, root)
        hits: list[Hit] = []
        for p, lineno, content in added:
            if _FIXED_RE.search(content):
                m = _FIXED_RE.search(content)
                hits.append(
                    Hit(
                        path=str(p.relative_to(root)),
                        line=lineno,
                        snippet=m.group(0).strip() if m else content.strip(),
                        archetype_hint=_guess_archetype(content, ""),
                    )
                )
        _print_report(hits, header=f"NEW setFixed* calls in {diff}")
        return 0

    # Expand user-supplied paths: a directory becomes its recursive .py files.
    raw = list(paths) if paths else None
    if raw is None:
        files = _gather_files(root, ("PacsClient", "modules"))
    else:
        files = []
        for p in raw:
            if p.is_file() and p.suffix == ".py":
                files.append(p)
            elif p.is_dir():
                files.extend(p.rglob("*.py"))
    all_hits: list[Hit] = []
    for f in files:
        rel = f.relative_to(root) if f.is_absolute() else f
        all_hits.extend(_scan_text(rel, _read_text(f)))
    _print_report(all_hits, header="Project-wide setFixed* audit")
    return 0


def _print_report(hits: list[Hit], *, header: str) -> None:
    print(f"=== {header} ===")
    if not hits:
        print("  (no matches)")
        return
    # Group by archetype hint for the summary.
    counts: dict[str, int] = {}
    for h in hits:
        counts[h.archetype_hint] = counts.get(h.archetype_hint, 0) + 1
    print(f"  total: {len(hits)}")
    for k in sorted(counts):
        print(f"    archetype {k}: {counts[k]}")
    print()
    for h in hits:
        print(f"  {h.path}:{h.line:<6} [{h.archetype_hint}] {h.snippet}")


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    parser.add_argument(
        "paths",
        nargs="*",
        type=Path,
        help="Files or directories to audit (default: PacsClient/ and modules/).",
    )
    parser.add_argument(
        "--diff",
        default=None,
        help="Audit only lines added by a git range, e.g. 'main..HEAD'.",
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path.cwd(),
        help="Repository root (defaults to current directory).",
    )
    args = parser.parse_args(argv)
    return run(args.paths or None, diff=args.diff, root=args.root)


if __name__ == "__main__":
    raise SystemExit(main())
