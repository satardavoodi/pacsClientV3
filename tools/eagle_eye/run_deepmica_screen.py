"""Label-blind DeepMiCa checkpoint screen; region metrics are not punctum truth."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import time

import cv2
import numpy as np
from PIL import Image
import torch

from run_calcification_pilot import iou


def preprocess(pixels):
    if pixels.ndim != 2 or pixels.dtype != np.uint8:
        raise ValueError('Expected native grayscale uint8 research input.')
    flipped = int(pixels[:, pixels.shape[1]//2:].sum()) > int(pixels[:, :pixels.shape[1]//2].sum())
    working = np.fliplr(pixels).copy() if flipped else pixels.copy()
    binary = (working > 2).astype(np.uint8)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (23,23))
    binary = cv2.dilate(cv2.morphologyEx(binary, cv2.MORPH_OPEN, kernel), kernel)
    count, labels, stats, _ = cv2.connectedComponentsWithStats(binary)
    if count <= 1:
        raise ValueError('No image-derived breast foreground; prediction unavailable.')
    largest = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    working[labels != largest] = 0
    ys, xs = np.where(working > 0)
    x, y, right, bottom = int(xs.min()), int(ys.min()), int(xs.max()+1), int(ys.max()+1)
    crop = working[y:bottom, x:right]
    crop = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8,8)).apply(crop)
    return crop, (x,y,right,bottom), flipped


def restore_map(cropped, bounds, flipped, shape):
    x,y,right,bottom = bounds
    if cropped.shape != (bottom-y, right-x):
        raise ValueError('Prediction geometry mismatch.')
    result = np.zeros(shape, dtype=np.float32)
    result[y:bottom,x:right] = cropped
    return np.fliplr(result).copy() if flipped else result


def load_checkpoint(source, weights):
    spec = importlib.util.spec_from_file_location('UNet', source)
    module = importlib.util.module_from_spec(spec)
    sys.modules['UNet'] = module
    spec.loader.exec_module(module)
    # Inspected upstream globals only. Never fall back to unrestricted pickle.
    allowed = [module.build_unet, module.conv_block, module.encoder_block, module.decoder_block,
               set, torch.nn.Conv2d, torch.nn.ConvTranspose2d, torch.nn.BatchNorm2d,
               torch.nn.ReLU, torch.nn.MaxPool2d]
    with torch.serialization.safe_globals(allowed):
        checkpoint = torch.load(weights, map_location='cpu', weights_only=True)
    model = module.build_unet()
    model.load_state_dict(checkpoint['model_state_dict'], strict=True)
    return model, int(checkpoint['epoch'])


def infer(model, pixels, batch_size):
    crop, bounds, flipped = preprocess(pixels)
    h,w = crop.shape
    padded = np.pad(crop, ((0,(-h)%256),(0,(-w)%256)))
    probabilities = np.zeros(padded.shape, dtype=np.float32)
    coordinates = [(x,y) for y in range(0,padded.shape[0],256)
                         for x in range(0,padded.shape[1],256)]
    with torch.inference_mode():
        for start in range(0,len(coordinates),batch_size):
            current = coordinates[start:start+batch_size]
            batch = np.stack([padded[y:y+256,x:x+256] for x,y in current])
            tensor = torch.from_numpy(batch[:,None].astype(np.float32)/255).cuda()
            logits = model(tensor)
            if not torch.isfinite(logits).all():
                raise RuntimeError('Nonfinite segmentation output.')
            outputs = logits.sigmoid()[:,0].cpu().numpy()
            for (x,y),output in zip(current,outputs):
                probabilities[y:y+256,x:x+256] = output
    return restore_map(probabilities[:h,:w],bounds,flipped,pixels.shape), len(coordinates)


def proposals(probabilities, threshold):
    # Exploratory cluster grouping in native pixels; no physical-size assertion.
    binary = (probabilities >= threshold).astype(np.uint8)
    count, labels, stats, _ = cv2.connectedComponentsWithStats(binary)
    accepted = np.zeros(count, dtype=np.uint8)
    accepted[1:] = stats[1:,cv2.CC_STAT_AREA] >= 2
    binary = accepted[labels]
    grouped = cv2.dilate(binary, cv2.getStructuringElement(cv2.MORPH_ELLIPSE,(65,65)))
    groups, group_labels, _, _ = cv2.connectedComponentsWithStats(grouped)
    ys,xs = np.where(binary)
    memberships = group_labels[ys,xs]
    boxes = []
    # Bounds use original predicted pixels, not the dilated support.
    for label in np.unique(memberships):
        if label == 0:
            continue
        select = memberships == label
        boxes.append([int(xs[select].min()),int(ys[select].min()),
                      int(xs[select].max()+1),int(ys[select].max()+1)])
    return binary, boxes, count-1, groups-1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--source',type=Path,required=True)
    parser.add_argument('--weights',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--batch-size',type=int,default=16)
    args = parser.parse_args()
    if args.output.exists() or not 1 <= args.batch_size <= 64:
        raise ValueError('Existing output or invalid batch budget.')
    torch.set_num_threads(4)
    free,total = torch.cuda.mem_get_info()
    if free < 9*2**30:
        raise RuntimeError('Insufficient free memory for initial checkpoint screen.')
    torch.cuda.set_per_process_memory_fraction(8*2**30/total)
    model,epoch = load_checkpoint(args.source,args.weights)
    model.cuda().eval()
    with torch.inference_mode():
        synthetic = model(torch.zeros(1,1,256,256,device='cuda'))
        if synthetic.shape != (1,1,256,256) or not torch.isfinite(synthetic).all():
            raise RuntimeError('Checkpoint synthetic inference failed.')
    rows = json.loads((args.root/'manifest.json').read_text())
    rows = [r for r in rows if r['partition']=='validation']
    thresholds = [.1,.3,.5,.7,.9]
    report = {'status':'completed_pretrained_segmentation_development_screen',
              'epoch':epoch, 'images':len(rows), 'patch_size':256, 'batch_size':args.batch_size,
              'results':{group:{str(t):{'regions':0,'iou_matched':0,'regions_with_at_least_3_predicted_pixels':0,
                                      'proposals':0,'predicted_pixels':0,'images':0}
                               for t in thresholds} for group in ('CBIS','VinDr_positive','VinDr_control')},
              'checkpoint_sha256':hashlib.sha256(args.weights.read_bytes()).hexdigest(),
              'source_sha256':hashlib.sha256(args.source.read_bytes()).hexdigest(),
              'manifest_sha256':hashlib.sha256((args.root/'manifest.json').read_bytes()).hexdigest(),
              'parameters':sum(p.numel() for p in model.parameters()),
              'limitations':['adapted image-only preprocessing; not exact upstream preprocessing reproduction',
                             'upstream ROI-center artifact cleanup and CBIS truth-mask AND deliberately omitted',
                             'region boxes cannot measure individual-punctum segmentation accuracy',
                             'pixel occupancy is a lenient descriptive proxy, not detection sensitivity',
                             '65-pixel grouping is exploratory; not physical-size validated',
                             'unreviewed controls and unmatched proposals are not confirmed false positives',
                             'checkpoint training membership and product weight rights unverified']}
    started = time.monotonic()
    patches = 0
    for number,row in enumerate(rows,1):
        pixels = np.asarray(Image.open(args.root/row['image']).convert('L'))
        probabilities,n = infer(model,pixels,args.batch_size)
        patches += n
        group = 'CBIS' if row['source']=='CBIS' else ('VinDr_positive' if row['boxes'] else 'VinDr_control')
        for threshold in thresholds:
            binary,boxes,_,_ = proposals(probabilities,threshold)
            remaining = list(range(len(boxes)))
            matched,occupied = 0,0
            for region in row['boxes']:
                candidate = [(iou(np.asarray(region),np.asarray(boxes[j])),j) for j in remaining]
                if candidate and max(candidate)[0] >= .5:
                    matched += 1
                    remaining.remove(max(candidate)[1])
                x,y,right,bottom = [int(v) for v in region]
                occupied += int(binary[max(0,y):min(pixels.shape[0],bottom),max(0,x):min(pixels.shape[1],right)].sum() >= 3)
            r = report['results'][group][str(threshold)]
            r['regions'] += len(row['boxes'])
            r['iou_matched'] += matched
            r['regions_with_at_least_3_predicted_pixels'] += occupied
            r['proposals'] += len(boxes)
            r['predicted_pixels'] += int(binary.sum())
            r['images'] += 1
        print(json.dumps({'images_completed':number,'patches':patches}),flush=True)
    report.update(seconds=time.monotonic()-started,patches=patches,
                  peak_vram_gib=torch.cuda.max_memory_allocated()/2**30,
                  precision='FP32',torch_version=torch.__version__)
    args.output.write_text(json.dumps(report,indent=2))
    print(json.dumps({'status':report['status']}),flush=True)


if __name__=='__main__':
    main()
