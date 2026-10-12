"""Stage a sealed calcium candidate alongside Breast; never overwrite a bundle."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil


def prepare(assets, deps, destination):
    from tools.eagle_eye.calcium_candidate import FROZEN, digest
    destination=Path(destination)
    if destination.exists():
        raise ValueError('Select a new immutable calcium destination.')
    for name, expected in FROZEN.items():
        if digest(Path(assets)/name)!=expected:
            raise ValueError('Frozen calcium assets differ.')
    destination.mkdir(parents=True)
    (destination/'assets').mkdir()
    for name in FROZEN:
        shutil.copyfile(Path(assets)/name,destination/'assets'/name)
    shutil.copytree(deps,destination/'deps',ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    shutil.copyfile(Path(__file__).with_name('calcium_candidate.py'),destination/'runner.py')
    shutil.copyfile(Path(__file__).with_name('physical_peaks_fast.py'),destination/'physical_peaks_fast.py')
    hashes={p.relative_to(destination).as_posix():digest(p) for p in sorted(destination.rglob('*')) if p.is_file()}
    manifest=dict(format='breast_calcium_v1',revision='b95-frozen-b25-b33-exact-peaks-v1', threads=4,
                  qualification='research_only',sha256=hashes)
    (destination/'manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    print(json.dumps(dict(files=len(hashes),qualification='research_only')))


if __name__=='__main__':
    import sys
    sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('assets','deps','destination'):parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args();prepare(args.assets,args.deps,args.destination)
