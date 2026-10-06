"""Bounded real-data FCOS region pilot; aggregate exploratory before/after evaluation."""
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
from torchvision.transforms import functional as TF
from calcification_p2_model import build_model, migrate_p3_to_p2


def crop_targets(boxes, window, minimum_fraction=.2):
    x, y, size = window
    result = []
    for raw in boxes:
        box = np.asarray(raw, dtype=float)
        lo = np.maximum(box[:2], [x, y]); hi = np.minimum(box[2:], [x + size, y + size])
        if np.any(hi <= lo):
            continue
        fraction = np.prod(hi - lo) / np.prod(box[2:] - box[:2])
        if fraction < minimum_fraction or np.min(hi - lo) < 4:
            raise ValueError('Ambiguous partial target; crop rejected.')
        result.append([*(lo - [x, y]), *(hi - [x, y])])
    if not result:
        raise ValueError('No positive target; unknown background is not a negative.')
    return result


def starts(length, size):
    return sorted(set(list(range(0, max(1, length - size + 1), size * 3 // 4)) + [max(0, length - size)]))


def iou(a, b):
    intersection = np.maximum(np.minimum(a[2:], b[2:]) - np.maximum(a[:2], b[:2]), 0).prod()
    union = np.prod(a[2:] - a[:2]) + np.prod(b[2:] - b[:2]) - intersection
    return intersection / union if union else 0


def evaluate(model, records, root, device, size):
    model.eval()
    totals = {str(t): dict(targets=0, matched=0, predictions=0, unmatched_predictions=0)
              for t in (.3, .4, .45)}
    with torch.inference_mode():
        for record in records:
            image = Image.open(root / record['image']).convert('RGB')
            boxes, scores = [], []
            for top in starts(image.height, size):
                for left in starts(image.width, size):
                    tile = TF.to_tensor(image.crop((left, top, left + size, top + size))).to(device)
                    with torch.autocast('cuda', dtype=torch.bfloat16 if torch.cuda.is_bf16_supported() else torch.float16):
                        prediction = model([tile])[0]
                    box = prediction['boxes'].float().cpu() + torch.tensor([left, top] * 2)
                    boxes.append(box); scores.append(prediction['scores'].float().cpu())
            boxes, scores = torch.cat(boxes), torch.cat(scores)
            keep = nms(boxes, scores, .5)
            boxes, scores = boxes[keep].numpy(), scores[keep].numpy()
            for threshold, values in totals.items():
                predictions = boxes[scores >= float(threshold)]
                remaining = list(range(len(predictions))); matched = 0
                for target in record['boxes']:
                    candidates = [(iou(np.asarray(target), predictions[j]), j) for j in remaining]
                    if candidates and max(candidates)[0] >= .5:
                        matched += 1; remaining.remove(max(candidates)[1])
                values['targets'] += len(record['boxes']); values['matched'] += matched
                values['predictions'] += len(predictions)
                values['unmatched_predictions'] += len(predictions) - matched
    return totals


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--steps', type=int, default=100)
    parser.add_argument('--size', type=int, default=1024)
    parser.add_argument('--eval-every', type=int, default=0,
                        help='Save and evaluate intermediate research checkpoints; zero disables.')
    parser.add_argument('--learning-rate', type=float, default=1e-5)
    parser.add_argument('--architecture', choices=('p3', 'p2'), default='p3')
    parser.add_argument('--initialization-architecture', choices=('p3', 'p2'), default='p3')
    args = parser.parse_args()
    if args.steps < 1 or args.size < 32 or args.eval_every < 0 or not 0 < args.learning_rate <= .001:
        raise ValueError('Invalid training budget or input size.')
    root = args.root
    if (root / 'pilot-result.json').exists():
        raise FileExistsError('Pilot result already exists.')
    torch.set_num_threads(4); torch.manual_seed(20261001); random.seed(20261001)
    if not torch.cuda.is_available():
        raise RuntimeError('CUDA worker unavailable.')
    free, total = torch.cuda.mem_get_info()
    if free < 9 * 2**30:
        raise RuntimeError('Insufficient free VRAM for bounded pilot.')
    torch.cuda.set_per_process_memory_fraction(8 * 2**30 / total)
    device = torch.device('cuda')
    records = json.loads((root / 'manifest.json').read_text())
    training = [r for r in records if r['partition'] == 'train']
    validation = [r for r in records if r['partition'] == 'validation']
    if {r['person_key'] for r in training} & {r['person_key'] for r in validation}:
        raise ValueError('Pilot person leakage.')
    model = build_model(args.architecture, args.size)
    state = torch.load(root / 'initialization.pth', weights_only=True, map_location='cpu')
    if args.architecture == 'p2' and args.initialization_architecture == 'p3':
        migrate_p3_to_p2(state, model)
    elif args.architecture == args.initialization_architecture:
        model.load_state_dict(state, strict=True)
    else:
        raise ValueError('Unsupported initialization migration.')
    model.to(device)
    start = time.monotonic()
    baseline = evaluate(model, validation, root, device, args.size)
    (root / 'baseline.json').write_text(json.dumps(baseline))
    optimizer = torch.optim.AdamW(model.parameters(), lr=args.learning_rate, weight_decay=1e-4)
    bf16 = torch.cuda.is_bf16_supported()
    scaler = torch.amp.GradScaler('cuda', enabled=not bf16)
    initial_head = model.head.classification_head.cls_logits.bias.detach().clone()
    used_sources = set()
    losses = []
    successful = 0
    rejected = 0
    intervals = []
    while successful < args.steps:
        if rejected > args.steps * 20:
            raise RuntimeError('Too many ambiguous crops.')
        record = training[successful % len(training)]
        image = Image.open(root / record['image']).convert('RGB')
        target = random.choice(record['boxes'])
        cx, cy = (target[0] + target[2]) / 2, (target[1] + target[3]) / 2
        left = int(max(0, min(max(0, image.width - args.size), cx - args.size / 2 + random.uniform(-.15, .15) * args.size)))
        top = int(max(0, min(max(0, image.height - args.size), cy - args.size / 2 + random.uniform(-.15, .15) * args.size)))
        try:
            boxes = crop_targets(record['boxes'], (left, top, args.size))
        except ValueError:
            rejected += 1
            # Move past a source whose large region cannot fit this pilot input.
            training = training[1:] + training[:1]
            continue
        tensor = TF.to_tensor(image.crop((left, top, left + args.size, top + args.size))).to(device)
        targets = [dict(boxes=torch.tensor(boxes, dtype=torch.float32, device=device),
                        labels=torch.zeros(len(boxes), dtype=torch.int64, device=device))]
        model.train()
        for module in model.modules():
            if isinstance(module, torch.nn.BatchNorm2d):
                module.eval()  # Preserve running statistics in a one-image pilot.
        optimizer.zero_grad(set_to_none=True)
        with torch.autocast('cuda', dtype=torch.bfloat16 if bf16 else torch.float16):
            components = model([tensor], targets)
            loss = sum(components.values())
        if not torch.isfinite(loss):
            raise RuntimeError('Nonfinite loss.')
        scaler.scale(loss).backward(); scaler.unscale_(optimizer)
        norm = torch.nn.utils.clip_grad_norm_(model.parameters(), 5., error_if_nonfinite=True)
        old_scale = scaler.get_scale()
        scaler.step(optimizer); scaler.update()
        if scaler.get_scale() < old_scale:
            raise RuntimeError('Mixed-precision optimizer step skipped.')
        successful += 1
        used_sources.add(record['image'])
        losses.append({key: float(value.detach()) for key, value in components.items()})
        if successful % 10 == 0:
            print(json.dumps(dict(optimizer_steps=successful, loss=float(loss.detach()),
                                  peak_vram_gib=torch.cuda.max_memory_allocated() / 2**30)), flush=True)
        if args.eval_every and successful % args.eval_every == 0:
            interval_path = root / f'research-step-{successful}.pth'
            torch.save({key: value.cpu() for key, value in model.state_dict().items()}, interval_path)
            # Reload the exact saved state before recording its evaluation.
            model.load_state_dict(torch.load(interval_path, map_location=device, weights_only=True), strict=True)
            metrics = evaluate(model, validation, root, device, args.size)
            interval = dict(optimizer_steps=successful, metrics=metrics,
                            checkpoint_sha256=hashlib.sha256(interval_path.read_bytes()).hexdigest())
            intervals.append(interval)
            (root / 'interval-results.json').write_text(json.dumps(intervals, indent=2))
            print(json.dumps(dict(interval_evaluation=interval)), flush=True)
    checkpoint = root / 'research-calcification-pilot.pth'
    if torch.equal(initial_head, model.head.classification_head.cls_logits.bias.detach()):
        raise RuntimeError('Detector head did not change.')
    torch.save({key: value.cpu() for key, value in model.state_dict().items()}, checkpoint)
    model.load_state_dict(torch.load(checkpoint, map_location=device, weights_only=True), strict=True)
    final = evaluate(model, validation, root, device, args.size)
    report = dict(status='real_data_research_pilot_completed', optimizer_steps=successful,
                  rejected_crops=rejected, train_images=len(training), validation_images=len(validation),
                  baseline=baseline, candidate=final, losses_first10=losses[:10], losses_last10=losses[-10:],
                  interval_evaluations=intervals, checkpoint_policy='preserve intervals; final is not automatically best',
                  learning_rate=args.learning_rate, manifest_sha256=hashlib.sha256((root / 'manifest.json').read_bytes()).hexdigest(),
                  architecture=args.architecture, initialization_architecture=args.initialization_architecture,
                  input_size=args.size, peak_vram_gib=torch.cuda.max_memory_allocated() / 2**30,
                  precision='BF16' if bf16 else 'FP16', actual_training_sources=len(used_sources),
                  seconds=time.monotonic() - start, torch_version=torch.__version__,
                  checkpoint_sha256=hashlib.sha256(checkpoint.read_bytes()).hexdigest(),
                  limitations=['positive-only small development pilot; no reviewed normal cohort',
                               'unmatched boxes are not confirmed clinical false positives',
                               'converted JPEG region annotations; not individual-punctum labels',
                               'unknown initialization lineage; no independent accuracy or promotion claim'])
    (root / 'pilot-result.json').write_text(json.dumps(report, indent=2))
    print(json.dumps(report), flush=True)


if __name__ == '__main__':
    main()
