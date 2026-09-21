"""Isolated CPU entry point for the ISBI 2020 vertebra landmark checkpoint."""
from pathlib import Path
import json
import sys

SOURCE_REVISION = 'b9fc05c215ea2b006564a3feb509634183a63f82'
WEIGHT_SHA256 = '6a779e01b9a41601334e0a9541278fc557a95bd650c6c8de311204821509d19b'


def infer(bundle, pixels):
    import numpy as np
    import torch
    from PIL import Image
    sys.path.insert(0, str(bundle))
    from models.spinal_net import SpineNet
    from decoder import DecDecoder

    torch.set_num_threads(4)
    model = SpineNet({'hm': 1, 'reg': 2, 'wh': 8}, pretrained=False,
                     down_ratio=4, final_kernel=1, head_conv=256)
    checkpoint = torch.load(bundle/'model_last.pth', map_location='cpu', weights_only=True)
    model.load_state_dict(checkpoint['state_dict'], strict=True)
    model.eval()
    # Grayscale replicated into RGB. PIL bilinear is deterministic and avoids
    # introducing OpenCV into the shared portable runtime.
    resized = np.asarray(Image.fromarray(pixels).resize((512, 1024), Image.Resampling.BILINEAR), dtype=np.float32)
    tensor = torch.from_numpy(np.repeat((resized/255.-.5)[None, None], 3, axis=1))
    with torch.inference_mode():
        output = model(tensor)
        decoded = DecDecoder(K=17, conf_thresh=.2).ctdet_decode(output['hm'], output['wh'], output['reg'])
    h, w = pixels.shape
    candidates = []
    for row in decoded[np.argsort(decoded[:, 1])]:
        corners = row[2:10].reshape(4, 2) * np.array([w/128., h/256.])
        candidates.append({'corners': corners.tolist(), 'confidence': float(row[10])})
    return {'candidates': candidates, 'source_revision': SOURCE_REVISION,
            'weight_sha256': WEIGHT_SHA256, 'model': 'Yi et al. ISBI 2020',
            'preprocessing': 'grayscale RGB; PIL bilinear 512x1024; /255 - 0.5',
            'anatomical_labels_predicted': False}


if __name__ == '__main__':
    import numpy as np
    root, source, destination = map(Path, sys.argv[1:4])
    image = np.load(source, allow_pickle=False)
    if image.ndim != 2 or image.dtype != np.uint8 or image.size > 80_000_000:
        raise ValueError('Expected a bounded uint8 radiograph.')
    destination.write_text(json.dumps(infer(root, image), allow_nan=False), encoding='utf-8')
