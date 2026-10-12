"""One research request, unchanged FCOS and frozen calcium in separate CPU processes.

No clinical routing, installed payload, service selection or qualification is changed.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from tools.eagle_eye.calcium_candidate import digest


def collect(job, branches, request):
    """A missing/failed branch is unavailable, never an empty normal result."""
    if set(branches) != {'parenchymal', 'calcium'}:
        raise ValueError('Both branch outcomes are required.')
    result = dict(study_id=request['study_uid'], qualification='research_only', branches={})
    for name, code in branches.items():
        path = job / name / 'result.json'
        if code != 0 or not path.is_file():
            result['branches'][name] = dict(status='unavailable', exit_code=code)
            continue
        data = json.loads(path.read_text(encoding='utf-8'))
        if data.get('status') != 'success' or data.get('study_id') != request['study_uid']:
            raise ValueError('Branch result identity mismatch.')
        if name == 'calcium':
            expected = {(r['series_uid'], r['sop_uid'], r['sha256']) for r in request['files']}
            actual = [(r['series_uid'], r['sop_uid'], r['source_sha256']) for r in data['files']]
            if set(actual) != expected or len(actual) != len(expected):
                raise ValueError('Calcium per-image identity mismatch.')
        result['branches'][name] = data
    for record in request['files']:
        if digest(record['path']) != record['sha256']:
            raise ValueError('Source changed; discard both branch results.')
    result['status'] = ('success' if all(b['status'] == 'success' for b in result['branches'].values())
                        else 'incomplete')
    return result


def run(args):
    from modules.ai_imaging.eagle_eye_engines.service import validate_bundle, validate_sources, runtime_command
    root = args.bundle.resolve()
    manifest = validate_bundle(root, 'breast')
    request = json.loads(args.request.read_text(encoding='utf-8'))
    if not .05 <= float(request.get('threshold', .45)) <= .95:
        raise ValueError('Invalid tissue threshold.')
    records, _ = validate_sources([r['path'] for r in request['files']], request['study_uid'], 'breast')
    request = dict(engine='breast', files=records, study_uid=request['study_uid'],
                   threshold=float(request.get('threshold', .45)), smoke=False, sex=None)
    job = args.output.resolve() / ('dual-' + uuid.uuid4().hex)
    job.mkdir(parents=True)
    for name in ('parenchymal', 'calcium'):
        (job / name).mkdir()
        (job / name / 'request.json').write_text(json.dumps(request), encoding='utf-8')
    tissue_command = runtime_command(root, job / 'parenchymal', manifest)
    python = Path(tissue_command[0])
    if not python.is_file():
        raise ValueError('This candidate currently requires the prepared Windows CPU runtime.')
    commands = {
        'parenchymal': tissue_command,
        'calcium': [str(python), str(Path(__file__).with_name('calcium_candidate.py')),
                    '--request', str(job / 'calcium/request.json'), '--job', str(job / 'calcium'),
                    '--assets', str(args.assets.resolve()), '--deps', str(args.deps.resolve()), '--threads', '2'],
    }
    env = {k: v for k, v in os.environ.items() if not k.startswith(('PYTHON', 'QT_'))}
    env.update(CUDA_VISIBLE_DEVICES='-1', OMP_NUM_THREADS='2', MKL_NUM_THREADS='2',
               PYTHONNOUSERSITE='1', PYTHONDONTWRITEBYTECODE='1', PYTHONUTF8='1',
               HF_HUB_OFFLINE='1', HF_HUB_DISABLE_TELEMETRY='1', NO_ALBUMENTATIONS_UPDATE='1')
    processes, logs, codes = {}, [], {}
    start = time.monotonic()
    try:
        for name, command in commands.items():
            log = (job / name / 'private.log').open('wb')
            logs.append(log)
            processes[name] = subprocess.Popen(command, cwd=job / name, env=env,
                                                stdout=log, stderr=log, stdin=subprocess.DEVNULL,
                                                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            if args.schedule == 'serial':
                codes[name] = processes[name].wait(timeout=args.timeout)
        if args.schedule == 'parallel':
            for name, process in processes.items():
                codes[name] = process.wait(timeout=max(1, args.timeout - (time.monotonic() - start)))
        result = collect(job, codes, request)
        result.update(schedule=args.schedule, elapsed_seconds=time.monotonic() - start,
                      tissue_revision=manifest['revision'])
        temporary = job / 'result.partial'
        temporary.write_text(json.dumps(result, allow_nan=False), encoding='utf-8')
        temporary.replace(job / 'result.json')
        print(json.dumps(dict(status=result['status'], schedule=args.schedule,
                              elapsed_seconds=result['elapsed_seconds'], job=str(job),
                              branches={k: v['status'] for k, v in result['branches'].items()})))
        return 0 if result['status'] == 'success' else 2
    finally:
        for process in processes.values():
            if process.poll() is None:
                process.kill()
            process.wait(timeout=15)
        for log in logs:
            log.close()


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('bundle', 'request', 'assets', 'deps', 'output'):
        p.add_argument('--' + name, type=Path, required=True)
    p.add_argument('--schedule', choices=('serial', 'parallel'), default='parallel')
    p.add_argument('--timeout', type=int, default=1200)
    raise SystemExit(run(p.parse_args()))
