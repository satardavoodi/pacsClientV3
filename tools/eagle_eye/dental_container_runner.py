"""Fixed container stdin protocol; no DICOM, identifiers, network, or arbitrary code."""
import base64
import contextlib
import io
import json
from pathlib import Path
import sys
from PIL import Image

DIGEST = 'sha256:74a722b3fb62f5b3f7f08820bfac9a21c1ffbe357311f22f9e1e187129204147'


def main():
    data = sys.stdin.buffer.read(32 * 1024**2 + 1)
    if len(data) > 32 * 1024**2:
        raise ValueError('Input too large')
    request = json.loads(data)
    if set(request) != {'protocol', 'image_png'} or request['protocol'] != 1:
        raise ValueError('Unsupported worker protocol')
    image = Image.open(io.BytesIO(base64.b64decode(request['image_png'], validate=True)))
    if image.format != 'PNG' or image.width * image.height > 24_000_000:
        raise ValueError('Unsupported worker image')
    import numpy as np
    sys.path.insert(0, '/app')
    # Upstream writes progress banners to stdout; protocol stdout must be pure JSON.
    with contextlib.redirect_stdout(sys.stderr):
        import main as upstream
        pixels = np.asarray(image.convert('RGB'))
        semantic = upstream.SemanticSegmentationModule(config_path='/app/models/deeplab/config.yaml', weights_path='/app/models/deeplab/model.pth')
        detector = upstream.InstanceDetectionModule(config_path='/app/models/yolo/config.yaml', weights_path='/app/models/yolo/model.pt')
        first = semantic(pixels, Path('/tmp'))
        second = detector(pixels, Path('/tmp'))
        result = upstream.PostProcessingModule()(first, second)
    rows = [{'fdi': row.fdi, 'finding': row.finding.name, 'score': float(row.score)} for row in result]
    print(json.dumps({'model_digest': DIGEST, 'rows': rows}, allow_nan=False))


if __name__ == '__main__':
    main()
