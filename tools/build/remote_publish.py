"""Incremental remote publishing for the AI-PACS update service (OPT-38).

Uploads a built release (``builder/output/updates/``) to one or more website
targets — transferring ONLY what the server does not already have:

- The content-addressed store (``files/<hh>/<sha256>.gz``) is immutable, so
  the publisher first builds a REMOTE INDEX (one listing per 2-hex subdir,
  256 max) and uploads only the blobs of the CURRENT release manifest that
  are missing or size-mismatched on the server.  Unchanged DLL blobs are
  never re-uploaded — a typical release pushes a few dozen MB, not 2 GB.
- The remote listing is the source of truth (self-healing: delete a blob on
  the server and the next publish restores it).  A small state file per
  target records what was published, for reporting only.
- Upload order is safety-ordered: blobs → core manifest/notes/(installer) →
  modules → ``update_feed.json`` **LAST** (the feed going live is the release
  moment), then the feed is downloaded back and byte-verified.

Targets come from ``builder/publish_targets.json`` (GITIGNORED — credentials
stay on the build machine; commit only ``publish_targets.template.json``).
Transports: ``folder`` (local site / mirror staging) and ``ftp`` (FTPS by
default, stdlib ftplib).  An HTTPS publish API on the Laravel side is a
staged follow-up and would slot in as a third transport.

Used by ``tools/build/publish_update.py`` (CLI ``--target``/``--all-targets``)
and auto-invoked from ``builder/build_release.py`` for targets with
``"auto": true`` (kill switch ``AIPACS_UPDATE_REMOTE_PUBLISH=0``).
"""

from __future__ import annotations

import ftplib
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

FEED_NAME = "update_feed.json"
_UPLOAD_RETRIES = 3
_INDEX_SUBDIR = "files"

Log = Callable[[str], None]


# ── configuration ──────────────────────────────────────────────────────────

def load_publish_targets(config_path: str | Path) -> dict[str, Any]:
    path = Path(config_path)
    if not path.is_file():
        return {"app": "aipacs", "channel": "stable", "targets": []}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("publish_targets.json must be a JSON object")
    payload.setdefault("app", "aipacs")
    payload.setdefault("channel", "stable")
    targets = [t for t in (payload.get("targets") or []) if isinstance(t, dict)]
    payload["targets"] = targets
    return payload


def describe_target(target: dict[str, Any]) -> str:
    """Loggable description — NEVER includes the password."""
    kind = str(target.get("type") or "?")
    if kind == "folder":
        return f"{target.get('id')} (folder: {target.get('site_root')})"
    return (
        f"{target.get('id')} (ftp{'s' if target.get('tls', True) else ''}: "
        f"{target.get('username')}@{target.get('host')}:{target.get('port', 21)}"
        f"/{target.get('remote_root', '')})"
    )


# ── transports ─────────────────────────────────────────────────────────────

class FolderTransport:
    """Local/UNC folder target (also the test double for the FTP flow)."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    def list_dir(self, relpath: str) -> dict[str, int]:
        target = self.root / relpath
        if not target.is_dir():
            return {}
        return {p.name: p.stat().st_size for p in target.iterdir() if p.is_file()}

    def exists(self, relpath: str) -> int | None:
        target = self.root / relpath
        return target.stat().st_size if target.is_file() else None

    def upload(self, local: Path, relpath: str) -> None:
        target = self.root / relpath
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(target.suffix + ".uploading")
        import shutil

        shutil.copyfile(local, tmp)
        import os

        os.replace(tmp, target)

    def download_bytes(self, relpath: str) -> bytes:
        return (self.root / relpath).read_bytes()

    def close(self) -> None:  # pragma: no cover - nothing to release
        pass


class FtpTransport:
    """FTP/FTPS target (stdlib ftplib; TLS by default, passive, binary)."""

    def __init__(
        self,
        host: str,
        username: str,
        password: str,
        *,
        port: int = 21,
        tls: bool = True,
        remote_root: str = "",
        timeout: int = 30,
        log: Log = print,
    ) -> None:
        self._host = host
        self._port = int(port or 21)
        self._tls = bool(tls)
        self._user = username
        self._password = password
        self._root = str(remote_root or "").strip("/").replace("\\", "/")
        self._timeout = timeout
        self._log = log
        self._ftp: ftplib.FTP | None = None
        self._made_dirs: set[str] = set()

    # -- connection -----------------------------------------------------
    def _connect(self) -> ftplib.FTP:
        if self._ftp is not None:
            return self._ftp
        if self._tls:
            ftp: ftplib.FTP = ftplib.FTP_TLS(timeout=self._timeout)
        else:
            ftp = ftplib.FTP(timeout=self._timeout)
        ftp.connect(self._host, self._port)
        ftp.login(self._user, self._password)
        if isinstance(ftp, ftplib.FTP_TLS):
            ftp.prot_p()  # encrypt the data channel too
        ftp.set_pasv(True)
        self._ftp = ftp
        return ftp

    def _reset(self) -> None:
        try:
            if self._ftp is not None:
                self._ftp.quit()
        except Exception:
            pass
        self._ftp = None
        self._made_dirs.clear()

    def close(self) -> None:
        self._reset()

    def _full(self, relpath: str) -> str:
        rel = relpath.strip("/").replace("\\", "/")
        return f"{self._root}/{rel}" if self._root else rel

    def _ensure_dirs(self, remote_file: str) -> None:
        ftp = self._connect()
        parts = remote_file.split("/")[:-1]
        path = ""
        for part in parts:
            path = f"{path}/{part}" if path else part
            if path in self._made_dirs:
                continue
            try:
                ftp.mkd(path)
            except ftplib.error_perm:
                pass  # already exists
            self._made_dirs.add(path)

    # -- queries --------------------------------------------------------
    def list_dir(self, relpath: str) -> dict[str, int]:
        ftp = self._connect()
        full = self._full(relpath)
        result: dict[str, int] = {}
        try:
            for name, facts in ftp.mlsd(full, facts=["type", "size"]):
                if facts.get("type") == "file":
                    result[name] = int(facts.get("size") or 0)
            return result
        except ftplib.error_perm:
            return {}  # directory does not exist yet
        except Exception:
            # MLSD unsupported → NLST + SIZE fallback
            try:
                names = ftp.nlst(full)
            except ftplib.error_perm:
                return {}
            ftp.voidcmd("TYPE I")
            for entry in names:
                name = entry.rsplit("/", 1)[-1]
                try:
                    size = ftp.size(f"{full}/{name}")
                except Exception:
                    continue
                if size is not None:
                    result[name] = int(size)
            return result

    def exists(self, relpath: str) -> int | None:
        ftp = self._connect()
        try:
            ftp.voidcmd("TYPE I")
            size = ftp.size(self._full(relpath))
            return int(size) if size is not None else None
        except Exception:
            return None

    # -- writes ---------------------------------------------------------
    def upload(self, local: Path, relpath: str) -> None:
        full = self._full(relpath)
        last: Exception | None = None
        for attempt in range(1, _UPLOAD_RETRIES + 1):
            try:
                ftp = self._connect()
                self._ensure_dirs(full)
                tmp = full + ".uploading"
                with open(local, "rb") as handle:
                    ftp.storbinary(f"STOR {tmp}", handle, blocksize=256 * 1024)
                try:
                    ftp.delete(full)
                except ftplib.error_perm:
                    pass  # target did not exist
                ftp.rename(tmp, full)
                return
            except Exception as exc:  # noqa: BLE001 — retried, then surfaced
                last = exc
                self._log(f"    retry {attempt}/{_UPLOAD_RETRIES} for {relpath}: {exc}")
                self._reset()
                time.sleep(min(2.0 * attempt, 6.0))
        raise RuntimeError(f"FTP upload failed for {relpath}: {last}") from last

    def download_bytes(self, relpath: str) -> bytes:
        ftp = self._connect()
        chunks: list[bytes] = []
        ftp.retrbinary(f"RETR {self._full(relpath)}", chunks.append)
        return b"".join(chunks)


def make_transport(target: dict[str, Any], *, log: Log = print):
    kind = str(target.get("type") or "").strip().lower()
    if kind == "folder":
        root = str(target.get("site_root") or "").strip()
        if not root:
            raise ValueError(f"target {target.get('id')}: site_root is required")
        return FolderTransport(root)
    if kind == "ftp":
        host = str(target.get("host") or "").strip()
        user = str(target.get("username") or "")
        password = str(target.get("password") or "")
        if not host or not user:
            raise ValueError(f"target {target.get('id')}: host/username are required")
        return FtpTransport(
            host,
            user,
            password,
            port=int(target.get("port") or 21),
            tls=bool(target.get("tls", True)),
            remote_root=str(target.get("remote_root") or ""),
            log=log,
        )
    raise ValueError(f"target {target.get('id')}: unknown type {kind!r}")


# ── release plan (what THIS release needs on the server) ───────────────────

def load_release_plan(updates_root: str | Path) -> dict[str, Any]:
    """Read the built feed + manifest and derive every required remote file."""
    root = Path(updates_root)
    feed_path = root / FEED_NAME
    if not feed_path.is_file():
        raise FileNotFoundError(f"{feed_path} not found — run the release build first.")
    feed = json.loads(feed_path.read_text(encoding="utf-8"))
    core = dict(feed.get("core") or {})
    version = str(core.get("release_version") or "")
    delta = core.get("delta") if isinstance(core.get("delta"), dict) else None

    blobs: list[tuple[str, int]] = []  # (store-relative path, stored size)
    manifest_rel = ""
    if delta:
        manifest_rel = str(delta.get("manifest_path") or "")
        manifest_file = root / manifest_rel
        manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
        seen: set[str] = set()
        for entry in manifest.get("files") or []:
            sha = str(entry.get("sha256") or "").lower()
            if not sha or sha in seen:
                continue
            seen.add(sha)
            blobs.append(
                (
                    f"files/{sha[:2]}/{sha}.gz",
                    int(entry.get("stored_size") or 0),
                )
            )

    return {
        "version": version,
        "feed_path": feed_path,
        "core": core,
        "manifest_rel": manifest_rel,
        "notes_rel": str(core.get("release_notes_path") or ""),
        "installer_rel": str(core.get("artifact_path") or ""),
        "blobs": blobs,
    }


# ── publishing ─────────────────────────────────────────────────────────────

def _state_dir(updates_root: Path) -> Path:
    return updates_root / ".publish_state"


def publish_release_to_target(
    updates_root: str | Path,
    target: dict[str, Any],
    *,
    app: str = "aipacs",
    channel: str = "stable",
    with_installer: bool | None = None,
    include_modules: bool = True,
    dry_run: bool = False,
    log: Log = print,
) -> dict[str, Any]:
    """Incrementally publish the built release to one remote target.

    Returns stats: uploaded/skipped counts + bytes. Raises on failure BEFORE
    the feed is replaced (a failed run never half-publishes a release —
    clients keep seeing the previous feed).
    """
    root = Path(updates_root)
    plan = load_release_plan(root)
    base = f"updates/{app}/{channel}"
    transport = make_transport(target, log=log)
    if with_installer is None:
        with_installer = bool(target.get("with_installer", False))

    uploaded = skipped = 0
    uploaded_bytes = 0
    try:
        log(f"[..] Remote publish v{plan['version']} -> {describe_target(target)}")

        # 1) Remote blob index: one listing per populated 2-hex subdir.
        needed_subdirs = sorted({rel.split("/")[1] for rel, _ in plan["blobs"]})
        remote_index: dict[str, int] = {}
        for sub in needed_subdirs:
            for name, size in transport.list_dir(f"{base}/files/{sub}").items():
                remote_index[f"files/{sub}/{name}"] = size

        # 2) Upload only missing / size-mismatched blobs.
        to_upload = [
            (rel, size)
            for rel, size in plan["blobs"]
            if remote_index.get(rel) != size or size == 0
        ]
        total_bytes = sum(size for _, size in to_upload)
        log(
            f"    store: {len(plan['blobs'])} blobs referenced, "
            f"{len(plan['blobs']) - len(to_upload)} already on server, "
            f"{len(to_upload)} to upload ({total_bytes / 1e6:.1f} MB)"
        )
        if dry_run:
            log("    (dry-run — nothing uploaded)")
            return {
                "target": str(target.get("id")),
                "version": plan["version"],
                "uploaded": 0,
                "skipped": len(plan["blobs"]) - len(to_upload),
                "would_upload": len(to_upload),
                "would_upload_bytes": total_bytes,
            }
        for index, (rel, size) in enumerate(to_upload, start=1):
            transport.upload(root / rel, f"{base}/{rel}")
            uploaded += 1
            uploaded_bytes += size
            if index % 25 == 0 or index == len(to_upload):
                log(
                    f"    blobs {index}/{len(to_upload)} "
                    f"({uploaded_bytes / 1e6:.1f}/{total_bytes / 1e6:.1f} MB)"
                )
        skipped += len(plan["blobs"]) - len(to_upload)

        # 3) Core artifacts (manifest + notes always; installer only if asked).
        for rel in (plan["manifest_rel"], plan["notes_rel"]):
            if rel and (root / rel).is_file():
                transport.upload(root / rel, f"{base}/{rel}")
                uploaded += 1
                uploaded_bytes += (root / rel).stat().st_size
        installer_rel = plan["installer_rel"]
        if installer_rel and (root / installer_rel).is_file():
            local_size = (root / installer_rel).stat().st_size
            remote_size = transport.exists(f"{base}/{installer_rel}")
            if remote_size == local_size:
                skipped += 1
            elif with_installer:
                log(f"    installer: uploading {installer_rel} ({local_size / 1e6:.0f} MB)")
                transport.upload(root / installer_rel, f"{base}/{installer_rel}")
                uploaded += 1
                uploaded_bytes += local_size
            else:
                log(
                    "    [WARN] installer NOT on server and not uploaded "
                    "(with_installer=false) — the full-installer fallback will 404 "
                    "until you publish it (--with-installer)."
                )

        # 4) Module packages (size-diff skip).
        if include_modules and (root / "modules").is_dir():
            for path in sorted((root / "modules").rglob("*")):
                if not path.is_file():
                    continue
                rel = f"modules/{path.relative_to(root / 'modules').as_posix()}"
                if transport.exists(f"{base}/{rel}") == path.stat().st_size:
                    skipped += 1
                    continue
                transport.upload(path, f"{base}/{rel}")
                uploaded += 1
                uploaded_bytes += path.stat().st_size

        # 5) FEED LAST — the release goes live here.
        transport.upload(plan["feed_path"], f"{base}/{FEED_NAME}")
        uploaded += 1

        # 6) Verify: read the feed back byte-for-byte.
        local_feed = plan["feed_path"].read_bytes()
        remote_feed = transport.download_bytes(f"{base}/{FEED_NAME}")
        if remote_feed != local_feed:
            raise RuntimeError(
                "feed verification FAILED — served bytes differ from the local feed"
            )

        state_dir = _state_dir(root)
        state_dir.mkdir(parents=True, exist_ok=True)
        (state_dir / f"{target.get('id')}.json").write_text(
            json.dumps(
                {
                    "target": describe_target(target),
                    "version": plan["version"],
                    "published_at_utc": datetime.now(timezone.utc).isoformat(),
                    "uploaded": uploaded,
                    "skipped": skipped,
                    "uploaded_bytes": uploaded_bytes,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        log(
            f"[OK] {target.get('id')}: v{plan['version']} live — "
            f"{uploaded} uploaded ({uploaded_bytes / 1e6:.1f} MB), {skipped} reused"
        )
        return {
            "target": str(target.get("id")),
            "version": plan["version"],
            "uploaded": uploaded,
            "skipped": skipped,
            "uploaded_bytes": uploaded_bytes,
        }
    finally:
        transport.close()
