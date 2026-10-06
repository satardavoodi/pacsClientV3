"""Bounded center-scoped case reads and socket-backed broadcast invalidations.

Each server instance has one configured PACS source. Membership is server-owned;
clinical content is fetched separately, never placed in the event ring.
"""
from collections import deque, OrderedDict
import json
import re
import threading
import time
import uuid
import urllib.parse

from .text_history import request_id
from .contracts import case_reference


class Events:
    def __init__(self, capacity=256):
        self.condition = threading.Condition()
        self.epoch = uuid.uuid4().hex
        self.revision = 0
        self.ring = deque(maxlen=capacity)
        self.slots = threading.BoundedSemaphore(64)
        self.closed = False

    def cursor(self):
        with self.condition:
            return {'epoch': self.epoch, 'revision': self.revision}

    def publish(self, study_uid, resource):
        if resource not in ('echomind', 'eagle_eye', 'workflow'):
            raise ValueError('Invalid resource kind.')
        with self.condition:
            self.revision += 1
            self.ring.append((self.revision, study_uid))
            self.condition.notify_all()

    def wait(self, cursor, study_uid, timeout=15):
        if (not isinstance(cursor, dict) or set(cursor) != {'epoch', 'revision'}
                or not isinstance(cursor['epoch'], str) or len(cursor['epoch']) > 64
                or type(cursor['revision']) is not int or cursor['revision'] < 0):
            raise ValueError('Invalid event cursor.')
        if not self.slots.acquire(blocking=False):
            raise BlockingIOError('Event reader limit reached.')
        try:
            deadline = time.monotonic() + min(max(timeout, 0), 15)
            with self.condition:
                while True:
                    revision = cursor['revision']
                    overflow = bool(self.ring and revision < self.ring[0][0] - 1)
                    changed = (cursor['epoch'] != self.epoch or revision > self.revision
                        or overflow or any(r > revision and (not uid or uid == study_uid)
                                           for r, uid in self.ring))
                    remaining = deadline - time.monotonic()
                    if changed or remaining <= 0 or self.closed:
                        return dict(epoch=self.epoch, revision=self.revision, changed=changed)
                    self.condition.wait(remaining)
        finally:
            self.slots.release()

    def close(self):
        with self.condition:
            self.closed = True
            self.condition.notify_all()


class CaseService:
    def __init__(self, jobs, history, memberships, center):
        if not isinstance(center, str) or not center or len(center) > 128:
            raise ValueError('Invalid server center.')
        if not all(isinstance(k, str) and isinstance(v, str) and v for k, v in memberships.items()):
            raise ValueError('Invalid center memberships.')
        self.jobs, self.history = jobs, history
        self.memberships, self.center = dict(memberships), center
        self.events = Events()
        self.lock = threading.Lock()
        self.watched = OrderedDict()
        self.workflow = {}
        self.workflow_seen = {}

    def authorize(self, owner, reference):
        case = case_reference(reference)
        if self.memberships.get(owner) != self.center:
            raise PermissionError('Case access denied.')
        identity = self.jobs.source.case_identity(case['study_uid'])
        if identity != case:
            raise PermissionError('Case identity changed or access denied.')
        with self.lock:
            self.watched[case['study_uid']] = case['patient_id']
            self.watched.move_to_end(case['study_uid'])
            while len(self.watched) > 100:
                uid, _ = self.watched.popitem(last=False)
                self.workflow.pop(uid, None)
                self.workflow_seen.pop(uid, None)
        return case

    def workflow_update(self, states):
        changed = []
        with self.lock:
            for state in states:
                uid = state['study_uid']
                if self.watched.get(uid) != state['patient_id']:
                    continue
                self.workflow_seen[uid] = time.monotonic()
                if self.workflow.get(uid) != state:
                    self.workflow[uid] = dict(state)
                    changed.append(uid)
        for uid in changed:
            self.events.publish(uid, 'workflow')

    def watch_list(self):
        with self.lock:
            return tuple(self.watched)

    def owners(self):
        return tuple(k for k, v in self.memberships.items() if v == self.center)

    def verify_study(self, owner, uid):
        if self.memberships.get(owner) != self.center:
            raise PermissionError('Case access denied.')
        identity = self.jobs.source.case_identity(uid)
        return self.authorize(owner, identity)

    def snapshot(self, owner, reference, *, offset=0):
        case = self.authorize(owner, reference)
        if type(offset) is not int or not 0 <= offset <= 10000:
            raise ValueError('Invalid history offset.')
        # Capture the cursor BEFORE reads: changes during either read stay dirty.
        cursor = self.events.cursor()
        owners = self.owners()
        with self.jobs.lock:
            rows = sorted((state for state in self.jobs.jobs.values()
                if state['owner'] in owners and state['study_uid'] == case['study_uid']),
                key=lambda s: (s.get('created_at', 0), s['job_id']), reverse=True)
            page = [self.job_metadata(s) for s in rows[offset:offset + 50]]
            completed_rows = [s for s in rows if s['status'] == 'succeeded']
            completed = [self.job_metadata(s) for s in completed_rows[offset:offset + 50]]
        texts = self.history.case_list(owners, case['study_uid'], offset=offset) if self.history else []
        with self.lock:
            workflow = dict(self.workflow.get(case['study_uid'], {}))
            if time.monotonic() - self.workflow_seen.get(case['study_uid'], 0) > 35:
                workflow = {}
        bridge = getattr(self.jobs, 'case_bridge', None)
        workflow_status = bridge.status if bridge else 'connected'
        if workflow_status != 'connected':
            workflow = {}
        source_config = getattr(self.jobs.source, 'config', {})
        host = source_config.get('client_host') or urllib.parse.urlsplit(source_config.get('url', '')).hostname
        return dict(case=case, cursor=cursor, jobs=page, eagle_eye=completed, workflow=workflow,
            workflow_status=workflow_status, pacs_host=host,
            pacs_socket_port=bridge.config.get('socket_port', 50052) if bridge else 50052,
            echomind=texts[:50], more_echomind=len(texts) > 50,
            more_jobs=len(rows) > offset + 50, more_eagle_eye=len(completed_rows) > offset + 50, offset=offset)

    @staticmethod
    def job_metadata(state):
        return {k: state.get(k) for k in ('job_id', 'module', 'study_uid', 'status', 'created_at')}

    def text(self, owner, reference, rid):
        case = self.authorize(owner, reference)
        request_id(rid)
        if not self.history:
            raise KeyError('Saved response unavailable.')
        return self.history.case_result(self.owners(), case['study_uid'], rid)

    def job(self, owner, reference, job_id):
        case = self.authorize(owner, reference)
        if not isinstance(job_id, str) or not re.fullmatch('[a-f0-9]{32}', job_id):
            raise ValueError('Invalid saved job.')
        with self.jobs.lock:
            state = self.jobs.jobs.get(job_id)
            if (not state or state['owner'] not in self.owners()
                    or state['study_uid'] != case['study_uid'] or state['status'] != 'succeeded'):
                raise KeyError('Saved analysis unavailable.')
            request = json.loads((self.jobs.root / job_id / 'request.json').read_text(encoding='utf-8'))
            return {k: v for k, v in state.items() if k not in ('owner', 'fingerprint')}, request

    def wait(self, owner, reference, cursor):
        case = self.authorize(owner, reference)
        value = self.events.wait(cursor, case['study_uid'])
        self.authorize(owner, reference)
        return value
