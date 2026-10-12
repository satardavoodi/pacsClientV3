"""Worker-only child admission over the existing authenticated resident RPC."""
import hashlib
import threading
import uuid


class ChildIdentityQueue:
    def __init__(self, timeout=8):
        self.timeout = timeout
        self.lock = threading.Lock()
        self.pending = {}

    def request(self, payload):
        from .client import ServerHTTPError
        identifier = uuid.uuid4().hex
        event = threading.Event()
        entry = dict(id=identifier, payload=payload, event=event, result=None, sent=False)
        with self.lock:
            if len(self.pending) >= 4:
                raise ServerHTTPError(429, 'Parent identity requests are busy.')
            self.pending[identifier] = entry
        try:
            if not event.wait(self.timeout):
                raise ServerHTTPError(401, 'The parent application is unavailable. Reopen Advanced Analysis.')
            result = entry['result']
            if not isinstance(result, dict) or result.get('ok') is not True:
                status = result.get('status', 401) if isinstance(result, dict) else 401
                raise ServerHTTPError(status if status in (401, 403, 429, 503) else 401,
                                      'The parent human session is unavailable. Sign in again.')
            return result
        finally:
            with self.lock:
                self.pending.pop(identifier, None)

    def pull(self):
        with self.lock:
            items = []
            for entry in self.pending.values():
                if not entry['sent']:
                    entry['sent'] = True
                    items.append(dict(id=entry['id'], payload=entry['payload']))
            return items

    def reply(self, identifier, result):
        with self.lock:
            entry = self.pending.get(identifier)
            if entry is not None:
                entry['result'] = result
                entry['event'].set()

    def session(self, client):
        from .client import ServerHTTPError
        result = self.request(dict(action='acquire', url=client.url,
            device=hashlib.sha256(client.token.encode()).hexdigest(),
            profile=getattr(client, '_profile_key', None),
            lease=getattr(client, '_parent_lease', None)))
        lease, opaque, principal = (result.get(k) for k in ('lease', 'session', 'principal'))
        if (not isinstance(lease, str) or len(lease) != 32 or
                not isinstance(opaque, str) or not 32 <= len(opaque) <= 256 or
                any(ord(c) < 33 or ord(c) > 126 for c in opaque) or
                not isinstance(principal, str) or not principal):
            raise ServerHTTPError(401, 'Invalid parent human session receipt.')
        client._parent_lease = lease
        client._human_generation = ('parent', lease)
        return opaque, principal, client._human_generation

    def validate(self, lease):
        self.request(dict(action='validate', lease=lease))
