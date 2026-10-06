"""Reproduce BF16 P2 anchor collapse and verify the research FP32 geometry fix."""
import argparse
import json
from pathlib import Path

import torch
from torchvision.models.detection.anchor_utils import AnchorGenerator
from torchvision.models.detection.image_list import ImageList

from calcification_p2_model import Float32Anchors, build_model, migrate_p3_to_p2


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--weights', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError('Guard receipt already exists.')
    torch.set_num_threads(4)
    free, total = torch.cuda.mem_get_info()
    if free < 9 * 2**30:
        raise RuntimeError('Insufficient free VRAM.')
    torch.cuda.set_per_process_memory_fraction(8 * 2**30 / total)
    images = ImageList(torch.zeros(1, 3, 1024, 1024, device='cuda'), [(1024, 1024)])
    features = [torch.zeros(1, 1, 1024 // s, 1024 // s, dtype=torch.bfloat16, device='cuda')
                for s in (4, 8, 16, 32, 64, 128)]
    kwargs = dict(sizes=tuple((s,) for s in (4, 8, 16, 32, 64, 128)), aspect_ratios=((1.,),) * 6)
    legacy = AnchorGenerator(**kwargs)(images, features)[0]
    fixed = Float32Anchors(**kwargs)(images, features)[0]
    collapsed = int(((legacy[:, 2:] - legacy[:, :2]) <= 0).any(dim=1).sum())
    assert collapsed > 0, 'The uncorrected BF16 geometry must reproduce the failure.'
    assert fixed.dtype == torch.float32 and ((fixed[:, 2:] - fixed[:, :2]) > 0).all()
    state = torch.load(args.weights, weights_only=True, map_location='cpu')
    model = migrate_p3_to_p2(state, build_model('p2')).cuda().train()
    for module in model.modules():
        if isinstance(module, torch.nn.BatchNorm2d):
            module.eval()
    with torch.autocast('cuda', dtype=torch.bfloat16):
        loss = sum(model([torch.rand(3, 1024, 1024, device='cuda')], [dict(
            boxes=torch.tensor([[900., 900., 920., 920.]], device='cuda'),
            labels=torch.zeros(1, dtype=torch.int64, device='cuda'))]).values())
    assert torch.isfinite(loss)
    loss.backward()
    assert torch.isfinite(model.backbone.fpn.inner_blocks[0][0].weight.grad).all()
    report = dict(status='float32_geometry_regression_guard_passed', legacy_degenerate_anchors=collapsed,
                  fixed_degenerate_anchors=0, finite_bf16_1024_training_loss=float(loss.detach()),
                  peak_vram_gib=torch.cuda.max_memory_allocated() / 2**30)
    args.output.write_text(json.dumps(report, indent=2))
    print(json.dumps(report))


if __name__ == '__main__':
    main()
