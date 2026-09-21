"""Low-cost local DICOM pixel-payload classification.

The patient image viewer must not treat SR, presentation-state, or other
metadata-only DICOM objects as one-slice image series.  These helpers inspect
only the pixel element headers and defer the pixel value itself, so callers can
classify local series without decoding or loading large cine payloads.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from collections import OrderedDict, deque
from hashlib import sha256
import json
import logging
import os
import tempfile
from threading import Lock, local
from time import monotonic, perf_counter, time

from pydicom.filereader import read_partial
from pydicom.tag import Tag


PIXEL_DATA_TAGS = (
    Tag(0x7FE0, 0x0010),  # Pixel Data
    Tag(0x7FE0, 0x0008),  # Float Pixel Data
    Tag(0x7FE0, 0x0009),  # Double Float Pixel Data
)

_logger = logging.getLogger(__name__)
# Worker-only Local inventory acceleration, not a download/completeness cache.
# Share immutable positive facts between Home and patient-tab projections. Check
# each file's identity/version on every use; never use a directory mtime alone.
_PIXEL_FACTS_CACHE_LIMIT = 4096
_PIXEL_FACTS_CACHE_TTL = 30.0
_pixel_facts_cache = OrderedDict()
_pixel_facts_cache_lock = Lock()
# Bounded single-flight locks: no per-patient lock objects accumulate. Unrelated
# paths may share a stripe, but no I/O runs under the global cache lock.
_pixel_facts_stripes = tuple(Lock() for _ in range(64))
# Optional derived hints in the central cache tree. Never create thumbnail
# presence, or write source media, the clinical DB or a viewer's decoded cache.
_PIXEL_FACTS_DISK_TTL = 24 * 60 * 60
_PIXEL_FACTS_DISK_MAX_BYTES = 1024 * 1024
_PIXEL_FACTS_DISK_MAX_FILES = 8192
_PIXEL_FACTS_DISK_MAX_ENTRIES = 256
_PIXEL_FACTS_DISK_BUDGET = 16 * 1024 * 1024
_pixel_facts_disk_write_lock = Lock()
# The catalog owner stays sequential so series identity and progressive card
# order cannot change. Only the files inside the current series borrow this
# owner-thread context for bounded worker I/O.
_ordered_inventory_context = local()


@dataclass(frozen=True)
class SeriesPixelInventory:
    """Displayability summary for one local series directory."""

    instance_count: int = 0
    pixel_instance_count: int = 0
    frame_count: int = 0
    # Excluded from value equality so the long-standing three-count contract
    # remains stable. Consumers use this only as a compare-and-persist token.
    directory_mtime_ns: int = field(default=0, compare=False)

    @property
    def has_pixel_data(self) -> bool:
        return self.pixel_instance_count > 0

    @property
    def display_image_count(self) -> int:
        """Number of viewport frames represented by the series."""
        return self.frame_count or self.pixel_instance_count


def try_dicom_file_pixel_facts(file_path: str | Path) -> tuple[bool, int] | None:
    """Return pixel facts, or ``None`` when the header was not readable.

    Producers use the tri-state result so a transient/read error can never be
    persisted as a verified non-pixel object.  Compatibility callers retain
    the historical ``(False, 0)`` fallback through ``dicom_file_pixel_facts``.
    """

    found_pixel_data = False

    def _stop_at_pixel_data(tag, _vr, _length) -> bool:
        nonlocal found_pixel_data
        if tag in PIXEL_DATA_TAGS:
            found_pixel_data = True
            return True
        return False

    try:
        with Path(file_path).open("rb") as stream:
            # Pixel detection happens in stop_when BEFORE specific_tags skips
            # values. Keep only NumberOfFrames, not unrelated private data or
            # defined-length sequences. Undefined-length sequences still follow
            # pydicom's parser; never invent a byte-level delimiter shortcut.
            dataset = read_partial(
                stream, stop_when=_stop_at_pixel_data, force=True,
                specific_tags=[Tag(0x0028, 0x0008)],
            )
    except Exception:
        return None
    if not found_pixel_data:
        return False, 0
    try:
        frames = max(1, int(getattr(dataset, "NumberOfFrames", 1) or 1))
    except (TypeError, ValueError):
        frames = 1
    return True, frames


def _dicom_file_pixel_facts(file_path: str | Path) -> tuple[bool, int]:
    """Compatibility form of :func:`try_dicom_file_pixel_facts`."""
    return try_dicom_file_pixel_facts(file_path) or (False, 0)


def dicom_file_pixel_facts(file_path: str | Path) -> tuple[bool, int]:
    """Return ``(has_pixel_data, frame_count)`` without reading pixel values.

    This is the shared public boundary for import, thumbnail, and viewer
    classification. Metadata-only DICOM objects remain preserved on disk but
    must not be projected as image frames.
    """
    return _dicom_file_pixel_facts(file_path)


def dicom_file_has_pixel_data(file_path: str | Path) -> bool:
    """Inspect pixel-element presence without reading the pixel value."""
    return dicom_file_pixel_facts(file_path)[0]


def indexed_series_pixel_inventory(series: dict, *, managed_root=None) -> SeriesPixelInventory | None:
    """Return producer-verified facts, or ``None`` when the index is not trustworthy.

    The fast path is deliberately strict: only an independently verified pixel
    inventory under the managed DICOM tree, with the current series-directory
    revision, may bypass per-file header inspection. Legacy/restored/external
    rows and any changed directory fall back to
    :func:`inspect_series_pixel_inventory`.

    Managed DICOM files are immutable after atomic import/download publication;
    all application add/remove/replace operations change the directory revision
    and must restamp this record.  The revision is not used for arbitrary media.
    """
    if not isinstance(series, dict):
        return None
    try:
        if (str(series.get("pixel_inventory_status") or "") != "Verified"
                or int(series.get("pixel_inventory_schema") or 0) != 1):
            return None
        instances = int(series.get("pixel_inventory_instance_count") or 0)
        pixel_count = int(series.get("pixel_instance_count") or 0)
        frame_count = int(series.get("display_frame_count") or 0)
        stamped_mtime = int(series.get("inventory_dir_mtime_ns") or 0)
        if (instances <= 0 or pixel_count < 0
                or pixel_count > instances or frame_count < 0
                or (pixel_count > 0 and frame_count < pixel_count)
                or stamped_mtime <= 0):
            return None

        series_path = Path(str(series.get("series_path") or "").strip()).resolve()
        if managed_root is None:
            from PacsClient.utils import data_paths
            managed_root = data_paths.DICOM_IMAGES_DIR
        root = Path(managed_root).resolve()
        relative = series_path.relative_to(root)
        # Canonical managed layout is <root>/<study_uid>/<folder_key>.
        if len(relative.parts) != 2 or not series_path.is_dir():
            return None
        if int(series_path.stat().st_mtime_ns) != stamped_mtime:
            return None
        return SeriesPixelInventory(instances, pixel_count, frame_count, stamped_mtime)
    except (ImportError, OSError, TypeError, ValueError):
        return None


def resolve_series_pixel_inventory(series: dict) -> tuple[SeriesPixelInventory, str]:
    """Resolve one Local series through the trusted index, then the legacy scan.

    Returns ``(inventory, source)`` where source is ``"index"`` or ``"scan"``.
    This pure presentation boundary performs no DB write and never turns an
    unverified summary into a Ready/completion verdict.
    """
    indexed = indexed_series_pixel_inventory(series)
    if indexed is not None:
        return indexed, "index"
    return inspect_series_pixel_inventory(series.get("series_path") or ""), "scan"


def _ordered_local_inventory_enabled() -> bool:
    """Keep a narrow rollback for the new Local catalog ownership model."""
    return (os.environ.get("AIPACS_LOCAL_ORDERED_INVENTORY", "1") or "1").strip() != "0"


def _ordered_inventory_worker_count(explicit=None) -> int:
    value = explicit
    if value is None:
        value = os.environ.get(
            "AIPACS_LOCAL_PIXEL_INVENTORY_WORKERS",
            os.environ.get("AIPACS_SERIES_FILE_WARM_WORKERS", "8"),
        )
    try:
        value = int(value)
    except (TypeError, ValueError):
        value = 8
    return max(1, min(value, 16))


def resolve_series_pixel_inventories(
    series_items, *, workers=None, cancelled=None,
):
    """Yield exact Local inventories in catalog order from one bounded owner.

    Producer-indexed rows remain O(1). Legacy rows retain the exact per-file
    inspection contract, but files within the *current* series may be inspected
    concurrently. Series themselves are never reordered or scanned ahead, so
    multi-study identity, alias allocation and progressive card order remain
    deterministic. This generator is worker-only and performs no GUI mutation.
    """
    rows = tuple(series_items or ())
    enabled = _ordered_local_inventory_enabled()
    worker_count = _ordered_inventory_worker_count(workers) if enabled else 1
    started = perf_counter()
    completed = indexed = scanned = 0
    was_cancelled = False
    previous = getattr(_ordered_inventory_context, "executor", None)
    previous_max_pending = getattr(_ordered_inventory_context, "max_pending", None)
    executor = None
    try:
        if worker_count > 1:
            from concurrent.futures import ThreadPoolExecutor
            executor = ThreadPoolExecutor(
                max_workers=worker_count,
                thread_name_prefix="LocalPixelInventory",
            )
            _ordered_inventory_context.executor = executor
            _ordered_inventory_context.max_pending = worker_count * 2
        for series in rows:
            if cancelled is not None and cancelled():
                was_cancelled = True
                break
            inventory, source = resolve_series_pixel_inventory(series)
            if cancelled is not None and cancelled():
                was_cancelled = True
                break
            completed += 1
            indexed += int(source == "index")
            scanned += int(source == "scan")
            yield series, inventory, source
    finally:
        if previous is None:
            try:
                del _ordered_inventory_context.executor
            except AttributeError:
                pass
        else:
            _ordered_inventory_context.executor = previous
        if previous_max_pending is None:
            try:
                del _ordered_inventory_context.max_pending
            except AttributeError:
                pass
        else:
            _ordered_inventory_context.max_pending = previous_max_pending
        if executor is not None:
            executor.shutdown(wait=True, cancel_futures=True)
        _logger.info(
            "[LOCAL_PIXEL_INVENTORY_BATCH] requested=%d completed=%d "
            "indexed=%d scanned=%d workers=%d cancelled=%s total_ms=%.2f",
            len(rows), completed, indexed, scanned, worker_count,
            was_cancelled, (perf_counter() - started) * 1000.0,
        )


def _pixel_file_version(path: Path) -> tuple:
    info = path.stat()
    return (info.st_dev, info.st_ino, info.st_size,
            info.st_mtime_ns, info.st_ctime_ns)


def _pixel_path_key(path: Path) -> str:
    return sha256(os.path.normcase(os.path.abspath(path)).encode(
        "utf-8", errors="surrogatepass",
    )).hexdigest()


def _pixel_inventory_cache_path(root: Path) -> Path | None:
    """Admit only managed study/series directories; external media stay read-only."""
    try:
        from PacsClient.utils.data_paths import DICOM_IMAGES_DIR, CACHE_DIR

        relative = root.resolve().relative_to(Path(DICOM_IMAGES_DIR).resolve())
        if len(relative.parts) != 2:
            return None
        cache = Path(CACHE_DIR).resolve()
        parent = (cache / "local_pixel_facts").resolve()
        if not parent.is_relative_to(cache):
            return None
        return parent / f"{_pixel_path_key(root)}.json"
    except (OSError, ValueError, RuntimeError, ImportError):
        return None


def _read_pixel_inventory_cache(path: Path | None, root: Path) -> dict:
    if path is None:
        return {}
    try:
        with path.open("rb") as stream:
            data = stream.read(_PIXEL_FACTS_DISK_MAX_BYTES + 1)
        if len(data) > _PIXEL_FACTS_DISK_MAX_BYTES:
            return {}
        payload = json.loads(data)
        if (not isinstance(payload, dict) or payload.get("schema") != 1
                or payload.get("root") != _pixel_path_key(root)):
            return {}
        records = payload.get("records")
        if not isinstance(records, dict) or len(records) > _PIXEL_FACTS_DISK_MAX_FILES:
            return {}
        encoded = json.dumps(records, separators=(",", ":"), sort_keys=True).encode("utf-8")
        if payload.get("digest") != sha256(encoded).hexdigest():
            return {}  # Detect accidental value corruption, not an authenticity claim.
        now = time()
        accepted = {}
        for key, record in records.items():
            if (not isinstance(key, str) or len(key) != 64
                    or not isinstance(record, list) or len(record) != 3):
                continue
            version, frames, checked = record
            if (not isinstance(version, list) or len(version) != 5
                    or not all(type(value) is int for value in version)
                    or type(frames) is not int or frames <= 0
                    or type(checked) not in (float, int)
                    or not 0 <= now - checked < _PIXEL_FACTS_DISK_TTL):
                continue
            accepted[key] = (tuple(version), frames, checked)
        return accepted
    except (OSError, ValueError, TypeError, RecursionError):
        # A missing/corrupt/read-only cache is not missing clinical data.
        return {}


def _reserve_pixel_cache_space(path: Path, size: int) -> bool:
    """Bound disposable metadata by count and bytes; caller owns write lock.

    Evict oldest-written entries only in this dedicated cache directory. No
    patient/media paths are read from the JSON or followed for cache eviction.
    Readers need no lock: a concurrently evicted entry is simply a miss.
    """
    if size > _PIXEL_FACTS_DISK_BUDGET:
        return False
    entries = []
    with os.scandir(path.parent) as scan:
        for scanned, entry in enumerate(scan, start=1):
            if scanned > _PIXEL_FACTS_DISK_MAX_ENTRIES + 16:
                return False
            name = entry.name
            if (len(name) != 69 or not name.endswith(".json")
                    or any(c not in "0123456789abcdef" for c in name[:64])
                    or not entry.is_file(follow_symlinks=False)):
                continue
            if Path(entry.path) == path:
                continue
            info = entry.stat(follow_symlinks=False)
            entries.append((info.st_mtime_ns, Path(entry.path), info.st_size))
    total, count = sum(item[2] for item in entries), len(entries)
    for _, candidate, entry_size in sorted(entries):
        if count < _PIXEL_FACTS_DISK_MAX_ENTRIES and total + size <= _PIXEL_FACTS_DISK_BUDGET:
            break
        candidate.unlink(missing_ok=True)
        count -= 1
        total -= entry_size
    return count < _PIXEL_FACTS_DISK_MAX_ENTRIES and total + size <= _PIXEL_FACTS_DISK_BUDGET


def _write_pixel_inventory_cache(path: Path | None, root: Path, records: dict) -> None:
    if path is None or len(records) > _PIXEL_FACTS_DISK_MAX_FILES:
        return
    # Persistence is optional: never queue workers behind another cache writer.
    if not _pixel_facts_disk_write_lock.acquire(blocking=False):
        return
    temporary = None
    try:
        encoded = json.dumps(records, separators=(",", ":"), sort_keys=True).encode("utf-8")
        data = json.dumps({"schema": 1, "root": _pixel_path_key(root),
                           "records": records, "digest": sha256(encoded).hexdigest()},
                          separators=(",", ":")).encode("utf-8")
        if len(data) > _PIXEL_FACTS_DISK_MAX_BYTES or not root.is_dir():
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        if not _reserve_pixel_cache_space(path, len(data)):
            return
        with tempfile.NamedTemporaryFile(mode="wb", prefix=".pixel-facts-", suffix=".tmp",
                                         dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(data)
        # Same-directory atomic replacement; concurrent snapshots can cost a
        # cache miss, never bypass the next per-file version/age check.
        if root.is_dir():
            os.replace(temporary, path)
    except (OSError, ValueError, TypeError):
        _logger.debug("[LOCAL_PIXEL_INVENTORY] cache_write_unavailable")
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
        _pixel_facts_disk_write_lock.release()


def _inventory_pixel_facts(
    path: Path, persisted: dict | None = None, verified: dict | None = None,
    reuse: dict | None = None,
) -> tuple[tuple[bool, int], bool, float]:
    """Return facts, cache-hit and lock-wait ms; call only from an I/O worker.

    The public single-file probe remains uncached for import/viewer consumers.
    Failures and non-pixel results both use its legacy (False, 0) contract, so
    neither is cached: a transient read failure must not hide a recovered image.
    """
    key = os.path.normcase(os.path.abspath(path))
    disk_key = _pixel_path_key(path) if verified is not None else None
    started = perf_counter()
    with _pixel_facts_stripes[hash(key) % len(_pixel_facts_stripes)]:
        wait_ms = (perf_counter() - started) * 1000.0
        try:
            version = _pixel_file_version(path)
        except OSError:
            with _pixel_facts_cache_lock:
                _pixel_facts_cache.pop(key, None)
            return (False, 0), False, wait_ms
        now = monotonic()
        with _pixel_facts_cache_lock:
            cached = _pixel_facts_cache.pop(key, None)
            if cached is not None:
                old_version, expires, facts, checked = cached
                if old_version == version and now < expires:
                    _pixel_facts_cache[key] = cached
                    if verified is not None:
                        verified[disk_key] = (version, facts[1], checked)
                    return facts, True, wait_ms

        record = (persisted or {}).get(disk_key)
        if record is not None:
            old_version, frames, checked = record
            if old_version == version and 0 <= time() - checked < _PIXEL_FACTS_DISK_TTL:
                facts = (True, frames)
                with _pixel_facts_cache_lock:
                    _pixel_facts_cache[key] = (version, now + _PIXEL_FACTS_CACHE_TTL, facts, checked)
                    while len(_pixel_facts_cache) > _PIXEL_FACTS_CACHE_LIMIT:
                        _pixel_facts_cache.popitem(last=False)
                if verified is not None:
                    verified[disk_key] = record
                if reuse is not None:
                    reuse["disk_hits"] += 1
                return facts, True, wait_ms

        probe_started = perf_counter()
        if reuse is not None:
            reuse["probes"] += 1
        facts = dicom_file_pixel_facts(path)
        if reuse is not None:
            elapsed_ms = (perf_counter() - probe_started) * 1000.0
            reuse["probe_ms"] += elapsed_ms
            reuse["max_probe_ms"] = max(reuse["max_probe_ms"], elapsed_ms)
        if facts[0]:
            try:
                unchanged = _pixel_file_version(path) == version
            except OSError:
                unchanged = False
            if unchanged:
                checked = time()
                with _pixel_facts_cache_lock:
                    _pixel_facts_cache[key] = (
                        version, monotonic() + _PIXEL_FACTS_CACHE_TTL, facts, checked,
                    )
                    while len(_pixel_facts_cache) > _PIXEL_FACTS_CACHE_LIMIT:
                        _pixel_facts_cache.popitem(last=False)
                if verified is not None:
                    verified[disk_key] = (version, facts[1], checked)
        return facts, False, wait_ms


def prime_dicom_pixel_fact(file_path: str | Path) -> tuple[bool, int]:
    """Prime the shared positive pixel-fact cache from an I/O worker.

    Local first-touch warming and Local inventory ask the same immutable header
    question.  Routing warming through the inventory single-flight prevents a
    raw-read worker and a header-probe worker from opening the same cold DICOM
    concurrently.  Successful pixel facts are version-bound in the existing
    short-lived cache; failures/non-pixel results retain the fail-open legacy
    behavior and are not made sticky.
    """
    return _inventory_pixel_facts(Path(file_path))[0]


def _inventory_dicom_paths(root: Path) -> list[Path]:
    """Enumerate once, retaining directory-entry type information until filtering.

    Like Path.glob('*.dcm'), use platform case matching, follow file symlinks,
    ignore non-files and do not recurse. Do not reuse DirEntry.stat for version
    validation: its cached Windows identity fields can be zero or stale.
    """
    try:
        with os.scandir(root) as scan:
            entries = list(scan)
    except OSError:
        return []  # Like glob, do not admit a partial failed enumeration.
    return sorted(
        Path(entry.path) for entry in entries
        if os.path.normcase(entry.name).endswith('.dcm') and entry.is_file()
    )


def _bounded_ordered_results(executor, function, values, max_pending: int):
    """Map in source order without eagerly submitting an entire large series."""
    source = iter(values)
    pending = deque()
    limit = max(1, int(max_pending))
    for _ in range(limit):
        try:
            pending.append(executor.submit(function, next(source)))
        except StopIteration:
            break
    while pending:
        future = pending.popleft()
        yield future.result()
        try:
            pending.append(executor.submit(function, next(source)))
        except StopIteration:
            pass


def inspect_series_pixel_inventory(series_path: str | Path) -> SeriesPixelInventory:
    """Count DICOM objects and pixel-bearing objects in a local series folder."""

    # Blank persisted paths must never be interpreted as the working directory.
    if not str(series_path or "").strip():
        return SeriesPixelInventory()
    started = perf_counter()
    root = Path(series_path)
    if not root.is_dir():
        return SeriesPixelInventory()
    try:
        scan_revision = int(root.stat().st_mtime_ns)
    except OSError:
        return SeriesPixelInventory()

    files = _inventory_dicom_paths(root)
    enumeration_ms = (perf_counter() - started) * 1000.0
    cache_started = perf_counter()
    cache_path = (_pixel_inventory_cache_path(root)
                  if len(files) <= _PIXEL_FACTS_DISK_MAX_FILES else None)
    cache_resolved = perf_counter()
    persisted = _read_pixel_inventory_cache(cache_path, root)
    cache_loaded = perf_counter()
    cache_read_ms = (cache_loaded - cache_started) * 1000.0
    cache_path_ms = (cache_resolved - cache_started) * 1000.0
    cache_load_ms = (cache_loaded - cache_resolved) * 1000.0
    verified = {} if cache_path is not None else None
    reuse = {"disk_hits": 0, "probes": 0, "probe_ms": 0.0, "max_probe_ms": 0.0}
    pixel_instance_count = 0
    frame_count = 0
    cache_hits = 0
    wait_ms = 0.0
    def _probe(path):
        # Each worker owns its mutable accounting dictionaries. The catalog
        # owner merges them after result delivery, avoiding shared-dict races.
        local_verified = {} if verified is not None else None
        local_reuse = {
            "disk_hits": 0, "probes": 0,
            "probe_ms": 0.0, "max_probe_ms": 0.0,
        }
        facts, hit, waited = _inventory_pixel_facts(
            path, persisted, local_verified, local_reuse,
        )
        return facts, hit, waited, local_verified, local_reuse

    executor = getattr(_ordered_inventory_context, "executor", None)
    results = (
        _bounded_ordered_results(
            executor, _probe, files,
            getattr(_ordered_inventory_context, "max_pending", 16),
        )
        if executor is not None and len(files) > 1
        else map(_probe, files)
    )
    for (has_pixel_data, frames), hit, waited, local_verified, local_reuse in results:
        cache_hits += int(hit)
        wait_ms += waited
        if verified is not None and local_verified:
            verified.update(local_verified)
        reuse["disk_hits"] += local_reuse["disk_hits"]
        reuse["probes"] += local_reuse["probes"]
        reuse["probe_ms"] += local_reuse["probe_ms"]
        reuse["max_probe_ms"] = max(
            reuse["max_probe_ms"], local_reuse["max_probe_ms"],
        )
        if has_pixel_data:
            pixel_instance_count += 1
            frame_count += frames
    cache_started = perf_counter()
    if verified is not None and verified != persisted:
        _write_pixel_inventory_cache(cache_path, root, verified)
    cache_write_ms = (perf_counter() - cache_started) * 1000.0
    try:
        final_revision = int(root.stat().st_mtime_ns)
    except OSError:
        final_revision = 0
    # A concurrent add/remove/rename makes these counts unsuitable for DB
    # backfill. They remain valid for this already-enumerated projection only.
    stable_revision = scan_revision if scan_revision == final_revision else 0
    result = SeriesPixelInventory(
        instance_count=len(files),
        pixel_instance_count=pixel_instance_count,
        frame_count=frame_count,
        directory_mtime_ns=stable_revision,
    )
    # Aggregate timings only: no path, patient/study/series UID or DICOM values.
    _logger.info(
        "[LOCAL_PIXEL_INVENTORY] files=%d cache_hits=%d probes=%d "
        "wait_ms=%.2f total_ms=%.2f disk_hits=%d enumeration_ms=%.2f "
        "cache_read_ms=%.2f cache_write_ms=%.2f probe_ms=%.2f max_probe_ms=%.2f stat_failures=%d "
        "cache_path_ms=%.2f cache_load_ms=%.2f",
        len(files), cache_hits, reuse["probes"],
        wait_ms, (perf_counter() - started) * 1000.0,
        reuse["disk_hits"], enumeration_ms, cache_read_ms, cache_write_ms,
        reuse["probe_ms"], reuse["max_probe_ms"], len(files) - cache_hits - reuse["probes"],
        cache_path_ms, cache_load_ms,
    )
    return result
