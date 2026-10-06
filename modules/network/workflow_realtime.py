"""Dedicated, bounded workflow notifications. No Qt, DB, files or download pool.

Events invalidate a small visible-study snapshot; they never become clinical truth.
Old servers must explicitly negotiate v1 before any snapshot calls are made.
"""
from collections import OrderedDict
import json
import random
import select
import socket
import threading
import time
import uuid

EVENTS = ("study_assigned", "report_status_changed", "audio_uploaded", "patient_list_updated", "attachment_uploaded")
BASE_EVENTS = EVENTS[:-1]
MAX_FRAME = 1024 * 1024
MAX_STUDIES = 100


def receive(sock, timeout=5.0, *, max_frame=MAX_FRAME):
    deadline = time.monotonic() + timeout
    def exact(size):
        data = bytearray()
        while len(data) < size:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("Workflow frame deadline")
            sock.settimeout(remaining)
            chunk = sock.recv(size - len(data))
            if not chunk:
                raise ConnectionError("Workflow connection closed")
            data.extend(chunk)
        return data
    size = int.from_bytes(exact(4), "big")
    if not 0 < size <= max_frame:
        raise ValueError("Workflow frame exceeds limit")
    value = json.loads(exact(size))
    if not isinstance(value, dict):
        raise ValueError("Invalid workflow frame")
    return value


def send(sock, endpoint, params, token):
    request_id = uuid.uuid4().hex
    data = json.dumps(dict(endpoint=endpoint, params=params, token=token,
                           request_id=request_id)).encode("utf-8")
    sock.settimeout(5)
    sock.sendall(len(data).to_bytes(4, "big") + data)
    return request_id


def validated_states(states, requested):
    if not isinstance(states, list) or len(states) > MAX_STUDIES:
        raise ValueError("Invalid workflow snapshot")
    allowed = set(requested)
    result = []
    for state in states:
        if not isinstance(state, dict) or state.get("study_uid") not in allowed:
            continue
        if not isinstance(state.get("patient_id"), str):
            continue
        status = state.get("report_status")
        assignment = state.get("assignment")
        count = state.get("audio_count")
        if not isinstance(status, str) or not isinstance(assignment, dict):
            continue
        if type(count) is not int or not 0 <= count <= 100000:
            continue
        clean_assignment = {}
        for role in ("radiologist", "typist"):
            person = assignment.get(role)
            if isinstance(person, dict):
                clean_assignment[role] = {k: str(person.get(k) or "")[:240] for k in ("id", "name", "source")}
        result.append(dict(study_uid=state["study_uid"], patient_id=state["patient_id"],
                           report_status=status[:80], assignment=clean_assignment, audio_count=count))
        for key, limit in (('image_count', 10000000), ('series_count', 100000)):
            if type(state.get(key)) is int and 0 <= state[key] <= limit:
                result[-1][key] = state[key]
        revision = state.get('attachment_revision')
        if type(state.get('legacy_audio')) is bool:
            result[-1]['legacy_audio'] = state['legacy_audio']
        documents = state.get('document_count')
        if (isinstance(revision, str) and len(revision) == 64
                and all(c in '0123456789abcdef' for c in revision)
                and type(documents) is int and 0 <= documents <= 100000):
            result[-1].update(attachment_revision=revision, document_count=documents)
    return result


def prepare_display(states):
    """Read local lifecycle overlays on the worker, never during a Qt repaint."""
    from modules.network.ino_assignment_history import current_assignment_details
    from modules.network.ino_assignment_models import merge_assignment_status
    from modules.network.ino_assignment import is_enabled
    enabled = is_enabled()
    for state in states:
        assignment = state["assignment"]
        people = [assignment.get(role) for role in ("radiologist", "typist")]
        person = next((p for p in people if isinstance(p, dict) and p.get("id")), {})
        local = (current_assignment_details(state["patient_id"]) or {}) if enabled else {}
        state["assignment_enabled"] = enabled
        state["display_assignment"] = merge_assignment_status(
            bool(person.get("id")), str(person.get("name") or ""),
            str(local.get("assignment_status") or ""), str(local.get("assignee_name") or ""))
        if not enabled:
            state["display_assignment"] = {}
    return states


class Mailbox:
    """Last value per UID; a slow GUI never accumulates an unbounded signal queue."""
    def __init__(self):
        self.lock = threading.Lock()
        self.states = OrderedDict()

    def publish(self, states):
        with self.lock:
            for state in states:
                key = state["study_uid"]
                self.states[key] = state
                self.states.move_to_end(key)
                while len(self.states) > MAX_STUDIES:
                    self.states.popitem(last=False)

    def drain(self):
        with self.lock:
            result = list(self.states.values())
            self.states.clear()
        return result


class WorkflowReceiver(threading.Thread):
    def __init__(self, host, port, token, *, transform=None):
        super().__init__(name="workflow-events", daemon=True)
        self.address = (host, int(port))
        self.token = token
        self.transform = transform or prepare_display
        self.stopped = threading.Event()
        self.lock = threading.Lock()
        self.watched = ()
        self.mailbox = Mailbox()
        self.sockets = set()
        self.status = "connecting"

    def watch(self, uids):
        with self.lock:
            self.watched = tuple(dict.fromkeys(u for u in uids if isinstance(u, str) and 0 < len(u) <= 64))[:MAX_STUDIES]

    def stop(self):
        self.stopped.set()
        with self.lock:
            sockets = tuple(self.sockets)
        for sock in sockets:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            sock.close()

    def _connect(self):
        sock = socket.create_connection(self.address, timeout=5)
        with self.lock:
            if self.stopped.is_set():
                sock.close()
                raise ConnectionError("Stopped")
            self.sockets.add(sock)
        return sock

    def _close(self, sock):
        with self.lock:
            self.sockets.discard(sock)
        sock.close()

    def _snapshot(self, watched):
        sock = self._connect()
        try:
            rid = send(sock, "GetWorkflowStates", {"study_uids": list(watched)}, self.token)
            reply = receive(sock)
            if reply.get("request_id") != rid or reply.get("status") != "success":
                raise ValueError("Workflow snapshot rejected")
            data = reply.get("data", {})
            if data.get("realtime_version") != 1:
                raise ValueError("Workflow snapshot version")
            self.mailbox.publish(self.transform(validated_states(data.get("states"), watched)))
        finally:
            self._close(sock)

    def run(self):
        backoff = 1.0
        while not self.stopped.is_set():
            sock = None
            try:
                sock = self._connect()
                rid = send(sock, "SubscribeToEvents", {"protocol_version": 1, "event_types": list(EVENTS)}, self.token)
                reply = receive(sock)
                if reply.get('request_id') == rid and reply.get('status') == 'error':
                    # Older v1 servers do not advertise document invalidations.
                    # One bounded retry preserves their existing voice/status path.
                    rid = send(sock, 'SubscribeToEvents', {'protocol_version': 1,
                        'event_types': list(BASE_EVENTS)}, self.token)
                    reply = receive(sock)
                if reply.get("request_id") != rid or reply.get("status") != "success" or reply.get("data", {}).get("realtime_version") != 1:
                    self.status = "unavailable"
                    # No repeated probe load on an old or unauthorized server.
                    return
                self.status = "connected"
                backoff = 1.0
                dirty = True
                last_snapshot = 0.0
                last_ping = time.monotonic()
                pending_ping = None
                previous_watch = ()
                while not self.stopped.is_set():
                    with self.lock:
                        watched = self.watched
                    now = time.monotonic()
                    dirty |= watched != previous_watch
                    previous_watch = watched
                    if watched and now - last_snapshot >= 1.0 and (dirty or now - last_snapshot >= 30):
                        self._snapshot(watched)
                        last_snapshot = time.monotonic()
                        dirty = False
                    if pending_ping and now - last_ping > 10:
                        raise TimeoutError("Workflow heartbeat")
                    if not pending_ping and now - last_ping >= 20:
                        pending_ping = send(sock, "ping", {}, self.token)
                        last_ping = now
                    if not select.select([sock], [], [], 0.2)[0]:
                        continue
                    event = receive(sock)
                    if event.get("request_id") == pending_ping:
                        pending_ping = None
                    if event.get("type") == "broadcast" and event.get("event_type") in EVENTS:
                        # Burst coalescing: one dirty bit, not one request per event.
                        data = event.get("data") or {}
                        uid = data.get("study_uid") if isinstance(data, dict) else None
                        if not uid or uid in watched:
                            dirty = True
            except (OSError, ValueError, TypeError):
                self.status = "reconnecting"
            finally:
                if sock is not None:
                    self._close(sock)
            if self.stopped.wait(backoff + random.random() * 0.25):
                break
            backoff = min(backoff * 2, 30.0)
