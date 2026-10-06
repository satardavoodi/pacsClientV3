"""Create a private, unlabelled proposal-review queue from development images only.

An unmatched proposal is NOT a negative training label. The reviewer assesses
the marked proposal and separately the complete native-resolution crop.
"""
import argparse
import base64
import hashlib
import io
import json
from pathlib import Path

import torch
from PIL import Image, ImageDraw
from torchvision.models.detection import fcos_resnet50_fpn
from torchvision.ops import nms
from torchvision.transforms import functional as TF

from run_calcification_pilot import starts, iou
import numpy as np


def verified_negative(review):
    """Only an explicit complete-crop assessment supports an empty target."""
    reviewer = review.get('reviewer')
    return (review.get('proposal_label') == 'not_calcification'
            and review.get('whole_crop') == 'reviewed_no_calcification'
            and review.get('image_quality') == 'adequate'
            and not review.get('point_annotations')
            and not review.get('box_annotations')
            and isinstance(reviewer, str) and reviewer.strip() != '')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--weights', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--per-image', type=int, default=2)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError('Review queue already exists.')
    if not 1 <= args.per_image <= 4:
        raise ValueError('Review budget must be between one and four proposals per image.')
    records = json.loads((args.root / 'manifest.json').read_text())
    if any(r['partition'] != 'validation' for r in records):
        raise ValueError('This review queue accepts development validation records only.')
    free, total = torch.cuda.mem_get_info()
    if free < 9 * 2**30:
        raise RuntimeError('Insufficient free VRAM.')
    torch.cuda.set_per_process_memory_fraction(8 * 2**30 / total)
    torch.set_num_threads(4)
    model = fcos_resnet50_fpn(weights=None, weights_backbone=None, num_classes=1,
                            min_size=1024, max_size=1024, score_thresh=.3, detections_per_img=100).cuda().eval()
    model.load_state_dict(torch.load(args.weights, map_location='cuda', weights_only=True), strict=True)
    args.output.mkdir()
    items, cards = [], []
    with torch.inference_mode():
        for record in records:
            if hashlib.sha256((args.root / record['image']).read_bytes()).hexdigest() != record['source_sha256']:
                raise ValueError('Review source changed.')
            image = Image.open(args.root / record['image']).convert('RGB')
            if min(image.size) < 1024:
                raise ValueError('Review requires an unpadded native crop.')
            boxes, scores = [], []
            for y in starts(image.height, 1024):
                for x in starts(image.width, 1024):
                    tile = TF.to_tensor(image.crop((x, y, x + 1024, y + 1024))).cuda()
                    with torch.autocast('cuda', dtype=torch.bfloat16 if torch.cuda.is_bf16_supported() else torch.float16):
                        prediction = model([tile])[0]
                    boxes.append(prediction['boxes'].float().cpu() + torch.tensor([x, y] * 2))
                    scores.append(prediction['scores'].float().cpu())
            boxes, scores = torch.cat(boxes), torch.cat(scores)
            keep = nms(boxes, scores, .5)
            taken = 0
            for index in keep:
                box = boxes[index].numpy()
                if any(iou(box, np.asarray(reference)) >= .5 for reference in record['boxes']):
                    continue
                if box[0] < 0 or box[1] < 0 or box[2] > image.width or box[3] > image.height:
                    continue
                cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
                x = int(max(0, min(image.width - 1024, cx - 512)))
                y = int(max(0, min(image.height - 1024, cy - 512)))
                if box[0] < x or box[1] < y or box[2] > x + 1024 or box[3] > y + 1024:
                    continue  # Do not ask for an assessment of a truncated proposal.
                crop = image.crop((x, y, x + 1024, y + 1024))
                uid = f'proposal-{len(items):03d}'
                crop.save(args.output / f'{uid}.png')
                draw = ImageDraw.Draw(crop)
                draw.rectangle(tuple(box - [x, y, x, y]), outline='red', width=3)
                buffer = io.BytesIO(); crop.save(buffer, format='PNG')
                encoded = base64.b64encode(buffer.getvalue()).decode()
                item = dict(id=uid, source_image=record['image'], source_sha256=record['source_sha256'],
                            person_key=record['person_key'], proposal_box=box.tolist(), crop_window=[x, y, 1024],
                            score=float(scores[index]), proposal_label='unreviewed', whole_crop='unreviewed',
                            reviewer='', cohort='development_review_only',
                            crop_sha256=hashlib.sha256((args.output / f'{uid}.png').read_bytes()).hexdigest())
                items.append(item)
                cards.append(f'''<article><h3>{uid}</h3><img src="data:image/png;base64,{encoded}">
<p>Red rectangle: proposed region. Open image in a new tab for native resolution.</p>
<label>Marked proposal <select data-id="{uid}" data-key="proposal_label">
<option value="unreviewed">Unreviewed</option><option value="calcification">Calcification</option>
<option value="not_calcification">Not calcification</option><option value="uncertain">Uncertain</option></select></label>
<label>Entire crop <select data-id="{uid}" data-key="whole_crop"><option value="unreviewed">Unreviewed</option>
<option value="reviewed_no_calcification">Fully reviewed: no calcification anywhere</option>
<option value="contains_calcification">Contains calcification</option><option value="uncertain">Uncertain / incomplete</option></select></label></article>''')
                taken += 1
                if taken == args.per_image:
                    break
    payload = dict(schema='calcification-review-v1', checkpoint_sha256=hashlib.sha256(args.weights.read_bytes()).hexdigest(),
                   status='unreviewed_not_training_labels', items=items)
    (args.output / 'private-queue.json').write_text(json.dumps(payload, indent=2))
    document = '''<!doctype html><html lang="en"><meta charset="utf-8"><title>Calcification proposal review</title>
<style>body{font-family:system-ui;background:#181818;color:#eee;margin:24px}article{margin:24px 0;border:1px solid #777;padding:16px}img{width:512px;max-width:100%}label{display:block;margin:12px 0}select{padding:8px}button{padding:12px}</style>
<h1>Private development proposal review</h1><p>Unmatched does not mean false positive. Assess any calcification, including benign calcification.
This queue is for development only. Reviewing it disqualifies these crops from independent qualification testing.
An empty training target requires explicit whole-crop review, not just rejection of the red rectangle.</p>
<label>Reviewer identifier <input id="reviewer"></label><button id="save">Export reviewed JSON</button>
''' + '\n'.join(cards) + '<script>const queue=' + json.dumps(payload).replace('<', '\\u003c') + ''';
document.querySelectorAll('select').forEach(s=>s.onchange=()=>{queue.items.find(i=>i.id===s.dataset.id)[s.dataset.key]=s.value});
document.getElementById('save').onclick=()=>{const reviewer=document.getElementById('reviewer').value.trim();
if(!reviewer){alert('Enter a reviewer identifier.');return;}
queue.items.forEach(i=>{i.reviewer=reviewer});queue.status='human_review_export_requires_validation';
const link=document.createElement('a');link.href=URL.createObjectURL(new Blob([JSON.stringify(queue,null,2)],{type:'application/json'}));
link.download='reviewed-calcification-proposals.json';link.click();URL.revokeObjectURL(link.href);};</script></html>'''
    (args.output / 'review.html').write_text(document)
    report = dict(status='unreviewed_queue_prepared', images=len(records), proposals=len(items),
                  automatic_negative_labels=0, checkpoint_sha256=payload['checkpoint_sha256'])
    (args.output / 'aggregate.json').write_text(json.dumps(report, indent=2))
    print(json.dumps(report))


if __name__ == '__main__':
    main()
