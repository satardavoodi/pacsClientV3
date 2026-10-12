"""SSH forced command for the pinned CPU-only research container."""
from pathlib import Path
import os
import subprocess
import sys
import signal
import uuid

DIGEST = 'sha256:74a722b3fb62f5b3f7f08820bfac9a21c1ffbe357311f22f9e1e187129204147'


def main():
    if os.environ.get('SSH_ORIGINAL_COMMAND') != 'dental-panorama-v1':
        raise SystemExit('Unsupported worker operation')
    payload = sys.stdin.buffer.read(32 * 1024**2 + 1)
    if len(payload) > 32 * 1024**2:
        raise SystemExit('Input too large')
    runner = Path(__file__).with_name('dental_container_runner.py').resolve()
    name = 'aipacs-dental-' + uuid.uuid4().hex
    command = ['docker', 'run', '--name', name, '--rm', '-i', '--network', 'none', '--cpus', '2', '--memory', '6g',
               '--pids-limit', '128', '-e', 'OMP_NUM_THREADS=2', '-e', 'MKL_NUM_THREADS=2',
               '-v', str(runner) + ':/runner.py:ro', '--entrypoint', 'poetry',
               'stmharry/dental-pano-ai@' + DIGEST, 'run', 'python3.11', '/runner.py']
    # Serialize cold-start workers without exposing a listener or accepting commands.
    import fcntl
    with runner.with_suffix('.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit('Dental worker busy')
        def interrupted(_signum, _frame):
            raise SystemExit('Worker connection closed')
        for signum in (signal.SIGHUP, signal.SIGTERM, signal.SIGINT):
            signal.signal(signum, interrupted)
        try:
            result = subprocess.run(command, input=payload, stdout=subprocess.PIPE,
                                    stderr=subprocess.DEVNULL, timeout=220)
        finally:
            # Only this request's uniquely named container may be retired.
            subprocess.run(['docker', 'rm', '-f', name], stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, timeout=15)
    if result.returncode or len(result.stdout) > 2 * 1024**2:
        raise SystemExit('Dental worker failed')
    sys.stdout.buffer.write(result.stdout)


if __name__ == '__main__':
    main()
