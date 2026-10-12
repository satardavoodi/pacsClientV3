"""Explicit server/worker commands, before the interactive workstation starts."""
import json
from pathlib import Path


COMMANDS = ('--eagle-eye-server', '--eagle-eye-worker',
            '--eagle-eye-windows-service', '--eagle-eye-service-child', '--eagle-eye-crm-worker')


def dispatch(argv):
    from .installer_entry import dispatch as dispatch_installer
    if dispatch_installer(argv):
        return True
    if len(argv) < 2 or argv[1] not in COMMANDS:
        return False
    if len(argv) != 3:
        raise ValueError('Supply exactly one server configuration or owned job directory.')
    from aipacs_runtime import is_frozen, load_installation_profile
    if is_frozen():
        if load_installation_profile().get('distribution_edition') != 'eagle-eye':
            raise ValueError('Model hosting requires the Eagle Eye server edition.')
    if argv[1] == '--eagle-eye-crm-worker':
        from .crm.worker import main
        main()
    elif argv[1] == '--eagle-eye-windows-service':
        from .service_host import run_windows_service
        run_windows_service(Path(argv[2]))
    elif argv[1] == '--eagle-eye-service-child':
        from .service_host import serve_child
        serve_child(Path(argv[2]))
    elif argv[1] == '--eagle-eye-server':
        from .server import serve
        serve(json.loads(Path(argv[2]).read_text(encoding='utf-8-sig')))
    else:
        from .adapters import main
        main(Path(argv[2]))
    return True
