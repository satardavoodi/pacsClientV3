"""Keep every snapshot forever, without keeping every snapshot uncompressed.

Every management tool writes the payload it received to
``<data_root>/data/raw`` so an answer can be reproduced against exactly what the
agent saw. Nothing prunes them, and nothing should: a snapshot is the only
record of what a moving system looked like at the moment an answer was given.
Re-fetching gives different numbers, which is the whole point of having it.

So the growth — measured at 19.3 MB/day, about 6.9 GB a year, on a disk shared
with a clinical archive — cannot be solved by deleting anything. It is solved by
storing the same bytes smaller. These payloads are indented JSON with repeated
Persian keys and gzip takes roughly 90% off.

The rules this module works by, in order of importance:

1. **Nothing is removed until its replacement has been read back and compared.**
   Not "the write returned without error" — the gzip is opened, parsed, and
   checked equal to the original object. A compaction that loses one audit
   record is worse than a disk that fills up, because the disk announces itself.
2. **Only files old enough to be settled.** A snapshot from an hour ago may
   still be referenced by an answer someone is reading.
3. **Readers must not care.** `read()` takes either form, so nothing that reads
   a snapshot needs to know whether it has been compacted.
"""

from __future__ import annotations

import gzip
import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

LOG = logging.getLogger("reception_crm.snapshots")

SUFFIX = ".json"
COMPRESSED_SUFFIX = ".json.gz"

#: How long a snapshot stays uncompressed. Long enough that anything still being
#: looked at is untouched, short enough that the bulk of the tree is compacted.
DEFAULT_AGE_DAYS = 14


@dataclass
class CompactionResult:
    considered: int = 0
    compacted: int = 0
    skipped_recent: int = 0
    failed: int = 0
    bytes_before: int = 0
    bytes_after: int = 0

    @property
    def bytes_saved(self) -> int:
        return max(0, self.bytes_before - self.bytes_after)

    def as_dict(self) -> dict[str, Any]:
        return {
            "considered": self.considered,
            "compacted": self.compacted,
            "skipped_recent": self.skipped_recent,
            "failed": self.failed,
            "megabytes_saved": round(self.bytes_saved / (1024 * 1024), 1),
        }


def read(path: Path) -> Any:
    """Load a snapshot in either form.

    The reason this exists rather than callers checking the suffix: a reader
    that handles only `.json` does not fail loudly after compaction, it simply
    stops finding files — and "no snapshot for that day" is indistinguishable
    from "nothing happened that day".
    """
    path = Path(path)
    if path.suffix == ".gz":
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            return json.load(handle)
    if path.exists():
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    # A caller holding a pre-compaction path is the normal case after a
    # compaction run, not an error.
    compressed = path.with_suffix(path.suffix + ".gz")
    if compressed.exists():
        with gzip.open(compressed, "rt", encoding="utf-8") as handle:
            return json.load(handle)
    raise FileNotFoundError(path)


def compact_file(path: Path) -> tuple[bool, int, int]:
    """Compress one snapshot, verified. Returns (ok, bytes_before, bytes_after).

    The original is removed only after the compressed copy has been read back
    and its parsed content compared with the original's. If anything about that
    fails the original is left exactly where it was and the partial `.gz` is
    cleaned up — a half-finished compaction must not look like a finished one.
    """
    target = path.with_suffix(path.suffix + ".gz")
    before = path.stat().st_size
    try:
        original = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        # Not ours to repair, and definitely not ours to delete.
        LOG.warning("snapshot %s is not readable JSON (%s); left untouched", path, exc)
        return False, before, before

    try:
        with gzip.open(target, "wt", encoding="utf-8") as handle:
            json.dump(original, handle, ensure_ascii=False)

        with gzip.open(target, "rt", encoding="utf-8") as handle:
            round_tripped = json.load(handle)
        if round_tripped != original:
            raise ValueError("round-trip mismatch")
    except Exception as exc:  # noqa: BLE001 - any failure means: keep the original
        LOG.error("could not compact %s (%s: %s); original kept", path, type(exc).__name__, exc)
        target.unlink(missing_ok=True)
        return False, before, before

    after = target.stat().st_size
    path.unlink()
    return True, before, after


def compact(
    root: Path | str,
    *,
    older_than_days: float = DEFAULT_AGE_DAYS,
    now: float | None = None,
    limit: int | None = None,
) -> CompactionResult:
    """Compact settled snapshots under `root`.

    `limit` bounds one run. This runs on a machine whose real job is a clinic's
    reception desk, and a first run over a year of snapshots should not become
    an hour of disk I/O nobody asked for.
    """
    root = Path(root)
    result = CompactionResult()
    if not root.exists():
        return result

    cutoff = (now if now is not None else time.time()) - older_than_days * 86400
    for path in sorted(root.rglob("*" + SUFFIX)):
        if path.name.endswith(COMPRESSED_SUFFIX):
            continue
        result.considered += 1
        try:
            if path.stat().st_mtime > cutoff:
                result.skipped_recent += 1
                continue
        except OSError:
            continue

        ok, before, after = compact_file(path)
        result.bytes_before += before
        result.bytes_after += after
        if ok:
            result.compacted += 1
        else:
            result.failed += 1

        if limit is not None and result.compacted >= limit:
            break

    if result.compacted or result.failed:
        LOG.info(
            "snapshot compaction: %d compacted, %d failed, %.1f MB saved",
            result.compacted, result.failed, result.bytes_saved / (1024 * 1024),
        )
    return result


def footprint(root: Path | str) -> dict[str, Any]:
    """Counts and sizes, split by whether a snapshot has been compacted yet."""
    root = Path(root)
    plain = compressed = 0
    plain_bytes = compressed_bytes = 0
    oldest: float | None = None

    for path in root.rglob("*.json*"):
        try:
            stat = path.stat()
        except OSError:
            continue
        if oldest is None or stat.st_mtime < oldest:
            oldest = stat.st_mtime
        if path.name.endswith(COMPRESSED_SUFFIX):
            compressed += 1
            compressed_bytes += stat.st_size
        elif path.suffix == SUFFIX:
            plain += 1
            plain_bytes += stat.st_size

    total_bytes = plain_bytes + compressed_bytes
    return {
        "files": plain + compressed,
        "compacted": compressed,
        "uncompacted": plain,
        "megabytes": round(total_bytes / (1024 * 1024), 1),
        "oldest_days": round((time.time() - oldest) / 86400, 1) if oldest else 0.0,
        "policy": (
            "compacted with gzip after "
            f"{DEFAULT_AGE_DAYS} days, verified before the original is removed. "
            "Nothing is ever deleted - these are the audit trail."
        ),
    }
