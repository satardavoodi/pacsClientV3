"""Explicit administration of only the Eagle Eye SCM service; no PACS mutations."""
from pathlib import Path
import math
import subprocess
import sys
import time

from .service_host import SERVICE_NAME, service_config


def service_command(config_path):
    config_path = str(Path(config_path).resolve())
    from aipacs_runtime import is_frozen, load_installation_profile
    if is_frozen():
        if load_installation_profile().get('distribution_edition') != 'eagle-eye':
            raise ValueError('Service installation requires the server edition.')
        return subprocess.list2cmdline([sys.executable, '--eagle-eye-windows-service', config_path])
    script = Path(__file__).resolve().parents[3] / 'tools/eagle_eye/windows_service.py'
    if not script.is_file():
        raise ValueError('The source service entry is missing.')
    return subprocess.list2cmdline([sys.executable, str(script), config_path])


def inspect_service(config_path):
    import win32service as scm
    import pywintypes
    manager = scm.OpenSCManager(None, None, scm.SC_MANAGER_CONNECT)
    service = None
    try:
        try:
            service = scm.OpenService(manager, SERVICE_NAME, scm.SERVICE_QUERY_CONFIG | scm.SERVICE_QUERY_STATUS)
        except pywintypes.error as exc:
            if exc.winerror == 1060:
                return {'installed': False, 'owned': False}
            raise
        config = scm.QueryServiceConfig(service)
        return {'installed': True, 'owned': config[3] == service_command(config_path),
                'running': scm.QueryServiceStatus(service)[1] == scm.SERVICE_RUNNING,
                'automatic': config[1] == scm.SERVICE_AUTO_START}
    finally:
        if service is not None:
            scm.CloseServiceHandle(service)
        scm.CloseServiceHandle(manager)


def install_service(config_path):
    """Requires an elevated administrator; refuse an existing service name."""
    import servicemanager  # Ensure the service dispatcher is installed before SCM writes.
    import win32service as scm
    service_config(config_path)
    from .administration import read_connection, _save
    snapshot = read_connection(config_path)
    manager = scm.OpenSCManager(None, None, scm.SC_MANAGER_CREATE_SERVICE)
    service = None
    try:
        service = scm.CreateService(manager, SERVICE_NAME, 'AI-PACS Eagle Eye Server',
            scm.SERVICE_ALL_ACCESS, scm.SERVICE_WIN32_OWN_PROCESS, scm.SERVICE_AUTO_START,
            scm.SERVICE_ERROR_NORMAL, service_command(config_path), None, 0, None,
            'NT AUTHORITY\\LocalService', None)
        scm.ChangeServiceConfig2(service, scm.SERVICE_CONFIG_DELAYED_AUTO_START_INFO, True)
        scm.ChangeServiceConfig2(service, scm.SERVICE_CONFIG_FAILURE_ACTIONS,
            {'ResetPeriod': 86400, 'RebootMsg': '', 'Command': '',
             'Actions': [(scm.SC_ACTION_RESTART, 15000), (scm.SC_ACTION_RESTART, 60000),
                         (scm.SC_ACTION_RESTART, 120000)]})
        scm.ChangeServiceConfig2(service, scm.SERVICE_CONFIG_FAILURE_ACTIONS_FLAG, True)
        scm.ChangeServiceConfig2(service, scm.SERVICE_CONFIG_DESCRIPTION,
            'Eagle Eye analysis service. Independent of workstation login and clinical PACS services.')
        _save(config_path, snapshot['revision'], lambda previous: {**previous, 'service_managed': True})
    except Exception:
        if service is not None:
            scm.DeleteService(service)
        raise
    finally:
        if service is not None:
            scm.CloseServiceHandle(service)
        scm.CloseServiceHandle(manager)
    return inspect_service(config_path)


def _owned_transition(config_path, operation, timeout):
    """Operate on the exact registered command/account, without adopting a service.

    These are transaction primitives, not an installer or an upgrade policy.
    A timeout leaves SCM ownership intact; it never kills arbitrary processes.
    Removal keeps configuration intact (including service_managed) and marks
    the SCM entry for deletion; it does not claim deletion has completed.
    """
    if not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or not 0 < timeout <= 120:
        raise ValueError('The service transition timeout must be within 120 seconds.')
    expected = service_command(config_path)
    import win32service as scm
    access = scm.SERVICE_QUERY_CONFIG | scm.SERVICE_QUERY_STATUS
    access |= scm.SERVICE_START if operation == 'start' else scm.SERVICE_STOP
    if operation == 'remove':
        access |= 0x00010000  # Windows DELETE right, absent from some win32service builds.
    manager = scm.OpenSCManager(None, None, scm.SC_MANAGER_CONNECT)
    service = None
    try:
        service = scm.OpenService(manager, SERVICE_NAME, access)
        config = scm.QueryServiceConfig(service)
        if config[3] != expected or config[7].casefold() != 'nt authority\\localservice':
            raise ValueError('Service ownership does not match this installation.')
        deadline = time.monotonic() + timeout
        target = scm.SERVICE_RUNNING if operation == 'start' else scm.SERVICE_STOPPED
        pending = scm.SERVICE_START_PENDING if operation == 'start' else scm.SERVICE_STOP_PENDING
        state = scm.QueryServiceStatus(service)[1]
        changed = state != target
        if changed and state != pending:
            if operation == 'start' and state == scm.SERVICE_STOPPED:
                scm.StartService(service, None)
            elif operation != 'start' and state == scm.SERVICE_RUNNING:
                scm.ControlService(service, scm.SERVICE_CONTROL_STOP)
            else:
                raise RuntimeError('Service is in an incompatible transition state.')
        while scm.QueryServiceStatus(service)[1] != target:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError('Owned service did not reach the requested state.')
            time.sleep(min(0.2, remaining))
        if operation == 'remove':
            scm.DeleteService(service)
        return changed
    finally:
        if service is not None:
            scm.CloseServiceHandle(service)
        scm.CloseServiceHandle(manager)


def stop_owned_service(config_path, *, timeout=30):
    """Stop only this installation's service; return whether it needed stopping."""
    return _owned_transition(config_path, 'stop', timeout)


def start_owned_service(config_path, *, timeout=60):
    """Start only this installation's service; RUNNING is not model acceptance."""
    return _owned_transition(config_path, 'start', timeout)


def remove_owned_service(config_path, *, timeout=30):
    """Stop then mark the owned service for deletion, preserving configuration."""
    _owned_transition(config_path, 'remove', timeout)
