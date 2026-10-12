"""Dedicated, bounded workflow notifications. No Qt, DB, files or download pool.

Events invalidate a small visible-study snapshot; they never become clinical truth.
V1 snapshots require negotiation; explicit legacy opt-in verifies the held session.
"""
from collections import OrderedDict
import json
import logging
import random
import select
import socket
import threading
import time
import uuid
from .home_legacy_workflow import CompatibilityReadError

EVENTS = ("study_assigned", "report_status_changed", "audio_uploaded", "patient_list_updated", "attachment_uploaded")
BASE_EVENTS = EVENTS[:-1]
MAX_FRAME = 1024 * 1024
MAX_STUDIES = 100
LEGACY_HEARTBEAT_SECONDS = 20
LEGACY_VERIFY_SECONDS = 60


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
        if isinstance(state.get('reporting_physician'), str):
            result[-1]['reporting_physician'] = state['reporting_physician'][:240]
        if type(state.get('assignment_known')) is bool:
            result[-1]['assignment_known'] = state['assignment_known']
        if isinstance(state.get('latest_study_uid'), str) and len(state['latest_study_uid']) <= 64:
            result[-1]['latest_study_uid'] = state['latest_study_uid']
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
        person = next((p for p in people if isinstance(p, dict) and (p.get("id") or p.get("name"))), {})
        local = (current_assignment_details(state["patient_id"]) or {}) if enabled else {}
        state["assignment_enabled"] = enabled or bool(assignment)
        state["display_assignment"] = merge_assignment_status(
            bool(person.get("id") or person.get("name")), str(person.get("name") or ""),
            str(local.get("assignment_status") or ""), str(local.get("assignee_name") or ""))
        if not state["assignment_enabled"]:
            state["display_assignment"] = {}
        if state.get('assignment_known') is False:
            state['assignment_enabled'] = False
            state['display_assignment'] = {}
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
    def __init__(self, host, port, token, *, transform=None, allow_legacy=False,
                 allow_legacy_events=False, enrich=None, invalidate=None):
        super().__init__(name="workflow-events", daemon=True)
        self.address = (host, int(port))
        self.token = token
        self.allow_legacy = allow_legacy
        self.allow_legacy_events = allow_legacy_events
        self.invalidate = invalidate
        self.patient_ids = {}
        self.observation = 0
        self.transform = transform or prepare_display
        self.stopped = threading.Event()
        self.lock = threading.Lock()
        self.watched = ()
        self.mailbox = Mailbox()
        self.sockets = set()
        self.status = "connecting"
        self.failure = None
        self.denied = threading.Event()
        self.legacy_snapshots = None
        self.enrichment = None
        if enrich:
            from .home_live_workflow import EnrichmentWorker
            self.enrichment = EnrichmentWorker(enrich)

    def watch(self, uids):
        with self.lock:
            if isinstance(uids, dict):
                self.patient_ids = {uid: (value[1] if isinstance(value, tuple) else value) for uid, value in uids.items()}
            self.watched = tuple(dict.fromkeys(u for u in uids if isinstance(u, str) and 0 < len(u) <= 64))[:MAX_STUDIES]

    def stop(self):
        self.stopped.set()
        if self.enrichment:
            self.enrichment.stop()
        if self.legacy_snapshots:
            self.legacy_snapshots.stop()
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
            self._deliver(data.get('states'), watched)
        finally:
            self._close(sock)

    def _deliver(self, states, watched, *, voice_only=False):
        if self.stopped.is_set() or self.denied.is_set():
            return
        states = validated_states(states, watched)
        if not voice_only:
            states = self.transform(states)
        with self.lock:
            for state in states:
                self.observation += 1
                state['_observation'] = self.observation
        self.mailbox.publish([dict(state, _voice_only=True) for state in states] if voice_only else states)
        if self.enrichment and states:
            self.enrichment.submit(states)

    def drain_enrichment(self):
        return self.enrichment.drain() if self.enrichment else []

    def _legacy_failed(self, endpoint, error):
        reason = error.reason if isinstance(error, CompatibilityReadError) else (
            'timeout' if isinstance(error, TimeoutError) else
            'transport' if isinstance(error, OSError) else 'invalid_response')
        if reason == 'authorization':
            self.denied.set()
        self._record_failure((endpoint, reason))

    def _legacy_exchange(self, sock, endpoint, params):
        rid = send(sock, endpoint, params, self.token)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            reply = receive(sock, timeout=max(.01, deadline - time.monotonic()))
            if reply.get('type') == 'broadcast':
                if self.legacy_snapshots:
                    self.legacy_snapshots.invalidate(reply.get('data'))
                    if self.invalidate:
                        self.invalidate(reply.get('data'))
                continue
            if reply.get('request_id') != rid:
                raise CompatibilityReadError('correlation')
            return reply
        raise TimeoutError('Legacy control response')

    def _legacy_live(self, sock):
        """Keep the installed event stream; require server-verified session and pong."""
        reply = self._legacy_exchange(sock, 'VerifyToken', {'token':self.token})
        if reply.get('status') != 'success' or reply.get('valid') is not True:
            if 'unknown endpoint' in str(reply.get('error') or '').lower():
                return False
            raise CompatibilityReadError('authorization')
        if self._legacy_exchange(sock, 'ping', {}).get('status') != 'success':
            return False
        from .home_live_workflow import LegacySnapshots
        worker = self.legacy_snapshots = LegacySnapshots(self)
        worker.start()
        self.status = 'connected_legacy'
        last_ping = last_verify = time.monotonic()
        try:
            while not self.stopped.is_set():
                if self.denied.is_set():
                    raise CompatibilityReadError('authorization')
                now = time.monotonic()
                if now - last_verify >= LEGACY_VERIFY_SECONDS:
                    reply = self._legacy_exchange(sock, 'VerifyToken', {'token':self.token})
                    if reply.get('status') != 'success' or reply.get('valid') is not True:
                        raise CompatibilityReadError('authorization')
                    last_verify = time.monotonic()
                if now - last_ping >= LEGACY_HEARTBEAT_SECONDS:
                    if self._legacy_exchange(sock, 'ping', {}).get('status') != 'success':
                        raise ConnectionError('Legacy heartbeat rejected')
                    last_ping = time.monotonic()
                if select.select([sock], [], [], .2)[0]:
                    event = receive(sock)
                    if event.get('type') == 'broadcast':
                        # Older servers send additional mutation event names.
                        worker.invalidate(event.get('data'))
                        if self.invalidate:
                            self.invalidate(event.get('data'))
        finally:
            worker.stop()
            # Receiver thread only: retain ownership through connect/read deadlines.
            # Qt stop stays nonblocking; reconnect cannot orphan an inventory pool.
            worker.join()
            self.legacy_snapshots = None
        return True

    def _legacy_request(self, endpoint, params):
        from .home_legacy_workflow import CompatibilityReadError
        if not self.token:
            raise ValueError('Compatibility reads require the signed-in socket token.')
        sock = self._connect()
        try:
            rid = send(sock, endpoint, params, self.token)
            reply = receive(sock)
            if reply.get('request_id') != rid:
                raise CompatibilityReadError('correlation')
            if reply.get('status') != 'success':
                from .socket_client import _is_sortarray_compat_error
                message = str(reply.get('error') or '').lower()
                reason = 'authorization' if any(word in message for word in
                    ('unauthorized', 'forbidden', 'token', 'authentication', 'permission')) else (
                    'mongo_sortarray' if endpoint == 'GetPatientList' and _is_sortarray_compat_error(reply) else
                    'not_found' if 'not found' in message else 'rejected')
                raise CompatibilityReadError(reason)
            data = reply.get('data') or {}
            if not isinstance(data, dict):
                raise ValueError('Invalid compatibility response.')
            return data
        finally:
            self._close(sock)

    def _legacy_loop(self):
        from .home_legacy_workflow import read_rows, CompatibilityReadError
        next_read = 0.0
        previous = None
        offset = 0
        while not self.stopped.wait(.2):
            with self.lock:
                watched = {uid:self.patient_ids.get(uid, '') for uid in self.watched}
            now = time.monotonic()
            if watched != previous:
                next_read, offset = 0.0, 0
                previous = dict(watched)
            if not watched or now < next_read:
                continue
            batch = dict(list(watched.items())[offset:offset + 20])
            offset = (offset + 20) if offset + 20 < len(watched) else 0
            try:
                failures = []
                def failed(endpoint, error):
                    reason = error.reason if isinstance(error, CompatibilityReadError) else (
                        'timeout' if isinstance(error, TimeoutError) else
                        'transport' if isinstance(error, OSError) else 'invalid_response')
                    failures.append((endpoint, reason))
                states = read_rows(self._legacy_request, batch, stopped=self.stopped.is_set, failed=failed)
                self._deliver(states, batch)
                self.status = 'compatibility_partial' if failures and states else (
                    'compatibility_reconnecting' if failures else 'compatibility')
                self._record_failure(failures[0] if failures else None)
            except (OSError, ValueError, TypeError, KeyError) as error:
                if isinstance(error, CompatibilityReadError) and error.reason == 'authorization':
                    self.status = 'unavailable'
                    self._record_failure(('compatibility', 'authorization'))
                    return
                self.status = 'compatibility_reconnecting'
                self._record_failure(('compatibility', 'transform' if not isinstance(error, OSError) else 'transport'))
            next_read = time.monotonic() + 15

    def _record_failure(self, failure):
        if failure != self.failure:
            self.failure = failure
            if failure:
                logging.getLogger(__name__).warning('Workflow compatibility failure: endpoint=%s reason=%s', *failure)

    def run(self):
        if self.enrichment:
            self.enrichment.start()
        try:
            self._run()
        finally:
            if self.enrichment:
                self.enrichment.stop()
                # Qt switches sources only after this receiver has quiesced.
                # Joining here keeps slow bounded HTTP reads off the GUI thread
                # and prevents one abandoned enrichment worker per search.
                self.enrichment.join()

    def _run(self):
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
                    unsupported = reply.get('request_id') == rid and (
                        reply.get('status') == 'success' and reply.get('data', {}).get('realtime_version') != 1
                        or reply.get('status') == 'error' and any(message in str(reply.get('error', '')).lower() for message in ('unknown endpoint', 'unsupported protocol')))
                    if (self.allow_legacy or self.allow_legacy_events) and unsupported and self.token:
                        if (self.allow_legacy_events and reply.get('status') == 'success'
                                and self._legacy_live(sock)):
                            return
                        if not self.allow_legacy:
                            self.status = 'unavailable'
                            return
                        self._close(sock)
                        sock = None
                        self.status = 'compatibility'
                        self._legacy_loop()
                        return
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
                            if self.invalidate:
                                self.invalidate(data)
            except CompatibilityReadError as error:
                if error.reason == 'authorization':
                    self.status = 'unavailable'
                    self._record_failure(('events', 'authorization'))
                    return
                self.status = 'reconnecting'
            except (OSError, ValueError, TypeError):
                self.status = "reconnecting"
            finally:
                if sock is not None:
                    self._close(sock)
            if self.stopped.wait(backoff + random.random() * 0.25):
                break
            backoff = min(backoff * 2, 30.0)
