"""Bounded best-effort logout using the original pinned transport, never the GUI."""
import queue
import threading
import urllib.request

_pending = queue.Queue(maxsize=64)
_lock = threading.Lock()
_worker = None


def _revoke(item):
    url, opener, device, opaque = item
    headers = {'X-Eagle-User-Session': opaque, 'Content-Type': 'application/json'}
    if device:
        headers['Authorization'] = 'Bearer ' + device
    request = urllib.request.Request(url + '/v1/auth/logout', data=b'{}', method='POST', headers=headers)
    try:
        with opener.open(request, timeout=2) as response:
            response.read(1024)
    except Exception:
        # Cleanup cannot restore local admission or replay any application request.
        pass


def _drain():
    global _worker
    while True:
        with _lock:
            try:
                item = _pending.get_nowait()
            except queue.Empty:
                _worker = None
                return
        try:
            _revoke(item)
        finally:
            _pending.task_done()


def schedule(item):
    global _worker
    with _lock:
        try:
            _pending.put_nowait(item)
        except queue.Full:
            return False
        if _worker is None:
            _worker = threading.Thread(target=_drain, name='Eagle-human-logout', daemon=True)
            _worker.start()
    return True
