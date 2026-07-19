"""Generate the incremental-update (delta) artifacts for an AIPacs release.

Produces, under ``builder/output/updates/`` (or ``--updates-root``):

- ``core/manifest-<version>.json``  — file-level manifest of the staged core
  bundle (``stage/core`` maps 1:1 to the installed ``{app}`` tree),
- ``files/<h2>/<sha256>.gz``        — content-addressed blob store (only NEW
  hashes are added; unchanged DLLs are never re-published),
- ``core/notes-<version>.md``       — release notes copy (when available),

and returns/prints the extra keys to merge into the ``update_feed.json`` core
entry (``delta{...}``, ``release_notes``, ``release_notes_path``).

Called automatically from ``builder/build_release.py::publish_update_bundle``
(guarded — a delta failure never fails the release build) and usable
standalone:

    python "tools/build/generate_update_manifest.py" --version 3.5.4

Design: docs/plans/architecture/AUTO_UPDATE_SYSTEM_2026-07-16.md (OPT-38).
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from modules.auto_update import manifest as manifest_mod  # noqa: E402

APP_NAME = "AIPacs"
VERSION_MARKER_NAME = "version.json"


def _default_version() -> str:
    pyproject = _PROJECT_ROOT / "pyproject.toml"
    try:
        import tomllib

        payload = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        return str((payload.get("project") or {}).get("version") or "").strip()
    except Exception:
        return ""


def stamp_stage_version(stage_core_dir: str | Path, version: str) -> Path | None:
    """Write ``engine/version.json`` into the staged core tree.

    This marker ships in BOTH the installer and the delta payload, so after a
    delta apply the client can reconcile its version identity
    (``modules.auto_update.apply.reconcile_version_on_boot``).
    """
    stage = Path(stage_core_dir)
    engine = stage / "engine"
    if not engine.is_dir():
        return None
    marker = engine / VERSION_MARKER_NAME
    marker.write_text(
        json.dumps(
            {
                "app_name": APP_NAME,
                "version": str(version),
                "built_at_utc": datetime.now(timezone.utc).isoformat(),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return marker


def _short_notes(notes_text: str, limit: int = 700) -> str:
    """First meaningful paragraph(s) of a markdown release-notes file."""
    lines: list[str] = []
    for raw in notes_text.splitlines():
        line = raw.strip()
        if line.startswith("#"):
            continue
        lines.append(raw.rstrip())
        if len("\n".join(lines)) >= limit:
            break
    text = "\n".join(lines).strip()
    return text[:limit].rstrip()


def generate_core_delta(
    stage_core_dir: str | Path,
    version: str,
    updates_root: str | Path,
    *,
    notes_source: str | Path | None = None,
    app_name: str = APP_NAME,
    quiet: bool = False,
) -> dict[str, object] | None:
    """Build manifest + populate the store. Returns feed core-entry extras.

    Returns ``None`` (with a warning) when the staged tree does not have the
    modern ``engine/`` layout — delta updates require it.
    """
    stage = Path(stage_core_dir)
    if not (stage / "engine").is_dir():
        if not quiet:
            print("[WARN] stage/core has no engine/ dir - delta manifest skipped")
        return None

    updates = Path(updates_root)
    core_dir = updates / "core"
    store_root = updates / manifest_mod.STORE_DIRNAME
    core_dir.mkdir(parents=True, exist_ok=True)

    # Guarantee the version marker exists in the payload before hashing.
    stamp_stage_version(stage, version)

    if not quiet:
        print(f"[..] Hashing staged core tree for manifest-{version}.json ...")
    manifest = manifest_mod.build_manifest(stage, version, app_name=app_name)

    if not quiet:
        print(f"[..] Populating content-addressed store ({manifest['file_count']} files) ...")
    stats = manifest_mod.populate_store(stage, manifest, store_root)

    manifest_name = f"manifest-{version}.json"
    manifest_sha = manifest_mod.dump_manifest(manifest, core_dir / manifest_name)

    extras: dict[str, object] = {
        "delta": {
            "manifest_path": f"core/{manifest_name}",
            "manifest_sha256": manifest_sha,
            "files_base": "files/",
            "compression": manifest_mod.DEFAULT_COMPRESSION,
        },
    }

    if notes_source is not None:
        notes_path = Path(notes_source)
        if notes_path.is_file():
            notes_text = notes_path.read_text(encoding="utf-8", errors="replace")
            notes_name = f"notes-{version}.md"
            (core_dir / notes_name).write_text(notes_text, encoding="utf-8")
            extras["release_notes_path"] = f"core/{notes_name}"
            extras["release_notes"] = _short_notes(notes_text)

    if not quiet:
        print(
            f"[OK] Delta published: {manifest['file_count']} files, "
            f"{stats['added']} new blobs / {stats['reused']} reused, "
            f"store bytes for this release: {stats['stored_bytes']:,}"
        )
    return extras


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--stage-dir",
        default=str(_PROJECT_ROOT / "builder" / "output" / "stage" / "core"),
        help="Staged core tree (== installed {app} layout).",
    )
    parser.add_argument("--version", default=_default_version(), help="Release version.")
    parser.add_argument(
        "--updates-root",
        default=str(_PROJECT_ROOT / "builder" / "output" / "updates"),
        help="Output root (core/ + files/ are created inside).",
    )
    parser.add_argument("--notes", default="", help="Release-notes markdown file.")
    args = parser.parse_args(argv)

    if not args.version:
        print("[ERROR] --version is required (pyproject.toml not readable).")
        return 2
    notes: Path | None = None
    if args.notes:
        notes = Path(args.notes)
    else:
        candidate = _PROJECT_ROOT / "docs" / "releases" / f"VERSION_{args.version}_RELEASE.md"
        if candidate.is_file():
            notes = candidate

    extras = generate_core_delta(
        args.stage_dir, args.version, args.updates_root, notes_source=notes
    )
    if extras is None:
        return 1
    print(json.dumps(extras, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
