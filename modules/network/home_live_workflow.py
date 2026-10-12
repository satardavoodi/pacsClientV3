"""Bounded Home workers: event reconciliation never waits for REST enrichment."""
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import OrderedDict
import threading
import time


class EnrichmentWorker(threading.Thread):
    def __init__(self, transform):
        super().__init__(name='workflow-enrichment', daemon=True)
        self.transform = transform
        self.stopped = threading.Event()
        self.wake = threading.Event()
        self.lock = threading.Lock()
        self.pending, self.results, self.versions = OrderedDict(), OrderedDict(), {}
        self.serial = 0

    def submit(self, states):
        with self.lock:
            for state in states:
                uid = state['study_uid']
                self.serial += 1
                self.versions[uid] = self.serial
                self.pending[uid] = (self.serial, dict(state))
                self.pending.move_to_end(uid)
                while len(self.pending) > 100:
                    dropped, _ = self.pending.popitem(last=False)
                    self.versions.pop(dropped, None)
                while len(self.versions) > 100:
                    self.versions.pop(next(iter(self.versions)))
        self.wake.set()

    def stop(self):
        self.stopped.set()
        self.wake.set()

    def drain(self):
        with self.lock:
            states = [state for uid, (version, state) in self.results.items()
                      if self.versions.get(uid) == version]
            self.results.clear()
        return states

    def run(self):
        while not self.stopped.is_set():
            self.wake.wait(.2)
            with self.lock:
                if not self.pending:
                    self.wake.clear()
                    continue
                uid, (version, state) = self.pending.popitem(last=True)
            try:
                result = self.transform([state])
            except Exception:
                # Optional enrichment cannot terminate or block the event reader.
                continue
            if self.stopped.is_set():
                break
            with self.lock:
                if self.versions.get(uid) != version:
                    continue
                for row in result:
                    if row.get('study_uid') == uid and row.get('patient_id') == state['patient_id']:
                        row = dict(row, _report_only=True)
                        self.results[uid] = (version, row)
                        while len(self.results) > 100:
                            self.results.popitem(last=False)


class LegacySnapshots(threading.Thread):
    """Four bounded inventory reads; stream completed patients immediately."""
    def __init__(self, receiver):
        super().__init__(name='workflow-legacy-snapshots', daemon=True)
        self.receiver = receiver
        self.stopped = threading.Event()
        self.wake = threading.Event()
        self.lock = threading.Lock()
        self.dirty = set()
        self.full = True

    def invalidate(self, data):
        with self.receiver.lock:
            watched = dict(self.receiver.patient_ids)
        uid = data.get('study_uid') if isinstance(data, dict) else None
        pid = data.get('patient_id') if isinstance(data, dict) else None
        with self.lock:
            if uid:
                if uid in watched:
                    self.dirty.add(uid)
            elif pid:
                self.dirty.update(key for key, value in watched.items() if value == pid)
            else:
                self.full = True
        self.wake.set()

    def stop(self):
        self.stopped.set()
        self.wake.set()

    def _read(self, watched):
        from .home_legacy_workflow import read_rows
        return read_rows(self.receiver._legacy_request, watched,
                         stopped=self.stopped.is_set, inventory_only=True,
                         failed=self.receiver._legacy_failed)

    def run(self):
        previous = {}
        next_reconcile = 0.0
        with ThreadPoolExecutor(max_workers=4, thread_name_prefix='workflow-inventory') as pool:
            while not self.stopped.is_set():
                self.wake.wait(.1)
                self.wake.clear()
                if self.stopped.wait(.1):
                    break  # Coalesce a mutation burst before scheduling bounded reads.
                with self.receiver.lock:
                    watched = {uid:self.receiver.patient_ids.get(uid, '') for uid in self.receiver.watched}
                with self.lock:
                    full = self.full or watched != previous or time.monotonic() >= next_reconcile
                    selected = watched if full else {uid:watched[uid] for uid in self.dirty if uid in watched}
                    self.dirty.clear()
                    self.full = False
                previous = watched
                if not selected:
                    continue
                groups = {}
                for uid, pid in selected.items():
                    groups.setdefault(pid, {})[uid] = pid
                futures = [pool.submit(self._read, group) for group in groups.values()]
                for future in as_completed(futures):
                    if self.stopped.is_set():
                        for pending in futures:
                            pending.cancel()
                        break
                    try:
                        states = future.result()
                    except Exception as error:
                        self.receiver._legacy_failed('inventory', error)
                        continue
                    with self.receiver.lock:
                        current = dict(self.receiver.patient_ids)
                    states = [state for state in states if current.get(state['study_uid']) == state['patient_id']]
                    self.receiver._deliver(states, current, voice_only=bool(self.receiver.enrichment))
                next_reconcile = time.monotonic() + 30
