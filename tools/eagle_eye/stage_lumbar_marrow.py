"""Prepare a bounded marrow patch or stage it against an immutable server baseline.

This tool never changes SCM, server configuration or a running source revision.
"""
import argparse
import difflib
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import zipfile

CHANGED = ('contracts.py', 'adapters.py', 'artifacts.py', 'scheduling.py')
NEW = ('modules/ai_imaging/lumbar_marrow.py',
       'modules/ai_imaging/lumbar_marrow_widget.py',
       'tests/code/ai_imaging/test_lumbar_marrow.py')


def make_bundle(repo, destination):
    manifest = {'format': 1, 'feature': 'lumbar-marrow-t1-v1', 'edits': {}, 'files': {}}
    for name in CHANGED:
        relative = 'modules/ai_imaging/eagle_eye_remote/' + name
        old = subprocess.check_output(['git', 'show', 'HEAD:' + relative], cwd=repo).decode('utf-8').splitlines(True)
        new = (repo / relative).read_text(encoding='utf-8').splitlines(True)
        groups = difflib.SequenceMatcher(None, old, new).get_grouped_opcodes(3)
        manifest['edits'][relative] = [
            {'old': ''.join(old[group[0][1]:group[-1][2]]),
             'new': ''.join(new[group[0][3]:group[-1][4]])}
            for group in groups]
    with zipfile.ZipFile(destination, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for relative in NEW:
            data = (repo / relative).read_bytes()
            manifest['files'][relative] = hashlib.sha256(data).hexdigest()
            archive.writestr(relative, data)
        archive.writestr('manifest.json', json.dumps(manifest, indent=2))
    return manifest


def stage(bundle, baseline, candidate):
    baseline = baseline.resolve(strict=True)
    candidate = candidate.resolve()
    if candidate.exists() or candidate == baseline or candidate.is_relative_to(baseline):
        raise ValueError('A new candidate outside the immutable baseline is required.')
    with zipfile.ZipFile(bundle) as archive:
        manifest = json.loads(archive.read('manifest.json'))
        if manifest.get('format') != 1 or manifest.get('feature') != 'lumbar-marrow-t1-v1':
            raise ValueError('Unsupported staging bundle.')
        expected = {'modules/ai_imaging/eagle_eye_remote/' + name for name in CHANGED}
        if set(manifest['edits']) != expected or set(manifest['files']) != set(NEW):
            raise ValueError('Staging bundle paths are not allowlisted.')
        edits = {}
        for relative, groups in manifest['edits'].items():
            content = (baseline / relative).read_text(encoding='utf-8')
            for group in groups:
                if not group['old'] or content.count(group['old']) != 1:
                    raise ValueError('Baseline patch context changed; stage requires review.')
                content = content.replace(group['old'], group['new'], 1)
            edits[relative] = content
        additions = {}
        for relative, expected_hash in manifest['files'].items():
            data = archive.read(relative)
            if hashlib.sha256(data).hexdigest() != expected_hash:
                raise ValueError('Staging bundle hash changed.')
            additions[relative] = data
    # Preserve baseline code and resources, excluding runtime/data/model payloads.
    excluded = {'.venv', '.git', '.pytest_cache', 'generated-files', 'user_data',
                'database', 'builder', 'builder nuitka', '.vscode', '.agents'}
    def ignore(folder, names):
        return [name for name in names if name == '__pycache__' or name.endswith('.pyc')
                or Path(folder) == baseline and name in excluded]
    shutil.copytree(baseline, candidate, ignore=ignore)
    for relative, content in edits.items():
        (candidate / relative).write_text(content, encoding='utf-8')
    for relative, data in additions.items():
        path = candidate / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    hashes = {relative: hashlib.sha256((candidate / relative).read_bytes()).hexdigest()
              for relative in (*edits, *additions)}
    receipt = dict(feature=manifest['feature'], baseline=str(baseline), candidate=str(candidate),
                   source_sha256=hashes, activated=False,
                   rollback='The original SCM/configuration and immutable baseline remain unchanged.')
    (candidate.parent / 'marrow-stage.json').write_text(json.dumps(receipt, indent=2), encoding='utf-8')
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--make-bundle', type=Path)
    parser.add_argument('--bundle', type=Path)
    parser.add_argument('--baseline', type=Path)
    parser.add_argument('--candidate', type=Path)
    args = parser.parse_args()
    if args.make_bundle:
        make_bundle(Path(__file__).resolve().parents[2], args.make_bundle)
        print('Bounded server bundle prepared; no activation.')
    elif args.bundle and args.baseline and args.candidate:
        stage(args.bundle, args.baseline, args.candidate)
        print('Candidate source staged; no activation.')
    else:
        parser.error('Choose --make-bundle, or --bundle with --baseline and --candidate.')


if __name__ == '__main__':
    main()
