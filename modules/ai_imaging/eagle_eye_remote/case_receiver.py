"""Worker-owned case broadcasts, with a one-value mailbox and bounded retries."""
import json
import threading
import time
import urllib.parse

from .client import Client
from .contracts import case_reference
from .settings import client_settings


class CaseReceiver(threading.Thread):
    def __init__(self, reference, *, settings=None, pacs_host=None):
        super().__init__(name='PatientCaseEvents', daemon=True)
        self.reference = case_reference(reference)
        self.settings = settings
        self.pacs_host = pacs_host
        self.stopped = threading.Event()
        self.lock = threading.Lock()
        self.latest = None
        self.connection = None

    def stop(self):
        self.stopped.set()

    def publish(self, state, *, connection=None):
        with self.lock:
            self.latest = state
            self.connection = connection

    def drain(self):
        with self.lock:
            value = self.latest
            self.latest = None
            return value

    def run(self):
        backoff = 1
        while not self.stopped.is_set():
            try:
                cfg = self.settings if self.settings is not None else client_settings()
                if not cfg.get('url'):
                    self.publish({'status': 'not_configured', 'case': self.reference})
                    return
                client = Client(cfg)
                if self.pacs_host is None:
                    from PacsClient.utils.server_profiles import get_active_profile
                    profile = get_active_profile()
                    if not profile:
                        raise ValueError('Select a PACS source profile.')
                    expected_host = profile.host
                    client.case_profile_id = profile.id
                    client.case_socket_port = profile.socket_port
                    client.case_pacs_host = profile.host
                else:
                    expected_host = self.pacs_host
                capabilities = client.json('/v1/capabilities').get('case_realtime') or {}
                if capabilities.get('version') != 1:
                    self.publish({'status': 'unavailable', 'case': self.reference})
                    return
                snapshot = client.case_snapshot(self.reference)
                server_host = urllib.parse.urlsplit(client.url).hostname
                self.validate(snapshot, expected_host, server_host)
                if self.pacs_host is None:
                    snapshot['pacs_socket_port'] = client.case_socket_port
                self.require_configuration(client, cfg)
                self.publish(dict(snapshot, status='connected'), connection=client)
                backoff = 1
                cursor = snapshot['cursor']
                last_read = time.monotonic()
                while not self.stopped.is_set():
                    event = client.case_events(self.reference, cursor)
                    if self.stopped.is_set():
                        return
                    if self.settings is None:
                        current = get_active_profile()
                        if (cfg != client_settings() or not current or current.host != expected_host
                                or current.id != client.case_profile_id or current.socket_port != client.case_socket_port):
                            raise ValueError('Case source configuration changed.')
                    if event['changed'] or time.monotonic() - last_read >= 30:
                        snapshot = client.case_snapshot(self.reference)
                        self.validate(snapshot, expected_host, server_host)
                        if self.pacs_host is None:
                            snapshot['pacs_socket_port'] = client.case_socket_port
                        self.require_configuration(client, cfg)
                        cursor = snapshot['cursor']
                        self.publish(dict(snapshot, status='connected'), connection=client)
                        last_read = time.monotonic()
                    else:
                        cursor = {'epoch': event['epoch'], 'revision': event['revision']}
            except Exception:
                self.publish({'status': 'disconnected', 'case': self.reference})
            if self.stopped.wait(backoff):
                return
            backoff = min(15, backoff * 2)

    def require_configuration(self, client, cfg):
        if self.settings is not None:
            return
        from PacsClient.utils.server_profiles import get_active_profile
        current = get_active_profile()
        if (not current or current.id != client.case_profile_id
                or current.host != client.case_pacs_host or current.socket_port != client.case_socket_port
                or cfg != client_settings()):
            raise ValueError('The case source configuration changed during its read.')

    def validate(self, snapshot, host, server_host=None):
        if not isinstance(snapshot, dict) or snapshot.get('case') != self.reference:
            raise ValueError('Case snapshot identity mismatch.')
        reported = snapshot.get('pacs_host')
        if reported in ('127.0.0.1', 'localhost', '::1') and server_host == host:
            # A loopback PACS source on the authenticated Eagle Eye machine is
            # reached by its paired public host from this workstation.
            snapshot['pacs_host'] = host
        elif reported != host:
            raise ValueError('Eagle Eye is bound to a different PACS source.')
        for key in ('eagle_eye', 'echomind', 'jobs'):
            rows = snapshot.get(key)
            if not isinstance(rows, list) or len(rows) > 50 or any(not isinstance(r, dict) for r in rows):
                raise ValueError('Invalid case inventory.')
