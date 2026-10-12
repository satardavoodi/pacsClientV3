"""Prepare the reviewed offline MR body supplement from an official local archive.

Download Dataset850_TotalSegMRI_part1_organs_1088subj.zip from the official
TotalSegmentator v2.5.0-weights release, then pass --archive and a new --output.
Never run inference or write into an existing model directory from this tool.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import zipfile

ARCHIVE_SHA256 = '8c6249783a270e2f6a23c1d554e03f2643771309474c58225c984f5df3d27835'
ARCHIVE_URL = ('https://github.com/wasserth/TotalSegmentator/releases/download/'
               'v2.5.0-weights/Dataset850_TotalSegMRI_part1_organs_1088subj.zip')


def prepare(archive, output):
    from modules.ai_imaging.marrow_body_worker import verify_manifest
    archive, output = Path(archive).resolve(strict=True), Path(output).resolve()
    if output.exists():
        raise ValueError('Choose a new immutable model directory.')
    with archive.open('rb') as stream:
        if hashlib.file_digest(stream, 'sha256').hexdigest() != ARCHIVE_SHA256:
            raise ValueError('The official model archive checksum does not match.')
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='marrow-assets-', dir=output.parent) as temporary:
        stage = Path(temporary)
        with zipfile.ZipFile(archive) as z:
            for member in z.infolist():
                relative = Path(member.filename)
                if (relative.is_absolute() or '..' in relative.parts or ':' in member.filename
                        or '\\' in member.filename):
                    raise ValueError('Unsafe archive member.')
                if member.is_dir():
                    continue
                dest = stage / 'weights' / relative
                dest.parent.mkdir(parents=True, exist_ok=True)
                with z.open(member) as source, dest.open('wb') as target:
                    shutil.copyfileobj(source, target)
        files = []
        for path in sorted((stage / 'weights').rglob('*')):
            if path.is_file():
                with path.open('rb') as stream:
                    checksum = hashlib.file_digest(stream, 'sha256').hexdigest()
                files.append({'path':path.relative_to(stage).as_posix(),
                              'sha256':checksum, 'size':path.stat().st_size})
        manifest = dict(format=1, task='total_mr', roi='vertebrae', dataset=850,
                        license='Apache-2.0', engine='2.14.0', archive_url=ARCHIVE_URL,
                        archive_sha256=ARCHIVE_SHA256, files=files)
        verify_manifest(manifest)
        (stage / 'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
        stage.rename(output)
    return output


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print(prepare(args.archive, args.output))
