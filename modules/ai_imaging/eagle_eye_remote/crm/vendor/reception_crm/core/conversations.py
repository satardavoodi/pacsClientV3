"""Server-authoritative chat conversations.

The phone shows a list of chats; this module owns it. The phone keeps a mirror
so it can render offline, but the server decides what exists, what it is called
and what order it is in -- because the same user signs in from more than one
device, and a mirror that can invent state is a mirror that will disagree with
itself.

Four decisions worth stating up front, because each is load-bearing:

**Ownership is enforced on every read, not just on list.** A conversation
belongs to a (center, user) pair, and an id alone never grants access. Passing
an id you happen to know must not read someone else's chat. This is the same
class of mistake as letting a client-supplied ``center`` choose the roles row --
see ``adapters/http_api.handle_session``.

**Deletes are tombstones.** A row removed outright is invisible to a mirror that
was offline when it happened, so the phone would keep showing a chat the user
deleted on another device. `deleted_at` is set, the row stays, and
`changed_since` hands the tombstone to the mirror. Real purging happens later,
after a window the mirror can tolerate.

**Sync is by revision, not by timestamp.** Two phones and a server do not share
a clock. A mirror that asks "what changed since 14:02" silently loses whatever
changed inside the skew. Each owner has a monotonic counter instead; the mirror
stores the number it last saw and asks for everything above it.

**Large analysis data lives beside, not inside, the chat database.** Turn rows
remain deliberately narrow.  A completed assistant analysis may attach a
complete JSON response, generated CSV tables and references to immutable raw
snapshots.  SQLite stores only their ownership-scoped metadata; managed files
live below the configured data root and are removed with the conversation.

SQLite rather than a JSON file (unlike ``idempotency.py``): this table grows
without bound, is read by ordered slice, and is written from several request
threads at once.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from . import modes as mode_registry
from .analysis_artifacts import ArtifactFile, create_artifacts, remove_managed_files
from .attachments import Attachment
from .errors import ReceptionCoreError
from .types import Principal

#: Shapes returned by this module's list-valued methods.
#:
#: Named at module level for the same reason as `registry.ToolDescriptions`:
#: `ConversationStore` defines a method called `list`, which shadows the builtin
#: inside the class body, so `list[...]` written there resolves to the METHOD
#: rather than to the type. Those annotations were quietly nonsense, and a type
#: checker said so before any reader noticed.
ResultIds = list[Any]
TurnList = list[dict[str, str]]
EvidenceList = list[dict[str, Any]]

# One source of truth. Duplicating the list here is how a mode ends up offered
# by /api/modes and then rejected on save.
DEFAULT_MODE = mode_registry.DEFAULT_MODE

MAX_TITLE_CHARS = 120
MAX_USER_TEXT_CHARS = 8000
MAX_ASSISTANT_TEXT_CHARS = 32000
# Compatibility for callers/tests which imported the original public constant.
MAX_TEXT_CHARS = MAX_USER_TEXT_CHARS
MAX_RESULT_IDS = 500
DEFAULT_PAGE = 50
MAX_PAGE = 200

#: Verbatim turns handed to the model.
#:
#: Was 6 — three exchanges — which a clinician working through one patient
#: crosses in about a minute, after which earlier context was gone with nothing
#: to say so. The live endpoint accepted a 20,000-token prompt without
#: complaint, so 6 was never a budget decision; it was a default nobody
#: revisited. 16 is still a small fraction of the window.
DEFAULT_HISTORY_TURNS = 16
MAX_HISTORY_TURNS = 40

#: How many referents a session may carry. Small on purpose: this is "which
#: patient are we talking about", not a transcript, and every entry is re-sent
#: to the provider on every subsequent turn.
MAX_FACTS = 12

# A prior analysis may contain row-level clinical and financial data.  Reusing
# it in the next turn is useful, but reading an unbounded artifact into the
# process would turn a damaged (or unexpectedly huge) file into a memory DoS.
# Real RAZI evidence files are far below this ceiling; larger files remain
# available as downloadable artifacts and are simply not used as LLM memory.
MAX_SESSION_EVIDENCE_BYTES = 8 * 1024 * 1024
MAX_SESSION_EVIDENCE_SOURCES = 16
# A long analytical chat can ask many follow-ups about one source before
# returning to another. Looking through only the last handful would make the
# earlier source disappear merely because it had not been mentioned recently.
# Metadata reads are cheap; payload bytes and distinct sources remain tightly
# bounded by the two ceilings above.
MAX_SESSION_EVIDENCE_RUNS = 200

# How long a deleted conversation's tombstone is kept so that offline mirrors
# can still learn about the deletion. Beyond this the row is purged for real.
TOMBSTONE_SECONDS = 30 * 24 * 60 * 60

LOG = logging.getLogger(__name__)


class ConversationError(ReceptionCoreError):
    code = "CONVERSATION"


class ConversationNotFound(ConversationError):
    code = "CONVERSATION_NOT_FOUND"


class InvalidMode(ConversationError):
    code = "VALIDATION"


SCHEMA = """
CREATE TABLE IF NOT EXISTS conversations (
    id            TEXT PRIMARY KEY,
    center        TEXT NOT NULL,
    username      TEXT NOT NULL,
    title         TEXT NOT NULL,
    mode          TEXT NOT NULL,
    created_at    REAL NOT NULL,
    updated_at    REAL NOT NULL,
    archived_at   REAL,
    deleted_at    REAL,
    turn_count    INTEGER NOT NULL DEFAULT 0,
    revision      INTEGER NOT NULL DEFAULT 1,
    facts         TEXT
);
CREATE INDEX IF NOT EXISTS ix_conversations_owner
    ON conversations (center, username, updated_at DESC);
CREATE INDEX IF NOT EXISTS ix_conversations_revision
    ON conversations (center, username, revision);

CREATE TABLE IF NOT EXISTS turns (
    id              TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL,
    seq             INTEGER NOT NULL,
    role            TEXT NOT NULL,
    text            TEXT NOT NULL,
    tool            TEXT,
    arguments       TEXT,
    result_ids      TEXT,
    result_count    INTEGER,
    request_id      TEXT,
    audit_id        TEXT,
    created_at      REAL NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS ix_turns_seq
    ON turns (conversation_id, seq);

CREATE TABLE IF NOT EXISTS analysis_runs (
    id              TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL,
    turn_id         TEXT NOT NULL UNIQUE,
    request_id      TEXT,
    tool            TEXT,
    status          TEXT NOT NULL,
    created_at      REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_analysis_runs_conversation
    ON analysis_runs (conversation_id, created_at DESC);

CREATE TABLE IF NOT EXISTS analysis_artifacts (
    id            TEXT PRIMARY KEY,
    analysis_id   TEXT NOT NULL,
    kind          TEXT NOT NULL,
    display_name  TEXT NOT NULL,
    format        TEXT NOT NULL,
    relative_path TEXT NOT NULL,
    mime_type     TEXT NOT NULL,
    size_bytes    INTEGER NOT NULL,
    row_count     INTEGER,
    sha256        TEXT,
    complete      INTEGER NOT NULL DEFAULT 1,
    managed       INTEGER NOT NULL DEFAULT 1,
    created_at    REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_analysis_artifacts_analysis
    ON analysis_artifacts (analysis_id, created_at ASC);
"""


#: Columns added after the first release, with the DDL that adds them.
#:
#: `CREATE TABLE IF NOT EXISTS` in SCHEMA leaves an existing table exactly as it
#: is, so a new column in that statement reaches a fresh install and NEVER
#: reaches the one database that matters -- the clinic's, which already exists
#: and already holds every conversation anyone has had. The failure is silent
#: until the first query naming the column.
_MIGRATIONS: tuple[tuple[str, str, str], ...] = (
    ("conversations", "facts", "ALTER TABLE conversations ADD COLUMN facts TEXT"),
)


def _migrate(conn: sqlite3.Connection) -> None:
    """Bring an existing database up to the current schema. Idempotent.

    Additive only, by construction: this adds nullable columns and nothing
    else. No column is dropped, renamed or retyped, so a database touched by a
    newer build still opens in an older one -- which matters because a rollback
    to the previous installer must not leave the clinic with a chat history it
    can no longer read.
    """
    for table, column, ddl in _MIGRATIONS:
        existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
        if column not in existing:
            conn.execute(ddl)


class ConversationStore:
    """All access goes through a Principal. There is no unscoped read."""

    def __init__(self, data_root: Path | str) -> None:
        self._root = Path(data_root)
        self._path = self._root / "data" / "conversations.sqlite3"
        self._lock = threading.Lock()
        self._ready = False

    @property
    def path(self) -> Path:
        return self._path

    @staticmethod
    def _owner(principal: Principal) -> tuple[str, str]:
        """(center, username) as storable strings.

        Both fields are Optional on Principal — the legacy shared-token path can
        leave them unset — and the columns are NOT NULL. Coercing here keeps a
        half-identified caller in its own bucket instead of crashing the insert
        or, worse, sharing a NULL bucket with every other one.
        """
        return str(principal.center or ""), str(principal.user or "")

    @contextmanager
    def _db(self) -> Iterator[sqlite3.Connection]:
        """One short-lived connection per operation, always closed.

        `with sqlite3.connect(...) as conn` commits but does **not** close, so
        using it alone leaks a handle per request until the service runs out.
        """
        self._path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self._path, timeout=10.0)
        conn.row_factory = sqlite3.Row
        try:
            # WAL: several request threads read while one writes. Without it a
            # listing blocks behind an append and the phone sees a timeout.
            conn.execute("PRAGMA journal_mode=WAL")
            if not self._ready:
                conn.executescript(SCHEMA)
                _migrate(conn)
                self._ready = True
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    # ---- ownership -------------------------------------------------------

    def _owned(
        self,
        conn: sqlite3.Connection,
        principal: Principal,
        conversation_id: str,
        *,
        allow_deleted: bool = False,
    ) -> sqlite3.Row:
        """Fetch a row this principal owns, or raise.

        The center and user are part of the WHERE clause rather than checked
        afterwards, so there is no code path where a row is loaded first and
        authorised second.
        """
        center, username = self._owner(principal)
        row = conn.execute(
            "SELECT * FROM conversations WHERE id = ? AND center = ? AND username = ?",
            (str(conversation_id or ""), center, username),
        ).fetchone()
        if row is None or (row["deleted_at"] is not None and not allow_deleted):
            # Deliberately the same error whether the id is unknown or belongs
            # to someone else: distinguishing them tells a caller which ids exist.
            raise ConversationNotFound("No such conversation.")
        return row

    def _next_revision(self, conn: sqlite3.Connection, principal: Principal) -> int:
        row = conn.execute(
            "SELECT COALESCE(MAX(revision), 0) AS r FROM conversations"
            " WHERE center = ? AND username = ?",
            self._owner(principal),
        ).fetchone()
        return int(row["r"]) + 1

    # ---- create ----------------------------------------------------------

    def create(
        self, principal: Principal, *, title: str = "", mode: str = DEFAULT_MODE
    ) -> dict[str, Any]:
        center, username = self._owner(principal)
        now = time.time()
        record = {
            "id": _new_id(),
            "center": center,
            "username": username,
            "title": _title(title),
            "mode": _mode(mode),
            "created_at": now,
            "updated_at": now,
            "archived_at": None,
            "deleted_at": None,
            "turn_count": 0,
        }
        with self._lock, self._db() as conn:
            record["revision"] = self._next_revision(conn, principal)
            conn.execute(
                "INSERT INTO conversations (id, center, username, title, mode, created_at,"
                " updated_at, archived_at, deleted_at, turn_count, revision)"
                " VALUES (:id, :center, :username, :title, :mode, :created_at,"
                " :updated_at, :archived_at, :deleted_at, :turn_count, :revision)",
                record,
            )
        return _conversation_dict(record)

    # ---- read ------------------------------------------------------------

    def get(self, principal: Principal, conversation_id: str) -> dict[str, Any]:
        with self._lock, self._db() as conn:
            return _conversation_dict(dict(self._owned(conn, principal, conversation_id)))

    def turns(
        self,
        principal: Principal,
        conversation_id: str,
        *,
        after_seq: int = 0,
        limit: int = DEFAULT_PAGE,
    ) -> list[dict[str, Any]]:
        limit = _page(limit)
        with self._lock, self._db() as conn:
            self._owned(conn, principal, conversation_id)  # ownership first
            rows = conn.execute(
                "SELECT * FROM turns WHERE conversation_id = ? AND seq > ?"
                " ORDER BY seq ASC LIMIT ?",
                (conversation_id, _int(after_seq), limit),
            ).fetchall()
        return [_turn_dict(dict(r)) for r in rows]

    def analyses(
        self,
        principal: Principal,
        conversation_id: str,
        *,
        limit: int = MAX_PAGE,
    ) -> list[dict[str, Any]]:
        """Return durable analysis metadata without exposing server paths."""
        with self._lock, self._db() as conn:
            self._owned(conn, principal, conversation_id)
            runs = conn.execute(
                "SELECT * FROM analysis_runs WHERE conversation_id = ?"
                " ORDER BY created_at DESC LIMIT ?",
                (conversation_id, _page(limit, default=MAX_PAGE)),
            ).fetchall()
            runs = list(reversed(runs))
            run_ids = [row["id"] for row in runs]
            artifacts: dict[str, list[dict[str, Any]]] = {run_id: [] for run_id in run_ids}
            if run_ids:
                placeholders = ",".join("?" for _ in run_ids)
                rows = conn.execute(
                    f"SELECT * FROM analysis_artifacts WHERE analysis_id IN ({placeholders})"
                    " ORDER BY created_at ASC",
                    run_ids,
                ).fetchall()
                for row in rows:
                    artifacts[row["analysis_id"]].append(_artifact_dict(dict(row)))
        return [_analysis_dict(dict(row), artifacts[row["id"]]) for row in runs]

    def artifact_path(self, principal: Principal, artifact_id: str) -> Path:
        """Resolve one owned artifact to a confined local path for desktop use."""
        center, username = self._owner(principal)
        with self._lock, self._db() as conn:
            row = conn.execute(
                "SELECT aa.relative_path FROM analysis_artifacts aa"
                " JOIN analysis_runs ar ON ar.id = aa.analysis_id"
                " JOIN conversations c ON c.id = ar.conversation_id"
                " WHERE aa.id = ? AND c.center = ? AND c.username = ?"
                " AND c.deleted_at IS NULL",
                (str(artifact_id or ""), center, username),
            ).fetchone()
        if row is None:
            raise ConversationNotFound("No such analysis file.")
        root = self._root.resolve()
        path = (root / row["relative_path"]).resolve()
        try:
            path.relative_to(root)
        except ValueError as exc:
            raise ConversationNotFound("No such analysis file.") from exc
        if not path.is_file():
            raise ConversationNotFound("The analysis file is no longer available.")
        return path

    def latest_evidence_for_llm(
        self, principal: Principal, conversation_id: str
    ) -> dict[str, Any] | None:
        """Return recent owned analysis evidence as cumulative server memory.

        The client supplies only ``conversation_id``. Ownership is checked in
        the SQL query before a path is resolved, and the path must remain below
        this store's root. Missing, corrupt or oversized evidence fails soft:
        the next turn will query the reception system normally instead of
        losing the answer or trusting a partial snapshot.
        """
        center, username = self._owner(principal)
        with self._lock, self._db() as conn:
            self._owned(conn, principal, conversation_id)
            rows = conn.execute(
                "SELECT ar.id AS analysis_id, ar.created_at, aa.relative_path,"
                " aa.size_bytes FROM analysis_runs ar"
                " JOIN analysis_artifacts aa ON aa.analysis_id = ar.id"
                " JOIN conversations c ON c.id = ar.conversation_id"
                " WHERE ar.conversation_id = ? AND ar.status = 'completed'"
                " AND aa.kind = 'evidence' AND aa.complete = 1 AND aa.managed = 1"
                " AND c.center = ? AND c.username = ? AND c.deleted_at IS NULL"
                " ORDER BY ar.created_at DESC LIMIT ?",
                (conversation_id, center, username, MAX_SESSION_EVIDENCE_RUNS),
            ).fetchall()
        if not rows:
            return None
        root = self._root.resolve()
        analysis_root = (root / "analyses").resolve()
        try:
            analysis_root.relative_to(root)
        except ValueError:
            LOG.warning("Analysis directory escaped the clinical data root")
            return None
        sources: list[dict[str, Any]] = []
        seen: set[str] = set()
        remaining = MAX_SESSION_EVIDENCE_BYTES
        for row in rows:
            declared_size = int(row["size_bytes"] or 0)
            if declared_size <= 0 or declared_size > remaining:
                continue
            path = (root / row["relative_path"]).resolve()
            try:
                path.relative_to(analysis_root)
                actual_size = path.stat().st_size
                if actual_size > remaining:
                    continue
                raw = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
                LOG.warning("Stored session evidence could not be read safely")
                continue
            remaining -= actual_size
            if not isinstance(raw, list):
                continue
            run_snapshot = _iso(row["created_at"])
            for item in raw:
                if len(sources) >= MAX_SESSION_EVIDENCE_SOURCES:
                    break
                if not isinstance(item, dict):
                    continue
                tool = str(item.get("tool") or "").strip()[:120]
                arguments = item.get("arguments")
                if not tool or not isinstance(arguments, dict):
                    continue
                clean_arguments = {
                    str(key): value
                    for key, value in arguments.items()
                    if str(key) != "data_root"
                }
                key = json.dumps(
                    [tool, clean_arguments], ensure_ascii=False, sort_keys=True, default=str
                )
                if key in seen:
                    continue
                seen.add(key)
                sources.append(
                    {
                        "tool": tool,
                        "arguments": clean_arguments,
                        "ok": bool(item.get("ok")),
                        "data": item.get("data"),
                        "error": item.get("error") if isinstance(item.get("error"), dict) else None,
                        "snapshotAt": str(item.get("sessionSnapshotAt") or run_snapshot or "") or None,
                    }
                )
            if len(sources) >= MAX_SESSION_EVIDENCE_SOURCES:
                break
        if not sources:
            return None
        return {
            "analysisId": rows[0]["analysis_id"],
            "createdAt": _iso(rows[0]["created_at"]),
            "sources": sources,
        }

    def list(
        self,
        principal: Principal,
        *,
        include_archived: bool = False,
        include_deleted: bool = False,
        limit: int = DEFAULT_PAGE,
    ) -> list[dict[str, Any]]:
        center, username = self._owner(principal)
        sql = ["SELECT * FROM conversations WHERE center = ? AND username = ?"]
        args: list[Any] = [center, username]
        if not include_deleted:
            sql.append("AND deleted_at IS NULL")
        if not include_archived:
            sql.append("AND archived_at IS NULL")
        sql.append("ORDER BY updated_at DESC LIMIT ?")
        args.append(_page(limit))
        with self._lock, self._db() as conn:
            rows = conn.execute(" ".join(sql), args).fetchall()
        return [_conversation_dict(dict(r)) for r in rows]

    def changed_since(
        self, principal: Principal, since_revision: int = 0, *, limit: int = MAX_PAGE
    ) -> dict[str, Any]:
        """Everything the mirror has not seen, tombstones included."""
        limit = _page(limit, default=MAX_PAGE)
        center, username = self._owner(principal)
        with self._lock, self._db() as conn:
            rows = conn.execute(
                "SELECT * FROM conversations WHERE center = ? AND username = ?"
                " AND revision > ? ORDER BY revision ASC LIMIT ?",
                (center, username, _int(since_revision), limit),
            ).fetchall()
            high = int(
                conn.execute(
                    "SELECT COALESCE(MAX(revision), 0) AS r FROM conversations"
                    " WHERE center = ? AND username = ?",
                    (center, username),
                ).fetchone()["r"]
            )
        changed = [_conversation_dict(dict(r)) for r in rows]
        # When the page is full the mirror has NOT caught up: hand back the
        # revision of the last row it actually received, never the table high
        # water mark, or the rows in between are skipped forever.
        cursor = changed[-1]["revision"] if changed and len(changed) == limit else high
        return {"conversations": changed, "revision": cursor, "more": len(changed) == limit}

    # ---- mutate ----------------------------------------------------------

    def rename(self, principal: Principal, conversation_id: str, title: str) -> dict[str, Any]:
        return self._patch(principal, conversation_id, {"title": _title(title, allow_empty=False)})

    def set_mode(self, principal: Principal, conversation_id: str, mode: str) -> dict[str, Any]:
        return self._patch(principal, conversation_id, {"mode": _mode(mode)})

    def archive(self, principal: Principal, conversation_id: str) -> dict[str, Any]:
        return self._patch(principal, conversation_id, {"archived_at": time.time()})

    def unarchive(self, principal: Principal, conversation_id: str) -> dict[str, Any]:
        return self._patch(principal, conversation_id, {"archived_at": None})

    def delete(self, principal: Principal, conversation_id: str) -> dict[str, Any]:
        """Tombstone the conversation and drop its turns.

        The turns go now -- they are the PHI, and a user who deletes a chat means
        it. The header row stays until `purge_tombstones` so that a mirror which
        was offline still learns the chat is gone.
        """
        managed_paths: list[str] = []
        with self._lock, self._db() as conn:
            row = self._owned(conn, principal, conversation_id)
            now = time.time()
            managed_paths = [
                item["relative_path"]
                for item in conn.execute(
                    "SELECT aa.relative_path FROM analysis_artifacts aa"
                    " JOIN analysis_runs ar ON ar.id = aa.analysis_id"
                    " WHERE ar.conversation_id = ? AND aa.managed = 1",
                    (row["id"],),
                ).fetchall()
            ]
            conn.execute(
                "DELETE FROM analysis_artifacts WHERE analysis_id IN"
                " (SELECT id FROM analysis_runs WHERE conversation_id = ?)",
                (row["id"],),
            )
            conn.execute("DELETE FROM analysis_runs WHERE conversation_id = ?", (row["id"],))
            conn.execute("DELETE FROM turns WHERE conversation_id = ?", (row["id"],))
            conn.execute(
                "UPDATE conversations SET deleted_at = ?, updated_at = ?, turn_count = 0,"
                " revision = ? WHERE id = ?",
                (now, now, self._next_revision(conn, principal), row["id"]),
            )
            updated = conn.execute(
                "SELECT * FROM conversations WHERE id = ?", (row["id"],)
            ).fetchone()
        failures = remove_managed_files(self._root, managed_paths)
        if failures:
            LOG.warning("Could not remove %d managed analysis files", len(failures))
        return _conversation_dict(dict(updated))

    def _patch(
        self, principal: Principal, conversation_id: str, changes: dict[str, Any]
    ) -> dict[str, Any]:
        with self._lock, self._db() as conn:
            row = self._owned(conn, principal, conversation_id)
            fields = dict(changes)
            fields["updated_at"] = time.time()
            fields["revision"] = self._next_revision(conn, principal)
            assignments = ", ".join(f"{k} = :{k}" for k in fields)
            conn.execute(
                f"UPDATE conversations SET {assignments} WHERE id = :id",
                {**fields, "id": row["id"]},
            )
            updated = conn.execute(
                "SELECT * FROM conversations WHERE id = ?", (row["id"],)
            ).fetchone()
        return _conversation_dict(dict(updated))

    # ---- turns -----------------------------------------------------------

    def append_turn(
        self,
        principal: Principal,
        conversation_id: str,
        *,
        role: str,
        text: str,
        tool: str | None = None,
        arguments: dict[str, Any] | None = None,
        result_ids: ResultIds | None = None,
        result_count: int | None = None,
        request_id: str = "",
        audit_id: str | None = None,
    ) -> dict[str, Any]:
        """Append one turn and bump the conversation.

        Tool result payloads remain out of this narrow relational row. A
        successful assistant turn may attach them through ``record_analysis``.
        """
        role = "assistant" if str(role) == "assistant" else "user"
        with self._lock, self._db() as conn:
            row = self._owned(conn, principal, conversation_id)
            seq = int(row["turn_count"]) + 1
            now = time.time()
            record = {
                "id": _new_id("turn"),
                "conversation_id": row["id"],
                "seq": seq,
                "role": role,
                "text": _clip(
                    text,
                    MAX_ASSISTANT_TEXT_CHARS if role == "assistant" else MAX_USER_TEXT_CHARS,
                ),
                "tool": tool or None,
                "arguments": _dump(arguments),
                "result_ids": _dump(_ids(result_ids)),
                "result_count": None if result_count is None else int(result_count),
                "request_id": str(request_id or ""),
                "audit_id": audit_id or None,
                "created_at": now,
            }
            conn.execute(
                "INSERT INTO turns (id, conversation_id, seq, role, text, tool, arguments,"
                " result_ids, result_count, request_id, audit_id, created_at)"
                " VALUES (:id, :conversation_id, :seq, :role, :text, :tool, :arguments,"
                " :result_ids, :result_count, :request_id, :audit_id, :created_at)",
                record,
            )
            title = row["title"]
            updates: dict[str, Any] = {
                "turn_count": seq,
                "updated_at": now,
                "revision": self._next_revision(conn, principal),
                "id": row["id"],
            }
            # An untitled chat takes its name from the first thing the user said,
            # the way every chat client does. Only from a *user* turn: naming it
            # after the agent's reply describes the answer, not the question.
            if not title and role == "user":
                updates["title"] = _title(text)
            assignments = ", ".join(f"{k} = :{k}" for k in updates if k != "id")
            conn.execute(f"UPDATE conversations SET {assignments} WHERE id = :id", updates)
        return _turn_dict(record)

    def record_analysis(
        self,
        principal: Principal,
        conversation_id: str,
        turn_id: str,
        response: dict[str, Any],
        *,
        evidence: EvidenceList | None = None,
        attachments: tuple[Attachment, ...] = (),
    ) -> dict[str, Any]:
        """Attach a complete, server-local analysis to an assistant turn.

        The unique turn id makes retries idempotent. Files are created before
        their metadata transaction and are cleaned up if that transaction does
        not commit.
        """
        analysis_id = _new_id("analysis")
        created: list[ArtifactFile] = []
        with self._lock:
            with self._db() as conn:
                self._owned(conn, principal, conversation_id)
                existing = conn.execute(
                    "SELECT * FROM analysis_runs WHERE turn_id = ? AND conversation_id = ?",
                    (str(turn_id or ""), conversation_id),
                ).fetchone()
                if existing is not None:
                    rows = conn.execute(
                        "SELECT * FROM analysis_artifacts WHERE analysis_id = ?"
                        " ORDER BY created_at ASC",
                        (existing["id"],),
                    ).fetchall()
                    return _analysis_dict(
                        dict(existing), [_artifact_dict(dict(row)) for row in rows]
                    )
                turn = conn.execute(
                    "SELECT id, role FROM turns WHERE id = ? AND conversation_id = ?",
                    (str(turn_id or ""), conversation_id),
                ).fetchone()
                if turn is None or turn["role"] != "assistant":
                    raise ConversationNotFound("No such assistant turn.")

            try:
                created = create_artifacts(
                    self._root,
                    conversation_id,
                    analysis_id,
                    dict(response or {}),
                    evidence=evidence,
                    attachments=attachments,
                )
                now = time.time()
                raw_action = response.get("action")
                action: dict[str, Any] = raw_action if isinstance(raw_action, dict) else {}
                status = response.get("status")
                if not status:
                    status = "completed" if response.get("success") else "not_completed"
                run = {
                    "id": analysis_id,
                    "conversation_id": conversation_id,
                    "turn_id": turn_id,
                    "request_id": str(response.get("requestId") or ""),
                    "tool": str(response.get("tool") or action.get("tool") or "") or None,
                    "status": str(status),
                    "created_at": now,
                }
                with self._db() as conn:
                    self._owned(conn, principal, conversation_id)
                    conn.execute(
                        "INSERT INTO analysis_runs"
                        " (id, conversation_id, turn_id, request_id, tool, status, created_at)"
                        " VALUES (:id, :conversation_id, :turn_id, :request_id, :tool, :status, :created_at)",
                        run,
                    )
                    for artifact in created:
                        conn.execute(
                            "INSERT INTO analysis_artifacts"
                            " (id, analysis_id, kind, display_name, format, relative_path,"
                            " mime_type, size_bytes, row_count, sha256, complete, managed, created_at)"
                            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                            (
                                artifact.id,
                                analysis_id,
                                artifact.kind,
                                artifact.display_name,
                                artifact.format,
                                artifact.relative_path,
                                artifact.mime_type,
                                artifact.size_bytes,
                                artifact.row_count,
                                artifact.sha256 or None,
                                int(artifact.complete),
                                int(artifact.managed),
                                now,
                            ),
                        )
                return _analysis_dict(run, [_artifact_from_file(item) for item in created])
            except Exception:
                failures = remove_managed_files(
                    self._root, [item.relative_path for item in created if item.managed]
                )
                if failures:
                    LOG.warning(
                        "Could not roll back %d managed analysis files", len(failures)
                    )
                raise

    def remember_facts(
        self, principal: Principal, conversation_id: str, facts: dict[str, Any]
    ) -> dict[str, Any]:
        """Merge server-observed referents into the conversation.

        "Server-observed" is the whole point. These come from the arguments a
        tool was ACTUALLY dispatched with, never from prose the model wrote --
        so the session's idea of "this patient" is a record of what was really
        queried, not of what the model said it queried. A model that
        misremembers cannot corrupt the referent, because it never writes here.

        Merging, not replacing: asking about a date range after naming a patient
        should narrow the session, not forget the patient.
        """
        clean = {k: v for k, v in (facts or {}).items() if v not in (None, "", [], {})}
        if not clean:
            # `get()` returns the PUBLISHED shape, which deliberately omits
            # facts -- they carry patient identifiers and the phone has no use
            # for them. Read the stored value instead of the published one.
            return self.facts_for_llm(principal, conversation_id)
        with self._lock, self._db() as conn:
            row = self._owned(conn, principal, conversation_id)
            merged = dict(_load(row["facts"]) or {})
            merged.update(clean)
            # Bounded: this is a referent, not a transcript. An unbounded blob
            # would be re-sent to the provider on every single turn thereafter.
            merged = dict(list(merged.items())[-MAX_FACTS:])
            conn.execute(
                "UPDATE conversations SET facts = ? WHERE id = ?",
                (_dump(merged), row["id"]),
            )
        return merged

    def facts_for_llm(self, principal: Principal, conversation_id: str) -> dict[str, Any]:
        with self._lock, self._db() as conn:
            row = self._owned(conn, principal, conversation_id)
        return dict(_load(row["facts"]) or {})

    def history_for_llm(
        self, principal: Principal, conversation_id: str, *, max_turns: int = DEFAULT_HISTORY_TURNS
    ) -> TurnList:
        """The last few turns in the shape ``llm.interpreter.interpret`` expects."""
        max_turns = max(0, min(MAX_HISTORY_TURNS, int(max_turns or 0)))
        if not max_turns:
            return []
        with self._lock, self._db() as conn:
            self._owned(conn, principal, conversation_id)
            rows = conn.execute(
                "SELECT role, text FROM turns WHERE conversation_id = ?"
                " ORDER BY seq DESC LIMIT ?",
                (conversation_id, max_turns),
            ).fetchall()
        return [{"role": r["role"], "content": r["text"]} for r in reversed(rows)]

    # ---- housekeeping ----------------------------------------------------

    def purge_tombstones(self, *, older_than_seconds: int = TOMBSTONE_SECONDS) -> int:
        cutoff = time.time() - max(0, int(older_than_seconds))
        with self._lock, self._db() as conn:
            cursor = conn.execute(
                "DELETE FROM conversations WHERE deleted_at IS NOT NULL AND deleted_at < ?",
                (cutoff,),
            )
            return int(cursor.rowcount or 0)


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _new_id(prefix: str = "conv") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


def _mode(value: Any) -> str:
    """Validate on the way IN, be forgiving on the way out.

    Storing an unknown mode is refused because the stored value is what a later
    turn will run in — a typo written today becomes silently wrong answers
    tomorrow. `modes.get()` is deliberately forgiving in the opposite direction,
    for a value that is already stored or already in flight.

    A retired id is accepted and stored as its replacement, never as itself, so
    the rows migrate as they are touched instead of accumulating two spellings
    of the same mode.
    """
    mode = mode_registry.canonical(value or DEFAULT_MODE)
    if not mode_registry.is_known(mode):
        known = ", ".join(m.id for m in mode_registry.all_modes())
        raise InvalidMode(f"mode must be one of {known}")
    return mode


def _title(value: Any, *, allow_empty: bool = True) -> str:
    title = " ".join(str(value or "").split())[:MAX_TITLE_CHARS]
    if not title and not allow_empty:
        raise ConversationError("A title is required.")
    return title


def _clip(value: Any, limit: int) -> str:
    text = str(value or "")
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _page(value: Any, default: int = DEFAULT_PAGE) -> int:
    return max(1, min(MAX_PAGE, _int(value, default) or default))


def _ids(values: Any) -> list[Any] | None:
    """Keep identifiers only, and only a bounded number of them.

    Callers pass whatever a tool returned. Anything that is not a scalar id is
    dropped rather than stored, because a dict here is a patient record and the
    point of saving ids is to avoid keeping one.
    """
    if not isinstance(values, (list, tuple)):
        return None
    kept = [v for v in values if isinstance(v, (str, int)) and str(v).strip()]
    return kept[:MAX_RESULT_IDS] or None


def _dump(value: Any) -> str | None:
    if value in (None, {}, []):
        return None
    try:
        return json.dumps(value, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return None


def _load(value: Any) -> Any:
    if not value:
        return None
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return None


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    from datetime import datetime, timezone

    return datetime.fromtimestamp(float(value), timezone.utc).isoformat()


def _conversation_dict(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "title": row["title"],
        "mode": row["mode"],
        "createdAt": _iso(row["created_at"]),
        "updatedAt": _iso(row["updated_at"]),
        "archivedAt": _iso(row.get("archived_at")),
        "deletedAt": _iso(row.get("deleted_at")),
        "archived": row.get("archived_at") is not None,
        "deleted": row.get("deleted_at") is not None,
        "turnCount": int(row.get("turn_count") or 0),
        "revision": int(row.get("revision") or 0),
    }


def _turn_dict(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "conversationId": row["conversation_id"],
        "seq": int(row["seq"]),
        "role": row["role"],
        "text": row["text"],
        "tool": row.get("tool"),
        "arguments": _load(row.get("arguments")),
        "resultIds": _load(row.get("result_ids")),
        "resultCount": row.get("result_count"),
        "requestId": row.get("request_id") or "",
        "auditId": row.get("audit_id"),
        "createdAt": _iso(row["created_at"]),
    }


def _analysis_dict(
    row: dict[str, Any], artifacts: list[dict[str, Any]]
) -> dict[str, Any]:
    return {
        "id": row["id"],
        "conversationId": row["conversation_id"],
        "turnId": row["turn_id"],
        "requestId": row.get("request_id") or "",
        "tool": row.get("tool"),
        "status": row.get("status") or "ok",
        "storedOnServer": True,
        "createdAt": _iso(row["created_at"]),
        "artifacts": artifacts,
    }


def _artifact_dict(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "kind": row["kind"],
        "name": row["display_name"],
        "format": row["format"],
        "mimeType": row["mime_type"],
        "sizeBytes": int(row.get("size_bytes") or 0),
        "rowCount": row.get("row_count"),
        "sha256": row.get("sha256") or None,
        "complete": bool(row.get("complete")),
        "available": True,
    }


def _artifact_from_file(item: ArtifactFile) -> dict[str, Any]:
    return {
        "id": item.id,
        "kind": item.kind,
        "name": item.display_name,
        "format": item.format,
        "mimeType": item.mime_type,
        "sizeBytes": item.size_bytes,
        "rowCount": item.row_count,
        "sha256": item.sha256 or None,
        "complete": item.complete,
        "available": True,
    }


_DEFAULT: ConversationStore | None = None
_DEFAULT_LOCK = threading.Lock()


def default_store(data_root: Path | str | None = None) -> ConversationStore:
    """One store per process, rooted at the configured data folder."""
    global _DEFAULT
    if data_root is not None:
        return ConversationStore(data_root)
    with _DEFAULT_LOCK:
        if _DEFAULT is None:
            from ..runtime import data_root as configured_root

            _DEFAULT = ConversationStore(configured_root())
        return _DEFAULT
