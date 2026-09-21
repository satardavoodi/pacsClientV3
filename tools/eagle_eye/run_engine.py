"""Run a prepared local engine or an actual-model synthetic smoke test."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from modules.ai_imaging.eagle_eye_engines.service import run

if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('engine', choices=('breast', 'bone-age'))
    p.add_argument('--study-uid', default='1.2.826.0.1.3680043.10.543.921')
    p.add_argument('--dicom', nargs='*', default=[])
    p.add_argument('--sex', choices=('M', 'F'))
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--smoke', action='store_true')
    a = p.parse_args()
    result = run(a.engine, a.dicom, a.study_uid, a.output, sex=a.sex, smoke=a.smoke)
    print(json.dumps({'status': result['status'], 'synthetic': result['synthetic'],
                      'engine': a.engine, 'image_count': result['image_count']}))
