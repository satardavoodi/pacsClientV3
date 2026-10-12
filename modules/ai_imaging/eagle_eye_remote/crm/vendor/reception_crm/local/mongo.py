"""A deliberately crippled MongoDB client: reads, and nothing else.

The reception system's MongoDB runs on this machine's loopback interface with
no authentication, which means anything executing here -- including us -- can
read *and write* every clinical record in the centre. Reads are the capability
we want. Writes are a liability: they would bypass the vendor's validation,
their business logic and their audit trail, and a corrupted report would be
untraceable afterwards.

So this module does not merely *avoid* writing. It wraps pymongo's collection
in a facade that exposes ``find``, ``find_one``, ``aggregate``, ``count`` and
``distinct`` -- and nothing else. ``update_one``, ``insert_many``,
``delete_many``, ``create_index`` and friends are not attributes of the object
a caller receives, so a future contributor cannot reach them by accident and a
review does not have to catch it.

``create_index`` deserves its own mention: adding an index to a live clinical
collection changes the vendor's performance profile and would be silently
dropped by their next upgrade. Measured cost of the unindexed scan we replaced
it with is ~2s over 25k reports, which is invisible next to LLM latency.
"""

from __future__ import annotations

import logging
import os
import threading
from typing import TYPE_CHECKING, Any, Iterable, Iterator, Mapping

if TYPE_CHECKING:  # pragma: no cover - typing only
    # Imported for the annotation on `find` alone. Kept behind TYPE_CHECKING so
    # this module still imports on a machine without pymongo, which is how the
    # desktop app and several tests run.
    from pymongo.cursor import Cursor

LOG = logging.getLogger("reception_crm.local.mongo")

# The reception database is on THIS machine. There is no configuration for a
# remote host, on purpose: an agent installed at clinic A must not be
# repointable at clinic B's database. Compare local_host.py, which resolves the
# HTTP API's address for the same reason.
DEFAULT_URI = "mongodb://127.0.0.1:27017/"
DEFAULT_DB = "ClinicWebsite"

ENV_URI = "RECEPTION_MONGO_URI"
ENV_DB = "RECEPTION_MONGO_DB"
ENV_ENABLED = "RECEPTION_MONGO_ENABLED"

SERVER_SELECTION_TIMEOUT_MS = 4000

# --------------------------------------------------------------------------- #
# Being a good neighbour on someone else's database
# --------------------------------------------------------------------------- #
# This mongod is the reception software's. It is not ours, it is shared, and it
# was sized for their workload. Three limits keep a companion service from
# taking more of it than it is owed. All three were chosen from measurements on
# the live server (docs/AGENT_SAFETY_REVIEW.md), not from taste.

#: pymongo's default pool is 100 connections. The reception stack already holds
#: ~93 of its own; a read-only sidecar has no business being able to double
#: that. Four is more than enough for a request pattern that is one query at a
#: time per HTTP request.
MAX_POOL_SIZE = 4
MAX_IDLE_TIME_MS = 60_000

#: Every query the agent issues carries a server-side deadline. This is the
#: control that actually matters: `maxTimeMS` makes *mongod* kill the operation,
#: so a scan that goes long stops consuming the clinical server's CPU whether or
#: not our process is still waiting for it. Measured: a full-archive report
#: search takes ~1.9 s, so 15 s is roughly eight times the worst honest case --
#: generous enough never to fire in normal use, tight enough that nothing the
#: agent starts can run for a minute.
QUERY_TIMEOUT_MS = 15_000
#: The interactive tools (open one report, list a patient's history) are index
#: lookups measured in single-digit milliseconds. They get a much shorter leash.
FAST_QUERY_TIMEOUT_MS = 5_000

#: A collection scan of `receptions` reads ~1.4 GB through WiredTiger. One of
#: those at a time is a reasonable thing to ask of a shared server; three at
#: once -- which an unbounded thread-per-request HTTP server would happily start
#: -- is not. Callers that scan take this first, so concurrent requests queue
#: instead of multiplying the load on the reception database.
_scan_slot = threading.Semaphore(1)
SCAN_QUEUE_TIMEOUT_S = 30.0

_lock = threading.Lock()
_client = None


class ScanBusy(RuntimeError):
    """Another heavy scan is already running and this one waited long enough."""

    code = "LOCAL_DB_BUSY"


class scan_slot:
    """Serialise the expensive scans against the reception database.

    A context manager rather than a decorator so the acquired region is visible
    at the call site: everything inside it is holding the one slot, and keeping
    that region small is the whole point.
    """

    __slots__ = ("_held",)

    def __init__(self) -> None:
        self._held = False

    def __enter__(self) -> "scan_slot":
        self._held = _scan_slot.acquire(timeout=SCAN_QUEUE_TIMEOUT_S)
        if not self._held:
            raise ScanBusy(
                "the agent is already running a database scan; try again shortly"
            )
        return self

    def __exit__(self, *exc: Any) -> None:
        if self._held:
            _scan_slot.release()
            self._held = False


class LocalMongoUnavailable(RuntimeError):
    """The local reception database could not be reached.

    Always recoverable from the caller's point of view: every tool that uses
    this degrades to an explanatory error rather than a stack trace, because
    the API-backed tools must keep working when Mongo does not.
    """

    code = "LOCAL_DB_UNAVAILABLE"


class ReadOnlyCollection:
    """One collection, read methods only, every read on a server-side deadline.

    The deadline is applied HERE rather than at each call site for the same
    reason writes are impossible here rather than by convention: a control that
    depends on every future caller remembering it is not a control. A caller
    that genuinely needs longer passes `max_time_ms` explicitly and the
    intention is visible in the diff.
    """

    __slots__ = ("_collection", "name")

    def __init__(self, collection: Any) -> None:
        self._collection = collection
        self.name = collection.name

    @staticmethod
    def _deadline(kw: dict[str, Any], key: str = "max_time_ms") -> dict[str, Any]:
        kw.setdefault(key, QUERY_TIMEOUT_MS)
        return kw

    def find(self, filter: Mapping[str, Any] | None = None, projection: Any = None, **kw: Any) -> "Cursor":
        """Returns a pymongo Cursor, and says so.

        This was annotated `Iterator[dict]`, which is true but not the whole
        truth: every caller in this package goes on to call `.sort(...)` and
        `.limit(...)` on the result, which an Iterator does not have. A type
        checker reported seven `"Iterator[dict]" has no attribute "sort"`
        errors across four modules — all of them correct about the annotation
        and wrong about the code, because the annotation understated what is
        actually handed back.

        An annotation that is narrower than reality is not the safe choice. It
        makes every real use look like a bug, and a checker whose findings are
        mostly false is one nobody reads.
        """
        return self._collection.find(filter or {}, projection, **self._deadline(kw))

    def find_one(self, filter: Mapping[str, Any] | None = None, projection: Any = None, **kw: Any) -> dict | None:
        return self._collection.find_one(filter or {}, projection, **self._deadline(kw))

    def aggregate(self, pipeline: Iterable[Mapping[str, Any]], **kw: Any) -> Iterator[dict]:
        # $out and $merge are aggregation stages that WRITE. Refuse them here so
        # "aggregate" cannot become a back door to the thing this class exists
        # to prevent.
        stages = list(pipeline)
        for stage in stages:
            for forbidden in ("$out", "$merge"):
                if forbidden in stage:
                    raise LocalMongoUnavailable(
                        "%s is a write stage and is not permitted against the reception database"
                        % forbidden
                    )
        return self._collection.aggregate(stages, **self._deadline(kw, "maxTimeMS"))

    def count_documents(self, filter: Mapping[str, Any] | None = None, **kw: Any) -> int:
        return self._collection.count_documents(filter or {}, **self._deadline(kw, "maxTimeMS"))

    def estimated_document_count(self, **kw: Any) -> int:
        # Reads collection metadata, not documents. No deadline needed and none
        # offered: this is the one count that is free.
        return self._collection.estimated_document_count(**kw)

    def distinct(self, key: str, filter: Mapping[str, Any] | None = None, **kw: Any) -> list:
        return self._collection.distinct(key, filter, **self._deadline(kw, "maxTimeMS"))

    def index_information(self) -> dict:
        return self._collection.index_information()

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "<ReadOnlyCollection %s>" % self.name


class ReadOnlyDatabase:
    """One database, exposing only read-only collections."""

    __slots__ = ("_db", "name")

    def __init__(self, db: Any) -> None:
        self._db = db
        self.name = db.name

    def __getitem__(self, name: str) -> ReadOnlyCollection:
        return ReadOnlyCollection(self._db[name])

    def collection_names(self) -> list[str]:
        return sorted(self._db.list_collection_names())

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "<ReadOnlyDatabase %s>" % self.name


def is_enabled() -> bool:
    """Direct database access is opt-out, not opt-in.

    It is on by default because the agent is installed on the reception server
    and this is the whole point of being there. Setting
    ``RECEPTION_MONGO_ENABLED=false`` turns every local-database tool into a
    clean "not available here" error, which is what a deployment that is NOT on
    the reception server wants.
    """
    raw = (os.getenv(ENV_ENABLED) or "").strip().lower()
    if raw in ("0", "false", "no", "off"):
        return False
    return True


def _connect() -> Any:
    global _client
    with _lock:
        if _client is not None:
            return _client
        try:
            import pymongo
        except ImportError as exc:  # pragma: no cover - environment dependent
            raise LocalMongoUnavailable(
                "pymongo is not installed in this runtime, so the local reception "
                "database cannot be read"
            ) from exc

        uri = os.getenv(ENV_URI) or DEFAULT_URI
        try:
            client: Any = pymongo.MongoClient(
                uri,
                serverSelectionTimeoutMS=SERVER_SELECTION_TIMEOUT_MS,
                # `appname` is not decoration: it is what makes the agent's
                # connections identifiable in `db.currentOp()` and in mongod's
                # log, so whoever is diagnosing a slow reception system at 9am
                # can tell in one glance whether we are involved.
                appname="reception-crm-agent",
                # Bounded footprint on a database we do not own. See MAX_POOL_SIZE.
                maxPoolSize=MAX_POOL_SIZE,
                minPoolSize=0,
                maxIdleTimeMS=MAX_IDLE_TIME_MS,
                # Nothing here writes, so a lost write can never be a concern;
                # this just keeps the driver from waiting on write concerns.
                w=0,
            )
            client.admin.command("ping")
        except Exception as exc:  # noqa: BLE001 - pymongo raises a wide family
            raise LocalMongoUnavailable(
                "cannot reach the reception database: %s" % type(exc).__name__
            ) from exc
        LOG.info("connected to the local reception database at %s", uri)
        _client = client
        return _client


def reception_db() -> ReadOnlyDatabase:
    """The reception system's live database, read-only."""
    if not is_enabled():
        raise LocalMongoUnavailable(
            "direct database access is disabled on this installation "
            "(%s=false)" % ENV_ENABLED
        )
    client = _connect()
    return ReadOnlyDatabase(client[os.getenv(ENV_DB) or DEFAULT_DB])


def reset() -> None:
    """Drop the cached client. Test seam, and a way to recover after a restart."""
    global _client
    with _lock:
        if _client is not None:
            try:
                _client.close()
            except Exception:  # noqa: BLE001
                pass
        _client = None
