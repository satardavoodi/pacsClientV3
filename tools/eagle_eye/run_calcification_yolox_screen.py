"""Bounded YOLOX-Tiny research screen; no clinical inference integration."""
import argparse
import hashlib
import json
from pathlib import Path
import random
import time

import numpy as np
from PIL import Image
import torch
from torchvision.ops import nms
from torchvision.transforms.functional import to_tensor
from yolox.models import YOLOX, YOLOPAFPN, YOLOXHead
from calcification_p2_model import build_model
from run_calcification_pilot import crop_targets, starts, iou


def targets_for_yolox(boxes, device):
    """Class zero followed by native-pixel center x/y and width/height."""
    b = torch.as_tensor(boxes, dtype=torch.float32, device=device)
    if b.ndim != 2 or b.shape[1] != 4 or not len(b) or not torch.isfinite(b).all():
        raise ValueError('Invalid positive region targets.')
    wh = b[:, 2:] - b[:, :2]
    if not (wh > 0).all():
        raise ValueError('Nonpositive region extent.')
    return torch.cat((torch.zeros((len(b), 1), device=device),
                      (b[:, :2] + b[:, 2:]) / 2, wh), dim=1).unsqueeze(0)


def tiny():
    return YOLOX(YOLOPAFPN(depth=.33, width=.375), YOLOXHead(1, width=.375))


def prediction(model, tensor, family):
    if family == 'fcos':
        return model([tensor])[0]
    # Official non-legacy YOLOX input: BGR pixels 0..255, no normalization.
    raw = model((tensor.flip(0) * 255).unsqueeze(0))[0].float()
    if not torch.isfinite(raw).all():
        raise RuntimeError('Nonfinite detector output; evaluation unavailable.')
    scores = raw[:, 4] * raw[:, 5]
    keep = scores >= .01
    raw, scores = raw[keep], scores[keep]
    boxes = torch.cat((raw[:, :2] - raw[:, 2:4] / 2,
                       raw[:, :2] + raw[:, 2:4] / 2), dim=1)
    keep = nms(boxes, scores, .5)[:100]
    return {'boxes': boxes[keep], 'scores': scores[keep]}


def evaluate(model, family, rows, root, image_transform=None):
    thresholds = [.01, .03, .05, .1, .15, .2, .25, .3, .35, .4, .45,
                  .5, .6, .7, .8, .9, .95]
    result = {group: {str(t): {'targets': 0, 'matched': 0, 'predictions': 0}
                         for t in thresholds}
              for group in ('CBIS', 'VinDr_positive', 'VinDr_control')}
    model.eval()
    start = time.monotonic()
    tiles = 0
    with torch.inference_mode():
        for row in rows:
            image = Image.open(root / row['image']).convert('RGB')
            if image_transform is not None:
                image = image_transform(image)
            boxes, scores = [], []
            for y in starts(image.height, 1024):
                for x in starts(image.width, 1024):
                    tensor = to_tensor(image.crop((x, y, x+1024, y+1024))).cuda()
                    # Both candidates evaluated in FP32 for geometric parity.
                    output = prediction(model, tensor, family)
                    boxes.append(output['boxes'].float().cpu() + torch.tensor([x, y]*2))
                    scores.append(output['scores'].float().cpu())
                    tiles += 1
            b, s = torch.cat(boxes), torch.cat(scores)
            keep = nms(b, s, .5)
            b, s = b[keep].numpy(), s[keep].numpy()
            group = 'CBIS' if row['source'] == 'CBIS' else (
                'VinDr_positive' if row['boxes'] else 'VinDr_control')
            for threshold in thresholds:
                selected = b[s >= threshold]
                remaining = list(range(len(selected)))
                matched = 0
                for target in row['boxes']:
                    candidates = [(iou(np.asarray(target), selected[j]), j) for j in remaining]
                    if candidates and max(candidates)[0] >= .5:
                        matched += 1
                        remaining.remove(max(candidates)[1])
                totals = result[group][str(threshold)]
                totals['targets'] += len(row['boxes'])
                totals['matched'] += matched
                totals['predictions'] += len(selected)
    return {'groups': result, 'seconds': time.monotonic()-start,
            'images': len(rows), 'tiles': tiles, 'precision': 'FP32',
            'tile_prediction_cap': 100, 'proposal_floor': .01}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--pretrained', type=Path, required=True)
    parser.add_argument('--baseline', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--steps', type=int, default=512)
    parser.add_argument('--learning-rate', type=float, default=1e-4)
    parser.add_argument('--adapt-batchnorm', action='store_true')
    args = parser.parse_args()
    if (args.output.exists() or args.output.with_suffix('.pth').exists()
            or not 1 <= args.steps <= 4096 or not 0 < args.learning_rate <= .001):
        raise ValueError('Invalid budget or existing output.')
    torch.set_num_threads(4)
    torch.manual_seed(20261001)
    random.seed(20261001)
    free, total = torch.cuda.mem_get_info()
    if free < 9*2**30:
        raise RuntimeError('Insufficient free VRAM.')
    torch.cuda.set_per_process_memory_fraction(8*2**30/total)
    rows = json.loads((args.root/'manifest.json').read_text())
    train = [r for r in rows if r['partition'] == 'train']
    validation = [r for r in rows if r['partition'] == 'validation']
    if not train or not validation or any(not r['boxes'] for r in train):
        raise ValueError('Missing cohort or unreviewed negative training target.')
    model = tiny().cuda()
    source = torch.load(args.pretrained, map_location='cpu', weights_only=True)['model']
    target = model.state_dict()
    skipped = [k for k in source if k.startswith('head.cls_preds.')]
    if set(source) != set(target) or len(skipped) != 6:
        raise ValueError('Unexpected pretrained schema.')
    for key in target:
        if key in skipped:
            continue
        if source[key].shape != target[key].shape:
            raise ValueError('Unexpected pretrained tensor shape.')
        target[key] = source[key]
    model.load_state_dict(target, strict=True)
    model.head.initialize_biases(.01)
    optimizer = torch.optim.AdamW(model.parameters(), lr=args.learning_rate, weight_decay=1e-4)
    losses, used = [], set()
    started = time.monotonic()
    rejected = 0
    for step in range(args.steps):
        if time.monotonic() - started > 7200:
            raise RuntimeError('Initial training screen exceeded two-hour budget.')
        attempts = 0
        while True:
            row = train[(step+attempts) % len(train)]
            image = Image.open(args.root/row['image']).convert('RGB')
            box = random.choice(row['boxes'])
            x = int(max(0, min(max(0, image.width-1024),
                              (box[0]+box[2])/2-512+random.uniform(-.15,.15)*1024)))
            y = int(max(0, min(max(0, image.height-1024),
                              (box[1]+box[3])/2-512+random.uniform(-.15,.15)*1024)))
            try:
                boxes = crop_targets(row['boxes'], (x,y,1024))
                break
            except ValueError:
                rejected += 1
                attempts += 1
                if attempts > len(train):
                    raise RuntimeError('No admissible positive crop.')
        tensor = to_tensor(image.crop((x,y,x+1024,y+1024))).cuda().flip(0)*255
        model.train()
        if not args.adapt_batchnorm:
            for module in model.modules():
                if isinstance(module, torch.nn.BatchNorm2d):
                    module.eval()
        optimizer.zero_grad(set_to_none=True)
        parts = model(tensor.unsqueeze(0), targets_for_yolox(boxes, 'cuda'))
        loss = parts['total_loss']
        if not torch.isfinite(loss):
            raise RuntimeError('Nonfinite training loss.')
        loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), 5, error_if_nonfinite=True)
        optimizer.step()
        losses.append(float(loss.detach()))
        used.add(row['image'])
        if (step+1) % 64 == 0:
            print(json.dumps({'steps':step+1, 'loss':losses[-1],
                              'peak_gib':torch.cuda.max_memory_allocated()/2**30}), flush=True)
    checkpoint = args.output.with_suffix('.pth')
    torch.save(model.state_dict(), checkpoint)
    model.load_state_dict(torch.load(checkpoint, weights_only=True), strict=True)
    report = {'status':'completed_bounded_development_screen', 'steps':args.steps,
              'training_seconds':time.monotonic()-started, 'actual_sources':len(used),
              'rejected_crops':rejected, 'losses_first10':losses[:10], 'losses_last10':losses[-10:],
              'initialization':'official COCO Tiny; classification projections replaced',
              'parameters':sum(p.numel() for p in model.parameters()),
              'learning_rate':args.learning_rate, 'training_precision':'FP32',
              'batchnorm_policy':'adapt' if args.adapt_batchnorm else 'frozen',
              'checkpoint_sha256':hashlib.sha256(checkpoint.read_bytes()).hexdigest(),
              'pretrained_sha256':hashlib.sha256(args.pretrained.read_bytes()).hexdigest(),
              'manifest_sha256':hashlib.sha256((args.root/'manifest.json').read_bytes()).hexdigest(),
              'limitations':['positive-only region labels; background annotations incomplete',
                            'different initialization lineage and tuning budget; not architecture-only proof',
                            'repeated development cohort; no independent test',
                            'controls are not confirmed calcification-free; no specificity claim']}
    report['yolox'] = evaluate(model, 'yolox', validation, args.root)
    del model, optimizer
    torch.cuda.empty_cache()
    baseline = build_model('p3').cuda()
    baseline.score_thresh = .01
    baseline.load_state_dict(torch.load(args.baseline, map_location='cuda', weights_only=True), strict=True)
    report['fcos'] = evaluate(baseline, 'fcos', validation, args.root)
    report['baseline_sha256'] = hashlib.sha256(args.baseline.read_bytes()).hexdigest()
    report['peak_vram_gib'] = torch.cuda.max_memory_allocated()/2**30
    report['torch_version'] = torch.__version__
    args.output.write_text(json.dumps(report, indent=2))
    print(json.dumps({'status':report['status'], 'receipt':args.output.name}), flush=True)


if __name__ == '__main__':
    main()
