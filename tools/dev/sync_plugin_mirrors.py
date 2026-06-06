"""Sync canonical sources INTO plugin-package payload mirrors.

Companion to ``tools/dev/verify_plugin_mirrors.py`` (which only checks).
For every ``.py`` under ``builder/plugin package/packages/<plugin>/payload/
python/<top>/<rest>`` whose canonical file ``<repo>/<top>/<rest>`` exists and
differs, the canonical content is copied over the payload copy.

``--add <repo-relative-path>`` additionally mirrors NEW canonical files (or
directories, recursively, ``.py`` only) into every plugin payload that
already contains the parent package directory.

Usage:
    python tools/dev/sync_plugin_mirrors.py                  # fix drifted files
    python tools/dev/sync_plugin_mirrors.py --dry-run
    python tools/dev/sync_plugin_mirrors.py --add modules/cd_burner/portable_viewer
"""

from __future__ import annotations

import argparse
import hashlib
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PLUGIN_ROOT = REPO_ROOT / "builder" / "plugin package" / "packages"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _payload_python_roots():
    for plugin_dir in sorted(PLUGIN_ROOT.iterdir()):
        python_root = plugin_dir / "payload" / "python"
        if python_root.is_dir():
            yield plugin_dir.name, python_root


def sync_drift(dry_run: bool) -> int:
    changed = 0
    for plugin, python_root in _payload_python_roots():
        for payload_file in python_root.rglob("*.py"):
            rel = payload_file.relative_to(python_root)
            canonical = REPO_ROOT / rel
            if not canonical.is_file():
                continue  # PLUGIN_ONLY file — legitimate
            if _sha(canonical) != _sha(payload_file):
                print(f"[sync] {plugin}: {rel}")
                if not dry_run:
                    shutil.copy2(canonical, payload_file)
                changed += 1
    return changed


def add_paths(paths: list[str], dry_run: bool) -> int:
    added = 0
    for raw in paths:
        rel = Path(raw.replace("\\", "/"))
        canonical = REPO_ROOT / rel
        if not canonical.exists():
            print(f"[add] SKIP (missing): {rel}")
            continue
        files = (
            [p for p in canonical.rglob("*.py")] if canonical.is_dir() else [canonical]
        )
        for plugin, python_root in _payload_python_roots():
            # Only add into plugins that already mirror the parent package.
            parent_in_payload = python_root / rel.parent
            if not parent_in_payload.is_dir():
                continue
            for src in files:
                dest = python_root / src.relative_to(REPO_ROOT)
                if dest.exists() and _sha(src) == _sha(dest):
                    continue
                print(f"[add]  {plugin}: {src.relative_to(REPO_ROOT)}")
                if not dry_run:
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src, dest)
                added += 1
    return added


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--add", nargs="*", default=[], metavar="REL_PATH")
    args = parser.parse_args()

    changed = sync_drift(args.dry_run)
    added = add_paths(args.add, args.dry_run) if args.add else 0

    print(f"Done: {changed} drifted file(s) synced, {added} new file(s) added"
          f"{' (dry-run)' if args.dry_run else ''}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
