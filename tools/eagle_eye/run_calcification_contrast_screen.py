"""Label-blind whole-image contrast ablation and finite YOLO evaluation check."""
import argparse
import hashlib
import json
from pathlib import Path

import cv2
import numpy as np
from PIL import Image
import torch

from calcification_p2_model import build_model
from run_calcification_yolox_screen import tiny, evaluate


def full_image_clahe(image):
    # Apply once before tiling; never use ROI annotations to select pixels.
    pixels = np.asarray(image.convert('L'), dtype=np.uint8)
    result = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(pixels)
    return Image.fromarray(result).convert('RGB')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--fcos', type=Path, required=True)
    parser.add_argument('--yolox', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError('Existing research receipt.')
    torch.set_num_threads(4)
    free, total = torch.cuda.mem_get_info()
    if free < 9*2**30:
        raise RuntimeError('Insufficient free VRAM.')
    torch.cuda.set_per_process_memory_fraction(8*2**30/total)
    rows = json.loads((args.root/'manifest.json').read_text())
    rows = [r for r in rows if r['partition'] == 'validation']
    yolo = tiny().cuda()
    yolo.load_state_dict(torch.load(args.yolox, map_location='cuda', weights_only=True), strict=True)
    report = {'yolox_finite_output_recheck':evaluate(yolo, 'yolox', rows, args.root)}
    del yolo
    torch.cuda.empty_cache()
    fcos = build_model('p3').cuda()
    fcos.score_thresh = .01
    fcos.load_state_dict(torch.load(args.fcos, map_location='cuda', weights_only=True), strict=True)
    report['fcos_full_image_clahe'] = evaluate(fcos, 'fcos', rows, args.root, full_image_clahe)
    report.update(status='completed_label_blind_development_ablation',
                  preprocessing='whole image grayscale CLAHE clipLimit=2, grid=8x8 before native tiling',
                  peak_vram_gib=torch.cuda.max_memory_allocated()/2**30,
                  checkpoint_sha256={name:hashlib.sha256(path.read_bytes()).hexdigest()
                                     for name,path in [('fcos',args.fcos),('yolox',args.yolox)]},
                  limitations=['contrast-only inference shift; no contrast-aware retraining',
                               'repeated small development cohort; no independent clinical evidence',
                               'region boxes, not individual punctum truth',
                               'unknown controls; output burden is not confirmed false-positive rate'])
    args.output.write_text(json.dumps(report, indent=2))
    print(json.dumps({'status':report['status']}), flush=True)


if __name__ == '__main__':
    main()
