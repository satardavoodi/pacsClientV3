"""Synthetic optimizer/checkpoint proof for an isolated calcification FCOS candidate.

Never reads clinical images and does not demonstrate diagnostic accuracy.
"""
import argparse
import hashlib
import json
from pathlib import Path
import time

import torch
from torchvision.models.detection import fcos_resnet50_fpn


def model_for_size(size):
    return fcos_resnet50_fpn(weights=None, weights_backbone=None, num_classes=1,
                            min_size=size, max_size=size)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--weights', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError('Refusing to replace candidate evidence.')
    torch.set_num_threads(4)
    torch.manual_seed(20261001)
    start = time.monotonic()
    model = model_for_size(128)
    model.load_state_dict(torch.load(args.weights, map_location='cpu', weights_only=True), strict=True)
    model.train()
    optimizer = torch.optim.AdamW(model.parameters(), lr=1e-5)
    before = model.head.classification_head.cls_logits.bias.detach().clone()
    images = [torch.rand(3, 128, 128), torch.rand(3, 128, 128)]
    targets = [dict(boxes=torch.tensor([[20., 20., 40., 40.], [65., 60., 90., 95.]]),
                    labels=torch.tensor([0, 0], dtype=torch.int64)),
               dict(boxes=torch.empty((0, 4)), labels=torch.empty((0,), dtype=torch.int64))]
    losses = model(images, targets)
    loss = sum(losses.values())
    if not torch.isfinite(loss) or loss.item() <= 0:
        raise RuntimeError('Invalid synthetic training loss.')
    optimizer.zero_grad(set_to_none=True)
    loss.backward()
    if not all(torch.isfinite(parameter.grad).all() for parameter in model.parameters() if parameter.grad is not None):
        raise RuntimeError('Nonfinite training gradient.')
    optimizer.step()
    if torch.equal(before, model.head.classification_head.cls_logits.bias.detach()):
        raise RuntimeError('Optimizer did not update the detector head.')
    args.output.mkdir(parents=True, exist_ok=False)
    checkpoint = args.output / 'synthetic-only-checkpoint.pth'
    torch.save(model.state_dict(), checkpoint)
    restored = model_for_size(128)
    restored.load_state_dict(torch.load(checkpoint, map_location='cpu', weights_only=True), strict=True)
    for key, value in model.state_dict().items():
        if not torch.equal(value.cpu(), restored.state_dict()[key].cpu()):
            raise RuntimeError('Checkpoint restore changed tensors.')
    restored.eval()
    with torch.inference_mode():
        prediction = restored([images[0]])[0]
    if not all(torch.isfinite(prediction[key]).all() for key in ('boxes', 'scores')):
        raise RuntimeError('Nonfinite reloaded inference.')
    report = dict(status='synthetic_optimizer_and_checkpoint_passed',
                  trained_medical_model=False, input_size=128, foreground_channels=1,
                  positive_boxes=2, empty_target_images=1, optimizer_steps=1,
                  losses={key: float(value.detach()) for key, value in losses.items()},
                  initialization_sha256=hashlib.sha256(args.weights.read_bytes()).hexdigest(),
                  torch_version=torch.__version__, seconds=time.monotonic() - start,
                  qualification='synthetic smoke only; native-1024 GPU capacity and real-data training pending')
    (args.output / 'aggregate.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report), flush=True)


if __name__ == '__main__':
    main()
