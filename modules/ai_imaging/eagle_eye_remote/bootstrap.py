"""Explicit server/worker commands, before the interactive workstation starts."""
import json
from pathlib import Path
import sys


COMMANDS = ('--eagle-eye-server', '--eagle-eye-worker',
            '--eagle-eye-windows-service', '--eagle-eye-service-child')


def dispatch(argv):
    if len(argv) < 2 or argv[1] not in COMMANDS:
        return False
    if len(argv) != 3:
        raise ValueError('Supply exactly one server configuration or owned job directory.')
    if getattr(sys, 'frozen', False):
        from aipacs_runtime import load_installation_profile
        if load_installation_profile().get('distribution_edition') != 'eagle-eye':
            raise ValueError('Model hosting requires the Eagle Eye server edition.')
    if argv[1] == '--eagle-eye-windows-service':
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
