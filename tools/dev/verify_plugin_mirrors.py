"""Verify plugin-package payload mirrors match their canonical sources.

Background
----------
Several invariants documented in ``.github/copilot-instructions.md`` (R24, R29,
R30, R31, and many of the per-rule "plugin-package copy MUST stay SHA-equal"
notes) rely on the plugin payload trees under
``builder/plugin package/packages/<plugin>/payload/python/<top>/...`` being
byte-identical to the canonical sources at ``<repo>/<top>/...``.

When a developer modifies a canonical file but forgets to mirror the change
into the plugin payload (or vice-versa), the installed/frozen build can ship
with a stale module — a recurring class of production-only bug. This script
detects that drift before commit.

Behavior
--------
* For every ``.py`` file under
  ``builder/plugin package/packages/<plugin>/payload/python/<top>/<rest>``,
  the canonical path is computed as ``<repo>/<top>/<rest>``.
* If the canonical file exists, SHA256 hashes are compared. A mismatch is a
  hard failure (exit code 1).
* If the canonical file does not exist, the entry is reported as
  ``PLUGIN_ONLY`` (informational). Per R24 some plugins legitimately
  introduce brand-new sub-modules not present in the engine; these are
  acceptable but logged for visibility.

This script is **read-only**: it never modifies any file.

Usage
-----
    python tools/dev/verify_plugin_mirrors.py            # exit 1 on drift
    python tools/dev/verify_plugin_mirrors.py --verbose  # list every pair

Programmatic API
----------------
``verify_plugin_mirrors(repo_root=None)`` returns a
``PluginMirrorReport`` dataclass. Used by
``tests/build/test_plugin_mirror_parity.py``.
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

_REPO_ROOT = Path(__file__).resolve().parents[2]
_PLUGIN_ROOT = _REPO_ROOT / "builder" / "plugin package" / "packages"


@dataclass
class MirrorPair:
    plugin: str
    canonical: Path
    payload: Path
    canonical_exists: bool
    canonical_hash: str = ""
    payload_hash: str = ""

    @property
    def matches(self) -> bool:
        return self.canonical_exists and self.canonical_hash == self.payload_hash


@dataclass
class PluginMirrorReport:
    pairs_checked: int = 0
    mismatches: list[MirrorPair] = field(default_factory=list)
    plugin_only: list[MirrorPair] = field(default_factory=list)
    matches: list[MirrorPair] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.mismatches


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _iter_payload_py_files(plugin_dir: Path) -> Iterable[Path]:
    payload_python = plugin_dir / "payload" / "python"
    if not payload_python.is_dir():
        return []
    return payload_python.rglob("*.py")


def _canonical_for(payload_file: Path, plugin_dir: Path, repo_root: Path) -> Path:
    payload_python = plugin_dir / "payload" / "python"
    rel = payload_file.relative_to(payload_python)
    return repo_root / rel


def verify_plugin_mirrors(repo_root: Path | None = None) -> PluginMirrorReport:
    repo = (repo_root or _REPO_ROOT).resolve()
    plugin_root = repo / "builder" / "plugin package" / "packages"
    report = PluginMirrorReport()
    if not plugin_root.is_dir():
        return report

    for plugin_dir in sorted(p for p in plugin_root.iterdir() if p.is_dir()):
        for payload_file in sorted(_iter_payload_py_files(plugin_dir)):
            canonical = _canonical_for(payload_file, plugin_dir, repo)
            pair = MirrorPair(
                plugin=plugin_dir.name,
                canonical=canonical,
                payload=payload_file,
                canonical_exists=canonical.is_file(),
            )
            pair.payload_hash = _sha256(payload_file)
            if pair.canonical_exists:
                pair.canonical_hash = _sha256(canonical)
                if pair.matches:
                    report.matches.append(pair)
                else:
                    report.mismatches.append(pair)
            else:
                report.plugin_only.append(pair)
            report.pairs_checked += 1

    return report


def _format_relative(path: Path, repo: Path) -> str:
    try:
        return str(path.relative_to(repo)).replace("\\", "/")
    except ValueError:
        return str(path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verbose", "-v", action="store_true", help="List every checked pair, not just mismatches.")
    parser.add_argument("--show-plugin-only", action="store_true", help="List plugin-only modules (R24 additive).")
    args = parser.parse_args(argv)

    report = verify_plugin_mirrors()
    repo = _REPO_ROOT.resolve()

    if args.verbose:
        for pair in report.matches:
            print(f"[OK]        {pair.plugin}  {_format_relative(pair.payload, repo)}")

    if args.show_plugin_only or args.verbose:
        for pair in report.plugin_only:
            print(f"[PLUGIN_ONLY] {pair.plugin}  {_format_relative(pair.payload, repo)}")

    if report.mismatches:
        print("", file=sys.stderr)
        print("[DRIFT] Plugin payload differs from canonical source:", file=sys.stderr)
        for pair in report.mismatches:
            print(
                f"  plugin={pair.plugin}\n"
                f"    canonical = {_format_relative(pair.canonical, repo)}  (sha256={pair.canonical_hash[:16]}...)\n"
                f"    payload   = {_format_relative(pair.payload, repo)}  (sha256={pair.payload_hash[:16]}...)",
                file=sys.stderr,
            )
        print("", file=sys.stderr)
        print(
            f"[DRIFT] {len(report.mismatches)} mismatched file(s) out of {report.pairs_checked} checked.",
            file=sys.stderr,
        )
        return 1

    print(
        f"[OK] {len(report.matches)} pair(s) match. "
        f"{len(report.plugin_only)} plugin-only file(s). "
        f"Total checked: {report.pairs_checked}."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
