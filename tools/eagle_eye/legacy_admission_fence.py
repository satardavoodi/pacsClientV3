"""Reversible admission fence for the pre-drain Eagle Eye Server revision.

This module does not stop services, switch revisions, inspect clinical records, or
decide that a server is idle.  It temporarily disables existing Eagle Eye grants
and requires a trusted caller-supplied activity observation before invoking a
transition.  The exact grants are held in a private crash-recovery snapshot and
are restored after success or failure.
"""
from contextlib import closing
from dataclasses import dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import secrets
import time


GRANT_KEYS = ("enabled", "echomind", "imaging", "crm", "secretary", "modules")
SNAPSHOT_VERSION = 1
DPAPI_MAGIC = b"AIPACS-LEGACY-FENCE-DPAPI-V1\n"
PLAIN_MAGIC = b"AIPACS-LEGACY-FENCE-PRIVATE-V1\n"


class FenceError(RuntimeError):
    """The legacy admission fence could not be applied or verified safely."""


class GrantDrift(FenceError):
    """A grant changed while the transition fence was active."""


class DrainTimeout(FenceError):
    """Accepted work did not reach an observed stable idle state in time."""


class CompletionUncertain(FenceError):
    """The activity observer cannot certify completion of accepted work."""


@dataclass(frozen=True)
class ActivitySnapshot:
    """Non-sensitive aggregate evidence supplied by a trusted host observer."""

    active_handlers: int = 0
    active_jobs: int = 0
    active_sockets: int = 0
    completion_uncertain: bool = False

    def __post_init__(self):
        for value in (self.active_handlers, self.active_jobs, self.active_sockets):
            if type(value) is not int or value < 0:
                raise ValueError("Activity counts must be non-negative integers.")
        if type(self.completion_uncertain) is not bool:
            raise ValueError("Completion uncertainty must be boolean.")

    @property
    def idle(self):
        return not (
            self.active_handlers
            or self.active_jobs
            or self.active_sockets
            or self.completion_uncertain
        )


def _grant(row):
    modules = row["modules"]
    if isinstance(modules, str):
        modules = json.loads(modules)
    return {
        "enabled": bool(row["enabled"]),
        "echomind": bool(row["echomind"]),
        "imaging": bool(row["imaging"]),
        "crm": bool(row["crm"]),
        "secretary": bool(row["secretary"]),
        "modules": list(modules),
    }


def _disabled(grant):
    return {**grant, "enabled": False}


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def _store_fingerprint(store):
    return hashlib.sha256(str(store.path.resolve()).encode()).hexdigest()


def _seal(raw):
    if os.name == "nt":
        try:
            import win32crypt
        except ImportError as error:
            raise FenceError("Windows grant snapshots require DPAPI support.") from error
        return DPAPI_MAGIC + win32crypt.CryptProtectData(
            raw, "AI-PACS legacy admission fence", None, None, None, 0
        )
    return PLAIN_MAGIC + raw


def _unseal(raw):
    if raw.startswith(DPAPI_MAGIC):
        if os.name != "nt":
            raise FenceError("This grant snapshot belongs to a Windows account.")
        try:
            import win32crypt
            return win32crypt.CryptUnprotectData(
                raw[len(DPAPI_MAGIC):], None, None, None, 0
            )[1]
        except Exception as error:
            raise FenceError("The private grant snapshot cannot be decrypted.") from error
    if raw.startswith(PLAIN_MAGIC) and os.name != "nt":
        return raw[len(PLAIN_MAGIC):]
    raise FenceError("The private grant snapshot format is invalid.")


def _write_snapshot(path, payload):
    path = Path(path)
    if not path.is_absolute():
        raise ValueError("The private snapshot path must be absolute.")
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise FenceError("The private snapshot path cannot be a symbolic link.")
    raw = _seal(_canonical(payload))
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as error:
        raise FenceError("A previous transition snapshot requires recovery first.") from error
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def _read_snapshot(path):
    path = Path(path)
    try:
        payload = json.loads(_unseal(path.read_bytes()))
    except FenceError:
        raise
    except Exception as error:
        raise FenceError("The private grant snapshot is unreadable.") from error
    checksum = payload.pop("checksum", None)
    if not isinstance(checksum, str) or not secrets.compare_digest(
        checksum, hashlib.sha256(_canonical(payload)).hexdigest()
    ):
        raise FenceError("The private grant snapshot failed its integrity check.")
    if payload.get("version") != SNAPSHOT_VERSION or not isinstance(payload.get("users"), list):
        raise FenceError("The private grant snapshot contract is unsupported.")
    return payload


def _row_grant(db, principal):
    row = db.execute(
        "SELECT enabled,echomind,imaging,crm,secretary,modules FROM users WHERE principal=?",
        (principal,),
    ).fetchone()
    if row is None:
        raise GrantDrift("A fenced Eagle Eye identity no longer exists.")
    return _grant(row)


def _apply_batch(store, expected, replacement, actor):
    """Compare and update every grant in one SQLite write transaction."""
    if not isinstance(actor, str) or not actor or len(actor) > 128:
        raise ValueError("A bounded transition actor is required.")
    with closing(store.connect()) as db, db:
        db.execute("BEGIN IMMEDIATE")
        for principal, value in expected.items():
            if _row_grant(db, principal) != value:
                raise GrantDrift("An Eagle Eye grant changed during the transition.")
        for principal, value in replacement.items():
            db.execute(
                """UPDATE users SET enabled=?,echomind=?,imaging=?,crm=?,secretary=?,modules=?
                   WHERE principal=?""",
                tuple(int(value[key]) for key in GRANT_KEYS[:-1])
                + (json.dumps(value["modules"]), principal),
            )
            db.execute(
                "INSERT INTO events VALUES (?,?,?,?,?,?)",
                (
                    secrets.token_hex(16),
                    principal,
                    actor,
                    "grant_changed",
                    json.dumps(value, sort_keys=True),
                    time.time(),
                ),
            )


def _snapshot_payload(store, original, fenced):
    payload = {
        "version": SNAPSHOT_VERSION,
        "center_sha256": hashlib.sha256(store.center.encode()).hexdigest(),
        "store_sha256": _store_fingerprint(store),
        "users": [
            {"principal": principal, "original": original[principal], "fenced": fenced[principal]}
            for principal in sorted(original)
        ],
    }
    payload["checksum"] = hashlib.sha256(_canonical(payload)).hexdigest()
    return payload


def _validate_snapshot_for_store(store, payload):
    if not secrets.compare_digest(
        payload.get("center_sha256", ""), hashlib.sha256(store.center.encode()).hexdigest()
    ) or not secrets.compare_digest(payload.get("store_sha256", ""), _store_fingerprint(store)):
        raise FenceError("The private grant snapshot belongs to another server store.")
    original = {}
    fenced = {}
    for item in payload["users"]:
        if set(item) != {"principal", "original", "fenced"}:
            raise FenceError("The private grant snapshot contains invalid fields.")
        principal = item["principal"]
        if not isinstance(principal, str) or len(principal) != 64:
            raise FenceError("The private grant snapshot contains an invalid identity.")
        if set(item["original"]) != set(GRANT_KEYS) or set(item["fenced"]) != set(GRANT_KEYS):
            raise FenceError("The private grant snapshot contains an invalid grant.")
        original[principal] = item["original"]
        fenced[principal] = item["fenced"]
    return original, fenced


class LegacyGrantFence:
    """Temporarily deny every currently enabled Eagle Eye human grant."""

    def __init__(self, store, snapshot_path, *, actor):
        self.store = store
        self.snapshot_path = Path(snapshot_path)
        self.actor = actor
        self.active = False

    def disable(self):
        if self.active:
            raise FenceError("This transition fence is already active.")
        rows = self.store.users()
        original = {row["principal"]: _grant(row) for row in rows if row["enabled"]}
        fenced = {principal: _disabled(value) for principal, value in original.items()}
        payload = _snapshot_payload(self.store, original, fenced)
        _write_snapshot(self.snapshot_path, payload)
        try:
            _apply_batch(self.store, original, fenced, self.actor)
        except BaseException:
            self.snapshot_path.unlink(missing_ok=True)
            raise
        self.active = True
        try:
            self.assert_fenced()
        except BaseException:
            self.restore()
            raise
        return len(original)

    def assert_fenced(self):
        if not self.active:
            raise FenceError("The transition fence is not active.")
        if any(row["enabled"] for row in self.store.users()):
            raise GrantDrift("An Eagle Eye grant became enabled during the transition.")
        return True

    def restore(self):
        if not self.active and not self.snapshot_path.exists():
            return False
        restore_from_snapshot(self.store, self.snapshot_path, actor=self.actor + ".restore")
        self.active = False
        return True


def restore_from_snapshot(store, snapshot_path, *, actor):
    """Recover exact grants after controller interruption without exposing identities."""
    path = Path(snapshot_path)
    payload = _read_snapshot(path)
    original, fenced = _validate_snapshot_for_store(store, payload)
    _apply_batch(store, fenced, original, actor)
    path.unlink()
    return len(original)


def _bounded_seconds(value, name, *, maximum=600):
    if type(value) not in (int, float) or not math.isfinite(value) or not 0 < value <= maximum:
        raise ValueError(f"{name} must be finite and between 0 and {maximum} seconds.")
    return float(value)


def wait_for_stable_idle(fence, observe, *, timeout, settle, poll):
    """Require repeated idle observations after the grant fence is fully applied."""
    timeout = _bounded_seconds(timeout, "timeout")
    settle = _bounded_seconds(settle, "settle", maximum=timeout)
    poll = _bounded_seconds(poll, "poll", maximum=timeout)
    deadline = time.monotonic() + timeout
    idle_since = None
    idle_samples = 0
    while True:
        fence.assert_fenced()
        observed = observe()
        if not isinstance(observed, ActivitySnapshot):
            raise TypeError("The activity observer must return ActivitySnapshot.")
        now = time.monotonic()
        if observed.completion_uncertain:
            idle_since = None
            idle_samples = 0
            if now >= deadline:
                raise CompletionUncertain("Accepted work completion remained uncertain.")
            time.sleep(min(poll, max(0.001, deadline - now)))
            continue
        if observed.idle:
            if idle_since is None:
                idle_since = now
                idle_samples = 1
            else:
                idle_samples += 1
            if idle_samples >= 2 and now - idle_since >= settle:
                fence.assert_fenced()
                return observed
        else:
            idle_since = None
            idle_samples = 0
        if now >= deadline:
            raise DrainTimeout("Accepted work did not reach stable idle before timeout.")
        time.sleep(min(poll, max(0.001, deadline - now)))


def run_fenced_transition(fence, *, observe, transition, timeout, settle, poll=0.25):
    """Fence, drain, transition, and restore grants on every controlled exit."""
    if not callable(observe) or not callable(transition):
        raise TypeError("Activity observation and transition callbacks are required.")
    fence.disable()
    try:
        wait_for_stable_idle(
            fence, observe, timeout=timeout, settle=settle, poll=poll
        )
        fence.assert_fenced()
        return transition()
    finally:
        fence.restore()
