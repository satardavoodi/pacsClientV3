"""Isolated FCOS P2 research ablation; retain strict owned-state migration."""
import torch
from torchvision.models import resnet50
from torchvision.models.detection import fcos_resnet50_fpn
from torchvision.models.detection.anchor_utils import AnchorGenerator
from torchvision.models.detection.backbone_utils import _resnet_fpn_extractor
from torchvision.models.detection.fcos import FCOS, FCOSHead
from torchvision.ops.feature_pyramid_network import LastLevelP6P7


class Float32Anchors(AnchorGenerator):
    def set_cell_anchors(self, dtype, device):
        # BF16 cannot represent every +/-2-pixel corner near the image edge.
        super().set_cell_anchors(torch.float32, device)


class Float32GeometryHead(FCOSHead):
    def forward(self, features):
        outputs = super().forward(features)
        # BoxLinearCoder casts anchors to the regression dtype during decoding.
        outputs['bbox_regression'] = outputs['bbox_regression'].float()
        return outputs


def migrated_key(key):
    for prefix in ('backbone.fpn.inner_blocks.', 'backbone.fpn.layer_blocks.'):
        if key.startswith(prefix):
            index, suffix = key[len(prefix):].split('.', 1)
            if index not in ('0', '1', '2'):
                raise ValueError('Unexpected source FPN level.')
            return f'{prefix}{int(index) + 1}.{suffix}'
    return key


def build_model(architecture='p3', size=1024):
    if architecture == 'p3':
        model = fcos_resnet50_fpn(weights=None, weights_backbone=None, num_classes=1,
                                 min_size=size, max_size=size, score_thresh=.2, detections_per_img=100)
        model.anchor_generator = Float32Anchors(sizes=((8,), (16,), (32,), (64,), (128,)),
                                               aspect_ratios=((1.,),) * 5)
        model.head = Float32GeometryHead(256, 1, 1)
        return model
    if architecture != 'p2':
        raise ValueError('Unsupported architecture.')
    backbone = _resnet_fpn_extractor(resnet50(weights=None), 5,
                                    returned_layers=[1, 2, 3, 4], extra_blocks=LastLevelP6P7(256, 256))
    anchors = Float32Anchors(sizes=((4,), (8,), (16,), (32,), (64,), (128,)),
                              aspect_ratios=((1.,),) * 6)
    return FCOS(backbone, num_classes=1, anchor_generator=anchors, head=Float32GeometryHead(256, 1, 1), min_size=size,
                max_size=size, score_thresh=.2, detections_per_img=100)


def migrate_p3_to_p2(source, model):
    """Shift existing C3-C5 FPN blocks; initialize only the new C2 lateral/output."""
    target = model.state_dict()
    mapped = {migrated_key(key): value for key, value in source.items()}
    expected_new = {f'backbone.fpn.{block}.0.0.{parameter}'
                    for block in ('inner_blocks', 'layer_blocks') for parameter in ('weight', 'bias')}
    if set(target) - set(mapped) != expected_new or set(mapped) - set(target):
        raise ValueError('Unexpected state schema; migration refused.')
    for key, value in mapped.items():
        if value.shape != target[key].shape:
            raise ValueError(f'State shape mismatch: {key}')
    for parameter in ('weight', 'bias'):
        inner = f'backbone.fpn.inner_blocks.0.0.{parameter}'
        layer = f'backbone.fpn.layer_blocks.0.0.{parameter}'
        mapped[inner] = torch.zeros_like(target[inner])
        mapped[layer] = mapped[f'backbone.fpn.layer_blocks.1.0.{parameter}'].clone()
    model.load_state_dict(mapped, strict=True)
    return model
