"""Service-owned PACS event subscription; no Qt or clinical database imports."""
import threading
import urllib.parse

from modules.network.workflow_realtime import WorkflowReceiver


class PacsCaseBridge(threading.Thread):
    def __init__(self, cases, config):
        super().__init__(name='EagleEyePacsEvents', daemon=True)
        self.cases, self.config = cases, config
        self.stopped = threading.Event()
        self.receiver = None
        self.status = 'connecting'

    def stop(self):
        self.stopped.set()
        if self.receiver:
            self.receiver.stop()

    def set_status(self, value):
        if self.status != value:
            self.status = value
            self.cases.events.publish('', 'workflow')

    def run(self):
        source = self.cases.jobs.source
        host = urllib.parse.urlsplit(self.config.get('url', '')).hostname
        if not host:
            self.set_status('unavailable')
            return
        while not self.stopped.is_set():
            receiver = None
            try:
                if self.config.get('credential_file'):
                    with source._auth_lock:
                        source._login()
                token = source.session.headers.get('Authorization', '').removeprefix('Bearer ')
                if not token:
                    raise ValueError('PACS service authentication unavailable.')
                receiver = WorkflowReceiver(host, self.config.get('socket_port', 50052),
                    token, transform=lambda states: states)
                self.receiver = receiver
                receiver.start()
                while not self.stopped.wait(.2):
                    receiver.watch(self.cases.watch_list())
                    self.cases.workflow_update(receiver.mailbox.drain())
                    self.set_status(receiver.status)
                    if not receiver.is_alive():
                        break
            except Exception:
                self.set_status('reconnecting')
            finally:
                if receiver:
                    receiver.stop()
                    receiver.join(timeout=6)
                self.receiver = None
                self.set_status('disconnected')
            if self.stopped.wait(15):
                break
