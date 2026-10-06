"""Private native-resolution DeepMiCa proposals; never automatic negative truth."""
import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw
import torch

from run_deepmica_screen import load_checkpoint, infer, proposals


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--source',type=Path,required=True)
    parser.add_argument('--weights',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError('Existing protected review packet.')
    free,total = torch.cuda.mem_get_info()
    if free < 9*2**30:
        raise RuntimeError('Insufficient free memory.')
    torch.cuda.set_per_process_memory_fraction(8*2**30/total)
    torch.set_num_threads(4)
    model,_ = load_checkpoint(args.source,args.weights)
    model.cuda().eval()
    rows = json.loads((args.root/'manifest.json').read_text())
    rows = [r for r in rows if r['partition']=='validation' and r['source']=='VinDr']
    args.output.mkdir()
    items,cards = [],[]
    for row in rows:
        path = args.root/row['image']
        if hashlib.sha256(path.read_bytes()).hexdigest()!=row['source_sha256']:
            raise ValueError('Review source changed.')
        image = Image.open(path).convert('RGB')
        if min(image.size)<1024:
            raise ValueError('Native unpadded crop unavailable.')
        probabilities,_ = infer(model,np.asarray(image.convert('L')),16)
        binary,boxes,_,_ = proposals(probabilities,.5)
        ranked=[]
        for box in boxes:
            x,y,right,bottom=box
            if right-x>1024 or bottom-y>1024:
                continue
            score=float(probabilities[y:bottom,x:right].max())
            ranked.append((score,box))
        for score,box in sorted(ranked,reverse=True)[:2]:
            x=int(max(0,min(image.width-1024,(box[0]+box[2])/2-512)))
            y=int(max(0,min(image.height-1024,(box[1]+box[3])/2-512)))
            uid=f'deepmica-{len(items):03d}'
            crop=image.crop((x,y,x+1024,y+1024))
            crop.save(args.output/f'{uid}.png')
            overlay=crop.copy()
            # Rectangle identifies the region; no heatmap hides native morphology.
            ImageDraw.Draw(overlay).rectangle((box[0]-x,box[1]-y,box[2]-x,box[3]-y),outline='red',width=2)
            overlay.save(args.output/f'{uid}-marked.png')
            item=dict(id=uid,source_image=row['image'],source_sha256=row['source_sha256'],
                      person_key=row['person_key'],proposal_box=box,crop_window=[x,y,1024],score=score,
                      crop_sha256=hashlib.sha256((args.output/f'{uid}.png').read_bytes()).hexdigest(),
                      proposal_label='unreviewed',whole_crop='unreviewed',reviewer='',
                      cohort='development_review_only')
            items.append(item)
            cards.append(f'''<article><h2>{uid}</h2><a href="{uid}.png" target="_blank">Open original native crop</a>
<img src="{uid}-marked.png"><p>Red rectangle: model proposal. Review the original for morphology.</p>
<label>Proposal <select data-id="{uid}" data-key="proposal_label"><option value="unreviewed">Unreviewed</option>
<option value="calcification">Calcification</option><option value="not_calcification">Not calcification</option>
<option value="uncertain">Uncertain</option></select></label>
<label>Entire crop <select data-id="{uid}" data-key="whole_crop"><option value="unreviewed">Unreviewed</option>
<option value="reviewed_no_calcification">Fully reviewed: no calcification</option>
<option value="contains_calcification">Contains calcification</option><option value="uncertain">Uncertain / incomplete</option>
</select></label></article>''')
    payload=dict(schema='calcification-review-v1',branch='DeepMiCa segmentation',
                 checkpoint_sha256=hashlib.sha256(args.weights.read_bytes()).hexdigest(),
                 status='unreviewed_not_training_labels',items=items)
    (args.output/'private-queue.json').write_text(json.dumps(payload,indent=2))
    document='''<!doctype html><html lang="en"><meta charset="utf-8"><title>Private DeepMiCa review</title>
<style>body{background:#171717;color:white;font:16px system-ui;margin:24px}article{border:1px solid #777;padding:16px;margin:20px 0}img{display:block;width:512px;max-width:100%}label{display:block;margin:12px}a{color:lightblue}</style>
<h1>Private DeepMiCa development review</h1><p>These are predictions, not verified calcifications.
Assess benign calcifications too. Rejecting a marked proposal does not establish an empty crop.
Reviewing these samples excludes them from independent qualification testing.</p>
<label>Reviewer <input id="reviewer"></label><button id="save">Export reviewed JSON</button>'''
    document+='\n'.join(cards)+'<script>const queue='+json.dumps(payload).replace('<','\\u003c')+''';
document.querySelectorAll('select').forEach(s=>s.onchange=()=>{queue.items.find(i=>i.id===s.dataset.id)[s.dataset.key]=s.value});
document.getElementById('save').onclick=()=>{const reviewer=document.getElementById('reviewer').value.trim();
if(!reviewer){alert('Enter a reviewer identifier.');return;}
queue.items.forEach(i=>i.reviewer=reviewer);queue.status='human_review_export_requires_validation';
const a=document.createElement('a');a.href=URL.createObjectURL(new Blob([JSON.stringify(queue,null,2)],{type:'application/json'}));
a.download='reviewed-deepmica-proposals.json';a.click();URL.revokeObjectURL(a.href);};</script></html>'''
    (args.output/'review.html').write_text(document)
    report=dict(status='unreviewed_queue_prepared',images=len(rows),proposals=len(items),
                automatic_negative_labels=0,checkpoint_sha256=payload['checkpoint_sha256'])
    (args.output/'aggregate.json').write_text(json.dumps(report,indent=2))
    print(json.dumps(report),flush=True)


if __name__=='__main__':
    main()
