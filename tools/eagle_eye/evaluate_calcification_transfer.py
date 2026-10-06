"""Aggregate paired digital transfer evaluation; unmatched boxes are not clinical FP truth."""
import argparse
import json
from pathlib import Path

import torch

from run_calcification_pilot import evaluate
from calcification_p2_model import build_model


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--baseline', type=Path, required=True)
    parser.add_argument('--candidate', type=Path, required=True)
    parser.add_argument('--candidate-architecture', choices=('p3', 'p2'), default='p3')
    args = parser.parse_args()
    torch.set_num_threads(4)
    free, total = torch.cuda.mem_get_info()
    if free < 9 * 2**30:
        raise RuntimeError('Insufficient free VRAM.')
    torch.cuda.set_per_process_memory_fraction(8 * 2**30 / total)
    records = json.loads((args.root / 'manifest.json').read_text())
    report = dict(protocol='development digital transfer; checkpoint lineage unverified; no clinical FP claim',
                  images=len(records), results={})
    for label, weights in (('baseline', args.baseline), ('candidate', args.candidate)):
        model = build_model('p3' if label == 'baseline' else args.candidate_architecture).cuda()
        model.load_state_dict(torch.load(weights, map_location='cuda', weights_only=True), strict=True)
        report['results'][label] = {
            'calcification_positive': evaluate(model, [r for r in records if r['boxes']], args.root, torch.device('cuda'), 1024),
            'no_finding_control': evaluate(model, [r for r in records if not r['boxes']], args.root, torch.device('cuda'), 1024)}
        del model
    (args.root / 'transfer-result.json').write_text(json.dumps(report, indent=2))
    print(json.dumps(report))


if __name__ == '__main__':
    main()
