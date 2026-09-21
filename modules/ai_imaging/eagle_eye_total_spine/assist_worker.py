"""Offline subprocess entry point. Never import torch into the PACS GUI process."""
from pathlib import Path
import json
import sys


def sam_mask(root, pixels, box):
    import numpy as np
    import torch
    sys.path.insert(0, str(root))
    from segment_anything import sam_model_registry, SamPredictor
    model = sam_model_registry['vit_b'](checkpoint=None)
    model.load_state_dict(torch.load(root/'sam_vit_b.pth', map_location='cpu', weights_only=True), strict=True)
    model.eval()
    predictor = SamPredictor(model)
    predictor.set_image(np.repeat(pixels[:, :, None], 3, axis=2))
    with torch.inference_mode():
        masks, scores, _ = predictor.predict(box=np.asarray(box), multimask_output=False)
    return masks[0], float(scores[0])


def scoliovis(root, pixels):
    import numpy as np
    import torch
    import torchvision
    from torchvision.models.detection.rpn import AnchorGenerator
    # Same anchor layout and four-keypoint/two-class heads as upstream. No
    # pretrained backbone request: the released state dictionary supplies it.
    anchors = AnchorGenerator(sizes=(32, 64, 128, 256, 512),
                              aspect_ratios=(.25, .5, .75, 1., 2., 3., 4.))
    model = torchvision.models.detection.keypointrcnn_resnet50_fpn(
        weights=None, weights_backbone=None, num_keypoints=4, num_classes=2,
        rpn_anchor_generator=anchors)
    model.load_state_dict(torch.load(root/'scoliovis.pt', map_location='cpu', weights_only=True), strict=True)
    model.eval()
    tensor = torch.from_numpy(np.repeat(pixels[None], 3, axis=0).astype(np.float32)/255.)
    with torch.inference_mode():
        output = model([tensor])[0]
    indices = torch.where(output['scores'] > .5)[0]
    indices = indices[torchvision.ops.nms(output['boxes'][indices], output['scores'][indices], .3)]
    # Keep scores and keypoints indexed together. Do not silently truncate extra
    # detections into a fabricated 17-vertebra sequence.
    candidates = [dict(corners=output['keypoints'][i, :, :2].tolist(),
                       confidence=float(output['scores'][i])) for i in indices]
    candidates.sort(key=lambda item: np.mean(item['corners'], axis=0)[1])
    return dict(candidates=candidates, model='ScolioVis Keypoint R-CNN (AP research model)',
                anatomical_labels_predicted=False,
                preprocessing='grayscale RGB /255; torchvision detector resize/normalization')


def main():
    import numpy as np
    import torch
    torch.set_num_threads(4)
    root, folder = map(Path, sys.argv[1:3])
    request = json.loads((folder/'request.json').read_text(encoding='utf-8'))
    pixels = np.load(folder/'input.npy', allow_pickle=False)
    if pixels.ndim != 2 or pixels.dtype != np.uint8 or pixels.size > 80_000_000:
        raise ValueError('Expected bounded grayscale pixels.')
    if request['mode'] == 'sam':
        mask, score = sam_mask(root, pixels, request['box'])
        np.save(folder/'mask.npy', mask.astype(bool), allow_pickle=False)
        result = dict(score=score)
    elif request['mode'] == 'scoliovis':
        result = scoliovis(root, pixels)
    else:
        raise ValueError('Unknown local inference mode.')
    (folder/'result.json').write_text(json.dumps(result, allow_nan=False), encoding='utf-8')


if __name__ == '__main__':
    main()
