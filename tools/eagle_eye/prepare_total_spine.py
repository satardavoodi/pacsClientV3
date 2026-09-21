"""Prepare pinned research weights; use the existing isolated Alignment runtime.

No patient data, training images or credentials are downloaded or included.
"""
from pathlib import Path
import argparse
import hashlib
import json
import shutil
import sys
import urllib.request
import zipfile
import tempfile

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from modules.ai_imaging.eagle_eye_total_spine.inference import SOURCE_REVISION, WEIGHT_SHA256


def prepare(destination):
    root = Path(destination)
    root.mkdir(parents=True, exist_ok=True)
    base = 'https://raw.githubusercontent.com/yijingru/Vertebra-Landmark-Detection/'+SOURCE_REVISION+'/'
    files = ('models/__init__.py', 'models/spinal_net.py', 'models/dec_net.py',
             'models/model_parts.py', 'models/resnet.py', 'decoder.py', 'LICENSE')
    for name in files:
        with urllib.request.urlopen(base+name, timeout=30) as response:
            data = response.read()
        target = root/name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    # The upstream optional pretrained path is disabled even if called by mistake.
    path = root/'models/resnet.py'
    source = path.read_text(encoding='utf-8')
    start = source.index('    if pretrained:\n', source.index('def _resnet('))
    end = source.index('    return model', start)
    source = source[:start] + "    if pretrained:\n        raise ValueError('Network downloads are disabled in this offline bundle.')\n" + source[end:]
    path.write_text(source, encoding='utf-8')
    cached = REPO/'generated-files/eagle-eye/total-spine-research/model_last.pth'
    weight = root/'model_last.pth'
    if cached.is_file() and hashlib.sha256(cached.read_bytes()).hexdigest() == WEIGHT_SHA256:
        shutil.copy2(cached, weight)
    elif not weight.is_file() or hashlib.sha256(weight.read_bytes()).hexdigest() != WEIGHT_SHA256:
        with tempfile.TemporaryDirectory(prefix='total-spine-weights-') as temporary:
            archive = Path(temporary)/'weights.zip'
            url = 'https://drive.usercontent.google.com/download?id=1X9gsP9_tvjPrfFlFWKkb9oP9jb-XmN7S&export=download&confirm=t'
            with urllib.request.urlopen(url, timeout=60) as response, archive.open('wb') as output:
                shutil.copyfileobj(response, output)
            with zipfile.ZipFile(archive) as zipped:
                data = zipped.read('model_last.pth')
            if hashlib.sha256(data).hexdigest() != WEIGHT_SHA256:
                raise ValueError('Upstream checkpoint hash changed.')
            weight.write_bytes(data)
    shutil.copy2(REPO/'modules/ai_imaging/eagle_eye_total_spine/inference.py', root/'inference.py')
    (root/'NOTICE').write_text(
        'Vertebra-Focused Landmark Detection for Scoliosis Assessment. Yi et al., ISBI 2020.\n'
        'Source: https://github.com/yijingru/Vertebra-Landmark-Detection\n'
        'MIT source license retained in LICENSE. Checkpoint supplied through the author README.\n'
        'Separate weight/data redistribution terms were not established. Research evaluation only.\n'
        'AI-PACS adaptation: no pretrained downloads, CPU inference, strict weights-only load,\n'
        'PIL bilinear preprocessing, validated source-coordinate candidates, no anatomical numbering claim.\n', encoding='utf-8')
    names = (*files, 'model_last.pth', 'inference.py', 'NOTICE')
    hashes = {name: hashlib.sha256((root/name).read_bytes()).hexdigest() for name in names}
    manifest = dict(format_version=1, source_revision=SOURCE_REVISION,
                    weight_sha256=WEIGHT_SHA256, runtime_provider='alignment', sha256=hashes)
    (root/'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    print('Prepared Total Spine model bundle; runtime and clinical acceptance are separate.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--destination', type=Path, default=REPO/'generated-files/eagle-eye/total-spine')
    prepare(parser.parse_args().destination)
