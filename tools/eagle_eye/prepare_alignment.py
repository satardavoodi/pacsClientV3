"""Provision the pinned local Alignment package outside the application venv.

Run with the source Python: --install-runtime --download --seal. Re-running
verifies existing weights. No patient data is opened or sent to the network.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import urllib.request

REPO=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(REPO))
from modules.ai_imaging.eagle_eye_alignment.service import SOURCE_REVISION,WEIGHT_REVISION,digest

FILES={
 'Weights/Ankle/Best_Run_ep100_bs8_lr1e-05_a0.2.pth':'b31ab602058b9c28e5bc91c1dfe6e879168d9417436789a259e6f1e5a58e4f8d',
 'Weights/Diaphysis/Best_DiceCELoss_lr1e5.pth':'9f94c1c46da0aad6708a2f018060c0fb18efb1d699df663c6233c8554663a0db',
 'Weights/Femur/Best_Run_ep100_bs8_lr1e-05_a0.2.pth':'4673b6b9074b42fed38fdeb57681624b86d305b683bf55ff53b8be8470b63cd7',
 'Weights/Knee/Best_Run_ep100_bs8_lr1e-05_a0.2.pth':'8d58a6c973577234553dc0bb7d9a55df21fd62bfe7a52e0fbcc53d295e245cfd',
 'Weights/ROI_Detection/fll_detection_joints_cv_5_31.pth':'ac0e38e6a212f767e2b6b0521d8a689f179481af56c86e1acc1b31fe06a5612e',
}


def prepare(root,install=False,download=False,seal=False):
    root.mkdir(parents=True,exist_ok=True)
    runtime=root/'runtime'
    if install:
        runtime.mkdir(exist_ok=True)
        base=Path(sys.base_prefix)
        for source in base.iterdir():
            if source.is_file() and source.suffix.lower() in ('.exe','.dll','.txt'):
                shutil.copy2(source,runtime/source.name)
        for name in ('Lib','DLLs'):
            shutil.copytree(base/name,runtime/name,dirs_exist_ok=True,
                            ignore=shutil.ignore_patterns('site-packages','__pycache__','test','tests'))
        subprocess.run([str(runtime/'python.exe'),'-m','ensurepip'],check=True)
        subprocess.run([str(runtime/'python.exe'),'-m','pip','install','torch==2.8.0','torchvision==0.23.0',
                        '--index-url','https://download.pytorch.org/whl/cpu'],check=True)
        subprocess.run([str(runtime/'python.exe'),'-m','pip','install','SimpleITK==2.5.2','numpy==2.2.6'],check=True)
    if download:
        for name,expected in FILES.items():
            path=root/name
            if path.is_file() and digest(path)==expected:continue
            path.parent.mkdir(parents=True,exist_ok=True)
            request=f'https://huggingface.co/samador7/sgr-lnd-det-v1/resolve/{WEIGHT_REVISION}/{name}?download=true'
            temporary=path.with_suffix('.partial')
            with urllib.request.urlopen(request,timeout=120) as source,temporary.open('wb') as target:
                shutil.copyfileobj(source,target)
            if digest(temporary)!=expected:raise RuntimeError('Downloaded model hash mismatch.')
            temporary.replace(path)
    if seal:
        for name,expected in FILES.items():
            if digest(root/name)!=expected:raise RuntimeError('Pinned model hash mismatch.')
        source=REPO/'modules/ai_imaging/eagle_eye_alignment'
        shutil.copy2(source/'inference.py',root/'inference.py')
        shutil.copytree(source/'vendor',root/'vendor',dirs_exist_ok=True,ignore=shutil.ignore_patterns('__pycache__'))
        subprocess.run([str(runtime/'python.exe'),'-E','-s','-B','-m','pip','check'],check=True)
        included=[root/'inference.py']
        for name in ('runtime','vendor','Weights'):
            included.extend(p for p in (root/name).rglob('*') if p.is_file() and '__pycache__' not in p.parts)
        manifest=dict(format_version=1,source_revision=SOURCE_REVISION,weight_revision=WEIGHT_REVISION,
                      code_license='Apache-2.0',weights_license='CC-BY-NC-SA-4.0',
                      commercial_rights='Unresolved; obtain appropriate permission before commercial distribution.',
                      inference='CPU; four threads; offline',
                      sha256={p.relative_to(root).as_posix():digest(p) for p in sorted(included)})
        (root/'manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
        print(f'Sealed {len(included)} files. No clinical or distribution acceptance is implied.')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,default=REPO/'generated-files/eagle-eye/alignment')
    parser.add_argument('--install-runtime',action='store_true')
    parser.add_argument('--download',action='store_true');parser.add_argument('--seal',action='store_true')
    args=parser.parse_args();prepare(args.root.resolve(),args.install_runtime,args.download,args.seal)
