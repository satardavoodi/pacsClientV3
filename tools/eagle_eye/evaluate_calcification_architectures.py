"""Paired complete-image P3/P2 development evaluation with source-specific results."""
import argparse
import hashlib
import json
from pathlib import Path
import time

import torch

from calcification_p2_model import build_model
from run_calcification_pilot import evaluate


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--p3', type=Path, required=True)
    parser.add_argument('--p2', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError('Evaluation receipt already exists.')
    torch.set_num_threads(4)
    free, total = torch.cuda.mem_get_info()
    if free < 9 * 2**30:
        raise RuntimeError('Insufficient free VRAM.')
    torch.cuda.set_per_process_memory_fraction(8 * 2**30 / total)
    rows = json.loads((args.root / 'manifest.json').read_text())
    rows = [r for r in rows if r['partition'] == 'validation']
    if any(r.get('source') not in ('CBIS', 'VinDr') for r in rows):
        raise ValueError('Unknown development source.')
    groups = {'CBIS': [r for r in rows if r['source'] == 'CBIS'],
              'VinDr_positive': [r for r in rows if r['source'] == 'VinDr' and r['boxes']],
              'VinDr_control': [r for r in rows if r['source'] == 'VinDr' and not r['boxes']]}
    if not all(groups.values()):
        raise ValueError('Incomplete paired source evaluation.')
    start = time.monotonic()
    report = dict(status='paired_architecture_development_evaluation', geometry_precision='FP32',
                  convolution_precision='BF16 if supported; otherwise FP16', results={}, checkpoint_sha256={},
                  limitations=['repeated development data; unverified initial training lineage',
                               'region detection, not individual punctum segmentation',
                               'control and unmatched boxes are not confirmed clinical false positives'])
    for architecture, weights in (('p3', args.p3), ('p2', args.p2)):
        model = build_model(architecture).cuda()
        model.load_state_dict(torch.load(weights, map_location='cuda', weights_only=True), strict=True)
        report['checkpoint_sha256'][architecture] = hashlib.sha256(weights.read_bytes()).hexdigest()
        report['results'][architecture] = {name: evaluate(model, records, args.root, torch.device('cuda'), 1024)
                                           for name, records in groups.items()}
        del model
        print(json.dumps(dict(completed_architecture=architecture)), flush=True)
    report['seconds'] = time.monotonic() - start
    report['peak_vram_gib'] = torch.cuda.max_memory_allocated() / 2**30
    args.output.write_text(json.dumps(report, indent=2))
    print(json.dumps(report), flush=True)


if __name__ == '__main__':
    main()
