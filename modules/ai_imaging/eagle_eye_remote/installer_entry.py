"""Frozen Server setup dispatcher with explicit staged versus activated receipts."""
import json
from pathlib import Path
import sys

from . import release_package
from .startup_barrier import plain_path, read_record, payload_identity

COMMAND = '--eagle-eye-install-server'
SETUP_COMMAND = '--eagle-eye-setup-server'
FIELDS = {'schema', 'operation', 'core_root', 'private_root', 'config_path', 'payloads', 'shortcut'}


def official_provisioning(config_path, candidate):
    """Use the actual signed host-bound Server product; never reinterpret Client."""
    from .service_host import service_config
    from modules.LicenseGenerator.renewal import server_manager
    config = service_config(config_path)
    manager = server_manager(config)
    status = manager.status()
    valid = (manager.product == 'eagle-eye-server' and status.get('product') == 'eagle-eye-server'
             and status.get('valid') is True and not status.get('legacy', False))
    return {'verified': valid, 'role': 'server' if valid else None, 'host_bound': valid}


def validate_request(request):
    from aipacs_runtime import is_frozen, load_installation_profile
    if not is_frozen() or load_installation_profile().get('distribution_edition') != 'eagle-eye':
        raise ValueError('Installed setup requires the frozen Eagle Eye Server edition.')
    if (not isinstance(request, dict) or set(request) != FIELDS or request['schema'] != 1
            or request['operation'] not in ('stage', 'install') or not isinstance(request['payloads'], list)):
        raise ValueError('Invalid installed Server setup request.')
    core = plain_path(request['core_root'])
    if core != Path(sys.executable).resolve().parent:
        raise ValueError('Setup can only operate on its own immutable frozen core.')
    private = plain_path(request['private_root'])
    if private.is_relative_to(core):
        raise ValueError('Host-private setup state must remain outside its frozen core.')
    if request['config_path'] is not None:
        config = plain_path(request['config_path'])
        if not config.is_relative_to(private):
            raise ValueError('Server configuration must remain host-private.')
    if plain_path(request['shortcut']).suffix.lower() != '.lnk':
        raise ValueError('Setup requires one explicit Server desktop shortcut.')
    return core, private


def execute(request, *, backend_factory=None, protect=None):
    """Stage-only works without a Server license; activation never does."""
    from tools.eagle_eye.installed_release_host import InstalledReleaseHost, WindowsBackend, _atomic_json
    from tools.eagle_eye.fresh_server_install import FreshServerInstall

    core, private = validate_request(request)
    identity = release_package.verify(core)
    protection = protect or WindowsBackend.protect
    private.mkdir(parents=True, exist_ok=True)
    protection(private)
    stage_receipt = {'schema': 1, 'phase': 'package_staged_service_not_activated',
                     'release_id': identity['release_id'], 'service_activated': False,
                     'installer_lifecycle_qualified': False}
    _atomic_json(private / 'setup-stage.json', stage_receipt)
    protection(private / 'setup-stage.json')
    config = request['config_path']
    if request['operation'] == 'stage' or config is None:
        return stage_receipt
    proof = official_provisioning(config, None)
    if proof['verified'] is not True:
        stage_receipt['phase'] = 'awaiting_official_server_provisioning'
        _atomic_json(private / 'setup-stage.json', stage_receipt)
        protection(private / 'setup-stage.json')
        return stage_receipt
    # Payload verification cannot be waived for activated install QA.
    from .installed_layout import selection
    if selection(core) != request['payloads']:
        raise ValueError('Frozen Server activation requires its sealed payload selection.')
    payload_identity(core, request['payloads'])
    if backend_factory is None:
        raise RuntimeError('Installed setup activation driver is not qualified; package remains staged.')
    backend = backend_factory(request, official_provisioning)
    host = InstalledReleaseHost(core.parent, private, config, backend)
    candidate = host.describe(core, payloads=request['payloads'])
    return FreshServerInstall(host).run(candidate)


def dispatch(argv):
    if len(argv) >= 2 and argv[1] == SETUP_COMMAND:
        if len(argv) != 5:
            raise ValueError('Setup requires private state, optional config and shortcut paths.')
        from tools.eagle_eye.installed_release_host import WindowsBackend, _atomic_json
        from tools.eagle_eye.fresh_install_driver import create_backend
        from .installed_layout import selection
        core = Path(sys.executable).resolve().parent
        request = {'schema': 1, 'operation': 'install' if argv[3] else 'stage',
            'core_root': str(core), 'private_root': argv[2], 'config_path': argv[3] or None,
            'payloads': selection(core), 'shortcut': argv[4]}
        _, private = validate_request(request)
        private.mkdir(parents=True, exist_ok=True)
        WindowsBackend.protect(private)
        request_path = private / 'setup-request.json'
        _atomic_json(request_path, request)
        WindowsBackend.protect(request_path)
        execute(read_record(request_path), backend_factory=create_backend)
        return True
    if len(argv) < 2 or argv[1] != COMMAND:
        return False
    if len(argv) != 3:
        raise ValueError('Supply one protected installed Server setup request.')
    from tools.eagle_eye.fresh_install_driver import create_backend
    execute(read_record(argv[2]), backend_factory=create_backend)
    return True
