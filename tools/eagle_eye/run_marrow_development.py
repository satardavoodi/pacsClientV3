"""Own one manually started Development listener through the existing supervisor."""
import argparse
import os
from pathlib import Path
import sys
import threading


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--config', type=Path, required=True)
    args = parser.parse_args()
    source, config = args.source.resolve(strict=True), args.config.resolve(strict=True)
    sys.path.insert(0, str(source))
    os.chdir(source)
    from modules.ai_imaging.eagle_eye_remote.service_host import Supervisor, service_config
    settings = service_config(config)
    if settings.get('host') != '127.0.0.1' or settings.get('port') != 8042:
        raise ValueError('This Development runner only supports the isolated loopback endpoint.')
    for key in ('OMP_NUM_THREADS', 'MKL_NUM_THREADS', 'OPENBLAS_NUM_THREADS'):
        os.environ[key] = '1'
    Supervisor(str(config)).run(threading.Event(), lambda state: print(state, flush=True))


if __name__ == '__main__':
    main()
