"""Reception sessions over the existing paired Eagle Eye connection."""
import json
from ..client import Client


class CRMClient:
    def __init__(self, settings=None):
        self.server = Client(settings)
        self.session = ''

    def request(self, operation, body=None):
        with self.server.open('/v1/crm/' + operation, body, timeout=190,
                              extra_headers={'X-CRM-Session': self.session}) as response:
            raw = response.read(8 * 1024 * 1024 + 1)
            if len(raw) > 8 * 1024 * 1024:
                raise ValueError('CRM response exceeds the transport budget.')
            return json.loads(raw)

    def login(self, username, password):
        self.session = ''
        result = self.request('session', {'username': username, 'password': password})
        if not result.get('accessToken'):
            raise ValueError('Reception sign-in was not accepted.')
        self.session = result['accessToken']
        return result
