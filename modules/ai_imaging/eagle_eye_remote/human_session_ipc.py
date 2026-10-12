"""Parent-owned human leases for resident Slicer; credentials never cross IPC."""
import hashlib
import time
import uuid

from . import user_session
from .client import Client, ServerHTTPError


class HumanSessionBroker:
    def __init__(self, client_factory=Client, ttl=3600):
        self.client_factory = client_factory
        self.ttl = ttl
        self.leases = {}

    def close(self):
        self.leases.clear()

    def _lease(self, identifier):
        value = self.leases.get(identifier)
        if value is None or value['deadline'] <= time.monotonic():
            raise ServerHTTPError(401, 'Parent human lease expired.')
        connection = value['client']
        connection._check_profile()
        user_session.require_generation(value['generation'])
        user_session.confirmed_admission(connection)
        value['deadline'] = time.monotonic() + self.ttl
        return value

    def handle(self, request):
        try:
            if not isinstance(request, dict):
                raise ValueError('Invalid identity request')
            action = request.get('action')
            if action == 'validate' and set(request) == {'action', 'lease'}:
                self._lease(request['lease'])
                return dict(ok=True)
            if action != 'acquire' or set(request) != {'action', 'url', 'device', 'profile', 'lease'}:
                raise ValueError('Invalid identity request')
            identifier = request['lease']
            value = self._lease(identifier) if identifier is not None else None
            connection = value['client'] if value else self.client_factory()
            if (request['url'] != connection.url or request['profile'] != connection._profile_key or
                    request['device'] != hashlib.sha256(connection.token.encode()).hexdigest()):
                raise ValueError('Mismatched parent connection')
            opaque, principal, generation = user_session.session(connection)
            if value is None:
                self.leases = {key: item for key, item in self.leases.items()
                               if item['deadline'] > time.monotonic()}
                if len(self.leases) >= 64:
                    raise ServerHTTPError(429, 'Parent human leases are busy.')
                identifier = uuid.uuid4().hex
                self.leases[identifier] = dict(client=connection, generation=generation,
                                              deadline=time.monotonic() + self.ttl)
            return dict(ok=True, session=opaque, principal=principal, lease=identifier)
        except ServerHTTPError as exc:
            return dict(ok=False, status=exc.status if exc.status in (401, 403, 429, 503) else 401)
        except Exception:
            return dict(ok=False, status=401)
