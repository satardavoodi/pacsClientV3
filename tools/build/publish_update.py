"""Publish the built update bundle into one or more website roots (mirrors).

Takes ``builder/output/updates/`` (produced by ``build_release.py``) and syncs
it into ``<site-root>/updates/<app>/<channel>/`` for each ``--site-root``.
The content-addressed ``files/`` store is MERGED (only new blobs are copied),
so publishing release N+1 adds only the changed files — exactly what then gets
uploaded to the website(s).

Typical two-mirror workflow (user decision 2026-07-16):

    python "tools/build/publish_update.py" ^
        --site-root "E:\\websites\\site-A" --site-root "E:\\websites\\site-B"

then upload each site root to its host (FTP / hosting panel / rsync). Any
static host works — no server code is required. See
``website_update_service/README.md``.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2]

FEED_NAME = "update_feed.json"


def _iter_files(root: Path):
    if root.is_dir():
        for path in sorted(root.rglob("*")):
            if path.is_file():
                yield path


def _copy(src: Path, dst: Path, *, dry_run: bool) -> int:
    if not dry_run:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
    return src.stat().st_size


def sync_updates_to_site(
    updates_root: Path,
    site_root: Path,
    *,
    app: str = "aipacs",
    channel: str = "stable",
    include_installer: bool = True,
    include_modules: bool = True,
    dry_run: bool = False,
) -> dict[str, int]:
    """Sync one site root. Returns counters."""
    target = site_root / "updates" / app / channel
    copied = skipped = 0
    copied_bytes = 0

    feed = updates_root / FEED_NAME
    if not feed.is_file():
        raise FileNotFoundError(
            f"{feed} not found — run build_release.py (publish step) first."
        )
    copied_bytes += _copy(feed, target / FEED_NAME, dry_run=dry_run)
    copied += 1
    print(f"  feed  -> {target / FEED_NAME}")

    core_src = updates_root / "core"
    for path in _iter_files(core_src):
        name = path.name
        is_installer = name.lower().endswith(".exe")
        if is_installer and not include_installer:
            skipped += 1
            continue
        rel = path.relative_to(core_src)
        dst = target / "core" / rel
        # manifests/notes/checksums always refresh; installers copy if absent
        # or size differs (they are versioned file names anyway).
        if is_installer and dst.is_file() and dst.stat().st_size == path.stat().st_size:
            skipped += 1
            continue
        copied_bytes += _copy(path, dst, dry_run=dry_run)
        copied += 1

    store_src = updates_root / "files"
    new_blobs = 0
    for path in _iter_files(store_src):
        rel = path.relative_to(store_src)
        dst = target / "files" / rel
        if dst.is_file() and dst.stat().st_size == path.stat().st_size:
            skipped += 1
            continue
        copied_bytes += _copy(path, dst, dry_run=dry_run)
        copied += 1
        new_blobs += 1
    print(f"  store -> {new_blobs} new blob(s) merged")

    if include_modules:
        modules_src = updates_root / "modules"
        for path in _iter_files(modules_src):
            rel = path.relative_to(modules_src)
            dst = target / "modules" / rel
            if dst.is_file() and dst.stat().st_size == path.stat().st_size:
                skipped += 1
                continue
            copied_bytes += _copy(path, dst, dry_run=dry_run)
            copied += 1

    return {"copied": copied, "skipped": skipped, "bytes": copied_bytes}


def _load_remote_publish_module():
    import importlib.util

    tool_path = Path(__file__).with_name("remote_publish.py")
    spec = importlib.util.spec_from_file_location("aipacs_remote_publish", tool_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def publish_to_targets(
    updates_root: Path,
    *,
    targets_config: Path,
    target_ids: list[str] | None,
    all_targets: bool,
    with_installer: bool | None,
    include_modules: bool,
    dry_run: bool,
) -> bool:
    """Incremental publish to configured remote targets (folder/ftp)."""
    rp = _load_remote_publish_module()
    config = rp.load_publish_targets(targets_config)
    wanted = set(target_ids or [])
    selected = [
        t
        for t in config["targets"]
        if (all_targets and t.get("enabled")) or str(t.get("id")) in wanted
    ]
    if not selected:
        print(
            f"[ERROR] no matching targets in {targets_config} "
            f"(requested: {sorted(wanted) or 'all enabled'})."
        )
        return False
    ok = True
    for target in selected:
        try:
            rp.publish_release_to_target(
                updates_root,
                target,
                app=str(config.get("app") or "aipacs"),
                channel=str(config.get("channel") or "stable"),
                with_installer=with_installer,
                include_modules=include_modules,
                dry_run=dry_run,
            )
        except Exception as exc:  # noqa: BLE001 — per-target isolation
            print(f"[ERROR] {target.get('id')}: {exc}")
            ok = False
    return ok


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--updates-root",
        default=str(_PROJECT_ROOT / "builder" / "output" / "updates"),
    )
    parser.add_argument(
        "--site-root",
        action="append",
        default=None,
        help="Website root folder (repeat for mirrors). Legacy full-copy mode.",
    )
    parser.add_argument(
        "--target",
        action="append",
        default=None,
        help="Publish incrementally to a configured target id (repeatable).",
    )
    parser.add_argument(
        "--all-targets",
        action="store_true",
        help="Publish incrementally to every enabled target in the config.",
    )
    parser.add_argument(
        "--targets-config",
        default=str(_PROJECT_ROOT / "builder" / "publish_targets.json"),
        help="Credentials/config file (gitignored; see publish_targets.template.json).",
    )
    parser.add_argument("--app", default="aipacs")
    parser.add_argument("--channel", default="stable")
    parser.add_argument("--skip-installer", action="store_true")
    parser.add_argument(
        "--with-installer",
        action="store_true",
        help="Force-upload the full installer to remote targets (overrides target config).",
    )
    parser.add_argument("--skip-modules", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    updates_root = Path(args.updates_root)

    if args.target or args.all_targets:
        ok = publish_to_targets(
            updates_root,
            targets_config=Path(args.targets_config),
            target_ids=args.target,
            all_targets=args.all_targets,
            with_installer=(
                True if args.with_installer else (False if args.skip_installer else None)
            ),
            include_modules=not args.skip_modules,
            dry_run=args.dry_run,
        )
        return 0 if ok else 1

    if not args.site_root:
        parser.error("provide --site-root, --target, or --all-targets")

    overall_ok = True
    for site in args.site_root:
        site_root = Path(site)
        label = "(dry-run) " if args.dry_run else ""
        print(f"[..] {label}Publishing to {site_root} ...")
        try:
            stats = sync_updates_to_site(
                updates_root,
                site_root,
                app=args.app,
                channel=args.channel,
                include_installer=not args.skip_installer,
                include_modules=not args.skip_modules,
                dry_run=args.dry_run,
            )
        except Exception as exc:  # noqa: BLE001
            print(f"[ERROR] {site_root}: {exc}")
            overall_ok = False
            continue
        print(
            f"[OK] {site_root}: {stats['copied']} copied, {stats['skipped']} skipped, "
            f"{stats['bytes'] / (1024 * 1024):.1f} MB"
        )
    return 0 if overall_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
