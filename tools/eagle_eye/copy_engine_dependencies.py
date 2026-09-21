"""Read an allowlisted dependency closure from the existing clinic engine venv.

Streams library files only; never writes remotely or reads an application dataset.
Uses the control-node SSH configuration and a private ignored local staging folder.
"""
import argparse
import base64
import json
from pathlib import Path
import subprocess
import tarfile
import re

REPO = Path(__file__).resolve().parents[2]
SSH = ['C:/Program Files/Git/usr/bin/ssh.exe', '-F', 'D:/control pc node/ssh/config']
TARGETS = {
    'breast': ('pacs', 'D:/FCOS_AR/venv', ['torch', 'torchvision', 'itk', 'imageio', 'pandas',
                'pydicom', 'xgboost', 'lightgbm', 'catboost', 'scikit-learn', 'pylibjpeg', 'pylibjpeg-libjpeg', 'pylibjpeg-openjpeg']),
    'bone-age': ('wina100', 'D:/Bone/venv', ['torch', 'torchvision', 'timm', 'albumentations', 'pydicom']),
}


def copy(engine, complete_existing=False):
    host, venv, roots = TARGETS[engine]
    root = REPO / 'generated-files/eagle-eye' / engine
    installed = []
    if complete_existing:
        result = subprocess.run([str(root / 'runtime/Scripts/python.exe'), '-c',
            "import importlib.metadata as m,json; print(json.dumps([d.metadata['Name'].lower().replace('_','-') for d in m.distributions()]))"],
            check=True, capture_output=True, text=True)
        installed = json.loads(result.stdout)
    code = '''import importlib.metadata as m, json
from packaging.requirements import Requirement
pending=ROOTS; visited={}; top=set(); installed=INSTALLED
while pending:
 name=pending.pop()
 key=name.lower().replace('_','-')
 if key in visited or key in installed:continue
 d=m.distribution(name); visited[key]=d.version
 for f in d.files or []:
  parts=f.parts
  if parts and parts[0] not in ('..','.') and not str(f).startswith(('/', '\\\\')):top.add(parts[0])
 for spec in d.requires or []:
  req=Requirement(spec)
  if req.marker is None or req.marker.evaluate({'extra':''}):pending.append(req.name)
print(json.dumps({'versions':visited,'entries':sorted(top)}))
'''.replace('ROOTS', repr(roots)).replace('INSTALLED', repr(installed))
    encoded_code = base64.b64encode(code.encode()).decode()
    command = "& '" + venv + "/Scripts/python.exe' -c \"import base64;exec(base64.b64decode('" + encoded_code + "'))\""
    encoded = base64.b64encode(command.encode('utf-16-le')).decode()
    proc = subprocess.run(SSH + [host, 'powershell', '-NoProfile', '-EncodedCommand', encoded], capture_output=True, text=True)
    if proc.returncode:
        raise RuntimeError('Dependency inventory failed: ' + proc.stderr[-800:])
    inventory = json.loads(proc.stdout)
    entries = inventory['entries']
    if not all(re.fullmatch(r'[A-Za-z0-9_.+-]+', x) and not x.startswith('-') for x in entries):
        raise ValueError('Unsafe library inventory.')
    root = REPO / 'generated-files/eagle-eye' / engine
    archive = root / ('dependency-completion.tar' if complete_existing else 'dependency-snapshot.tar')
    with archive.open('wb') as output:
        proc = subprocess.run(SSH + [host, 'tar', '-cf', '-', '-C', venv + '/Lib/site-packages', *entries], stdout=output, stderr=subprocess.PIPE)
    if proc.returncode:
        raise RuntimeError('Dependency archive read failed.')
    target = root / ('runtime/Lib/site-packages' if complete_existing else 'runtime-lan/Lib/site-packages')
    with tarfile.open(archive) as package:
        for member in package.getmembers():
            if member.issym() or member.islnk() or not (target / member.name).resolve().is_relative_to(target.resolve()):
                raise ValueError('Unsafe dependency archive member.')
        package.extractall(target, filter='data')
    (root / ('dependency-completion.json' if complete_existing else 'dependency-source.json')).write_text(json.dumps(inventory, indent=2), encoding='utf-8')
    print(engine + ': copied ' + str(len(inventory['versions'])) + ' dependency distributions')


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('engine', choices=TARGETS)
    p.add_argument('--complete-existing', action='store_true')
    args = p.parse_args()
    copy(args.engine, args.complete_existing)
