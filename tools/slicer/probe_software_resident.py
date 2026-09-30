"""Owned synthetic viewer probe with the supported software OpenGL choice."""
import argparse
import json
import os
from pathlib import Path
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--executable', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--graphics-dir', type=Path)
    args = parser.parse_args()
    from modules.mpr.advanced_3d_slicer.resident_service import LocalRuntime
    os.environ['QT_OPENGL'] = 'software'
    if args.graphics_dir:
        directory = args.graphics_dir.resolve(strict=True)
        if not directory.is_dir():
            parser.error('Graphics directory must be a directory')
        os.environ['PATH'] = str(directory) + os.pathsep + os.environ.get('PATH', '')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    runtime = LocalRuntime('viewer', executable=args.executable,
                           diagnostic_log=args.output.with_suffix('.log'))
    result = {'scope': 'synthetic-viewer-only', 'ready': False, 'passed': False}
    try:
        runtime.start()
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            if runtime.ready():
                result['ready'] = True
                break
            time.sleep(.25)
        if not result['ready']:
            raise TimeoutError('Viewer readiness')
        state = runtime.command('status', {}, threading.Event(), 10)
        result['status'] = state
        result['passed'] = (state.get('role') == 'viewer'
                            and state.get('window_visible') is False)
    except Exception as exc:
        result['error_type'] = type(exc).__name__
    finally:
        runtime.close()
        args.output.write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps({k: v for k, v in result.items() if k != 'status'}))
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
