"""Separate server and desktop processes serialize the shared entitlement file."""
import os
from pathlib import Path
import subprocess
import sys
import threading

from modules.LicenseGenerator import license_manager
from modules.LicenseGenerator.renewal import RenewalLicenseManager


def test_another_process_cannot_overwrite_an_inflight_license_operation(tmp_path, monkeypatch):
    monkeypatch.setattr(license_manager, '_compute_app_data_dir', lambda: tmp_path / 'legacy')
    directory = tmp_path / 'shared-server'
    command = '''import sys
from modules.LicenseGenerator.renewal import RenewalLicenseManager
manager=RenewalLicenseManager(directory=sys.argv[1], product='eagle-eye-server')
with manager._exclusive():
    print('held', flush=True)
    sys.stdin.readline()
'''
    child = subprocess.Popen([sys.executable, '-c', command, str(directory)],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        text=True, env={**os.environ, 'APPDATA': str(tmp_path / 'child-profile')},
        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    manager = RenewalLicenseManager(directory=directory, product='eagle-eye-server')
    acquired = threading.Event()
    failures = []
    def acquire():
        try:
            with manager._exclusive():
                acquired.set()
        except Exception as exc:
            failures.append(type(exc).__name__)
    worker = threading.Thread(target=acquire)
    ready = threading.Event()
    def read_ready():
        if child.stdout.readline().strip() == 'held':
            ready.set()
    reader = threading.Thread(target=read_ready, daemon=True)
    reader.start()
    try:
        assert ready.wait(3), 'Synthetic child did not acquire its license lock'
        worker.start()
        assert not acquired.wait(.2), 'Concurrent process entered an active licensing transaction'
        child.stdin.write('\n')
        child.stdin.flush()
        assert acquired.wait(3)
        worker.join(3)
        assert not failures
        assert child.wait(3) == 0
    finally:
        if child.poll() is None:
            child.kill()
        child.wait(3)
        if worker.ident:
            worker.join(6)
        reader.join(1)
        child.stdin.close()
        child.stdout.close()
