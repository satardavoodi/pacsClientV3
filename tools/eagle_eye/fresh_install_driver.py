"""Fresh setup OS driver; post-release uncertainty requires manual recovery."""
from pathlib import Path
import time

from modules.ai_imaging.eagle_eye_remote import startup_barrier as barrier
from .fresh_server_install import WindowsFreshBackend


def create_backend(request, provisioning):
    backend = None

    def never_upgrade():
        raise RuntimeError('Fresh setup does not provide an upgrade admission transport.')

    def closed_for_removal(manifest, candidate):
        marker = Path(manifest['release_marker_path'])
        barrier.protected_file(marker)
        if marker.exists():
            return backend.cooperative_removal(candidate)
        state = backend.inspect()
        if not state.get('installed', True) or state.get('stopped') is True:
            if state.get('installed', True) and (state.get('pid') != 0
                    or state.get('command') != backend.expected_command(candidate)
                    or state.get('account', '').casefold() != 'nt authority\\localservice'):
                raise RuntimeError('Stopped startup service ownership is uncertain.')
            # The transaction exclusive lock remains held by FreshServerInstall.
            # STOPPED alone cannot rule out an orphaned runtime child.
            backend.verify_no_runtime(candidate)
            return {'state': 'quiesced', 'inflight': 0, 'completion_uncertain': False,
                    'fresh': True, 'never_released': True}
        record = barrier.read_record(manifest['readiness_path'], runtime_writable=True)
        if (any(record.get(key) != manifest[key] for key in barrier.BINDINGS)
                or not state.get('running') or state.get('pid') != record.get('scm_pid')
                or state.get('command') != backend.expected_command(candidate)
                or state.get('account', '').casefold() != 'nt authority\\localservice'):
            raise RuntimeError('Closed startup readiness does not own the current service.')
        backend.verify_child(record, candidate)
        # A protected absent marker plus this still-live startup child proves
        # admission has never opened, rather than assuming a timestamp is fresh.
        snapshot = record.get('admission') or {}
        if (snapshot.get('state') != 'quiesced' or snapshot.get('inflight') != 0
                or snapshot.get('completion_uncertain') is not False):
            raise RuntimeError('Startup admission is not certainly closed.')
        return {**snapshot, 'fresh': True, 'never_released': True}

    def retain_closed(manifest):
        # FreshServerInstall already persisted recovery_required. There is no
        # permission here to force-stop a possibly accepting service.
        barrier.protected_file(manifest['journal_path'])

    backend = WindowsFreshBackend(provisioning=provisioning,
        closed_for_removal=closed_for_removal, retain_closed=retain_closed,
        admission=never_upgrade, health=lambda *args: never_upgrade(),
        shortcut=request['shortcut'])
    import subprocess
    backend.expected_command = lambda candidate: subprocess.list2cmdline([
        str(Path(candidate['root']) / 'AIPacs.exe'), '--eagle-eye-windows-service',
        str(Path(request['config_path']).resolve())])
    def verify_no_runtime(candidate):
        import psutil
        executable = (Path(candidate['root']) / 'AIPacs.exe').resolve()
        for process in psutil.process_iter():
            # Windows reserves these PIDs for the idle/kernel processes. They
            # cannot be an installed user-mode AIPacs runtime.
            if process.pid in (0, 4):
                continue
            try:
                if Path(process.exe()).resolve() == executable and any(flag in process.cmdline()
                        for flag in ('--eagle-eye-service-child', '--eagle-eye-windows-service')):
                    raise RuntimeError('An installed runtime process still exists.')
            except psutil.NoSuchProcess:
                continue
            except (psutil.AccessDenied, OSError):
                raise RuntimeError('Runtime process absence could not be established.') from None
    backend.verify_no_runtime = verify_no_runtime
    def cooperative_removal(candidate):
        from modules.ai_imaging.eagle_eye_remote import service_control
        core = Path(candidate['root']).resolve()
        executable = core / 'AIPacs.exe'
        state = backend.inspect()
        if (not state.get('running') or state.get('command') != backend.expected_command(candidate)
                or state.get('account', '').casefold() != 'nt authority\\localservice'):
            raise RuntimeError('Cooperative removal requires the current owned live service.')
        expected = service_control.reviewed_identity(request['config_path'], core,
            core / 'eagle-eye-release.json', executable, executable, scm_pid=state['pid'])
        if expected['scm_command'] != backend.expected_command(candidate):
            raise RuntimeError('Cooperative control identity differs from the installed candidate.')
        deadline = time.monotonic() + backend.timeout
        receipt = service_control.stop_when_idle(request['config_path'], expected, deadline)
        if (receipt.get('result') != 'committed' or receipt.get('code') != 'CERTIFIED_IDLE_EXIT'
                or receipt.get('identity') != expected or receipt.get('closed') is not True
                or type(receipt.get('inflight')) is not int or receipt['inflight'] != 0
                or receipt.get('completion_uncertain') is not False):
            raise RuntimeError('Cooperative control lacks exact committed idle proof.')
        while time.monotonic() < deadline:
            stopped = backend.inspect()
            if (stopped.get('command') != backend.expected_command(candidate)
                    or stopped.get('account', '').casefold() != 'nt authority\\localservice'):
                raise RuntimeError('Service identity changed after cooperative completion.')
            if stopped.get('stopped') is True and stopped.get('pid') == 0:
                backend.verify_no_runtime(candidate)
                return {'state': 'closed', 'inflight': 0, 'completion_uncertain': False,
                        'fresh': True, 'cooperatively_stopped': True}
            time.sleep(min(.1, max(.001, deadline - time.monotonic())))
        raise TimeoutError('Cooperative stop was not observed; no SCM stop fallback is permitted.')
    backend.cooperative_removal = cooperative_removal
    return backend
