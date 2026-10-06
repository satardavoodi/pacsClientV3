"""Exploratory selected-crop audit; region occupancy is not punctum sensitivity."""
import argparse
import hashlib
import json
from pathlib import Path

import cv2
import numpy as np
from PIL import Image


def overlap(a, b):
    area = max(0, min(a[2], b[2])-max(a[0], b[0])) * max(0, min(a[3], b[3])-max(a[1], b[1]))
    union = (a[2]-a[0])*(a[3]-a[1])+(b[2]-b[0])*(b[3]-b[1])-area
    return area / union if union else 0.0


def contains_center(region, proposal):
    x, y = (proposal[0]+proposal[2])/2, (proposal[1]+proposal[3])/2
    return region[0] <= x < region[2] and region[1] <= y < region[3]


def counts(predictions, references):
    return {
        'reference_regions': len(references), 'proposals': len(predictions),
        'regions_with_proposal_center': sum(any(contains_center(r,p) for p in predictions) for r in references),
        'regions_with_iou_025': sum(any(overlap(r,p)>=.25 for p in predictions) for r in references),
        'proposal_centers_outside_all_regions': sum(not any(contains_center(r,p) for r in references) for p in predictions),
    }


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--feedback',type=Path,required=True)
    parser.add_argument('--crops',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    payload=json.loads(args.feedback.read_text(encoding='utf-8'))
    totals={}; included=[]; excluded=0
    for item in payload['items']:
        if item.get('dataset_disposition')=='excluded_non_mammographic':
            excluded+=1; continue
        path=args.crops/(item['id']+'.png')
        if hashlib.sha256(path.read_bytes()).hexdigest()!=item['crop_sha256']:
            raise ValueError('Crop hash mismatch')
        image=np.asarray(Image.open(path).convert('L'))
        refs=[b['crop_box'] for b in item.get('box_annotations',[])]
        if any(not (0<=r[0]<r[2]<=1024 and 0<=r[1]<r[3]<=1024) for r in refs):
            raise ValueError('Invalid reference region')
        w=item['crop_window']; b=item['proposal_box']
        branches={'selected_model_red_box':[[b[0]-w[0],b[1]-w[1],b[2]-w[0],b[3]-w[1]]]}
        # Fixed exploratory grids, native source pixels, no reviewer window preprocessing.
        enhanced=np.maximum.reduce([cv2.morphologyEx(image,cv2.MORPH_TOPHAT,
                    cv2.getStructuringElement(cv2.MORPH_ELLIPSE,(k,k))) for k in (5,9,15)])
        for threshold in (8,16,24,32):
            binary=((enhanced>=threshold)&(image>2)).astype(np.uint8)
            n,_,stats,_=cv2.connectedComponentsWithStats(binary)
            boxes=[]
            for x,y,width,height,area in stats[1:]:
                if 2<=area<=100 and max(width,height)<=20:
                    boxes.append([int(x),int(y),int(x+width),int(y+height)])
            branches[f'tophat_threshold_{threshold}']=boxes
            if threshold==24:
                ranked=sorted(boxes,key=lambda b:float(enhanced[b[1]:b[3],b[0]:b[2]].max()),reverse=True)
                for budget in (1,3,10):
                    branches[f'tophat_24_top_{budget}']=ranked[:budget]
                model_box=branches['selected_model_red_box'][0]
                branches['selected_model_with_tophat_support']=[model_box] if any(contains_center(model_box,p) for p in boxes) else []
        for name,preds in branches.items():
            result=counts(preds,refs)
            if name not in totals: totals[name]={key:0 for key in result}
            for key,value in result.items(): totals[name][key]+=value
        included.append(item)
    report={'status':'exploratory_region_audit_not_independent_test',
            'feedback_sha256':hashlib.sha256(args.feedback.read_bytes()).hexdigest(),
            'crops':len(included),'excluded_non_mammographic':excluded,
            'unique_source_images':len({i['source_sha256'] for i in included}),
            'crops_without_marked_regions':sum(not i.get('box_annotations') for i in included),
            'branches':totals,
            'limitations':['Selected model proposals only; not complete model output.',
                          'Overlapping crops and repeated regions are not deduplicated.',
                          'Region center occupancy does not establish true microcalcification detection.',
                          'Multiple particles within one physician cluster are not false positives.',
                          'Outside-region centers require adjudication; quality ratings remain unknown.',
                          'Native pixel size filters are exploratory, not physical size thresholds.']}
    args.output.write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report))


if __name__=='__main__': main()
