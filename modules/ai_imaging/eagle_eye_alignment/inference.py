"""Isolated SGR inference entry point. Only pixel arrays cross this boundary."""
from pathlib import Path
import json
import sys


WEIGHTS = {
    'Femur': 'Weights/Femur/Best_Run_ep100_bs8_lr1e-05_a0.2.pth',
    'Knee': 'Weights/Knee/Best_Run_ep100_bs8_lr1e-05_a0.2.pth',
    'Ankle': 'Weights/Ankle/Best_Run_ep100_bs8_lr1e-05_a0.2.pth',
    'ROI': 'Weights/ROI_Detection/fll_detection_joints_cv_5_31.pth',
}


def tensor_image(pixels, size):
    import SimpleITK as sitk
    import numpy as np
    import torch
    original = sitk.GetImageFromArray(pixels.astype('float32'))
    result = sitk.Resample(original, list(size), sitk.Transform(), sitk.sitkBSpline,
                           original.GetOrigin(), [pixels.shape[1]/size[0], pixels.shape[0]/size[1]],
                           original.GetDirection(), 0., sitk.sitkFloat32)
    array = sitk.GetArrayFromImage(result) / 255.
    return torch.from_numpy(np.stack([array]*3)).float()


def joint_model(kind, root):
    import torch
    from vendor.BaseModels import UNet16
    from vendor.SGRModel import SGRNetwork16
    count = {'Femur': 1, 'Knee': 5, 'Ankle': 2}[kind]
    unet = UNet16()
    if count != 1:
        unet.final = torch.nn.Conv2d(32, count, kernel_size=1)
    model = SGRNetwork16(unet, count*2)
    model.load_state_dict(torch.load(root/WEIGHTS[kind], map_location='cpu', weights_only=True))
    return model.eval()


def detector_model(root):
    import torch
    import torchvision
    from torchvision.models.detection.faster_rcnn import FastRCNNPredictor
    model = torchvision.models.detection.fasterrcnn_resnet50_fpn(weights=None, weights_backbone=None)
    model.roi_heads.box_predictor = FastRCNNPredictor(model.roi_heads.box_predictor.cls_score.in_features, 5)
    model.load_state_dict(torch.load(root/WEIGHTS['ROI'], map_location='cpu', weights_only=True))
    return model.eval()


def run(pixels, root):
    import numpy as np
    import torch
    torch.set_num_threads(4)
    torch.set_num_interop_threads(1)
    h, w = pixels.shape
    detector = detector_model(root)
    with torch.inference_mode():
        detections = detector([tensor_image(pixels, (1400,4200))])[0]
    boxes = {}
    scores = {}
    for label, kind in ((1,'Femur'),(3,'Knee'),(4,'Ankle')):
        for side, half in (('R',0),('L',1)):
            candidates = []
            for box, score, cls in zip(detections['boxes'], detections['scores'], detections['labels']):
                if int(cls) == label and float(score) >= .7 and int(float(box[0]+box[2])/2 >= 700) == half:
                    candidates.append((float(score),box.numpy()))
            if not candidates:
                raise ValueError('A complete bilateral hip, knee and ankle could not be localized. Place points manually.')
            score, box = max(candidates,key=lambda item:item[0])
            x0,y0,x1,y1 = (box*np.array([w/1400,h/4200,w/1400,h/4200])).astype(int)
            x0,y0,x1,y1 = max(0,x0),max(0,y0),min(w,x1),min(h,y1)
            if x1-x0 < 10 or y1-y0 < 10:
                raise ValueError('An anatomical region is incomplete. Place points manually.')
            boxes[side,kind] = (x0,y0,x1,y1)
            scores[f'{side}_{kind}'] = score
    del detector
    result = {'R':{},'L':{}}
    for kind in ('Femur','Knee','Ankle'):
        model = joint_model(kind,root)
        for side in ('R','L'):
            x0,y0,x1,y1 = boxes[side,kind]
            with torch.inference_mode():
                _, coords = model(tensor_image(pixels[y0:y1,x0:x1], (512,512)).unsqueeze(0))
            coords = coords.numpy().reshape(-1,2)
            if not np.isfinite(coords).all() or (coords < 0).any() or (coords > 512).any():
                raise ValueError('Landmark prediction is outside its anatomical region. Place points manually.')
            # Preserve subpixel predictions; never round landmark positions for measurement.
            coords = coords*np.array([(x1-x0)/512,(y1-y0)/512])+np.array([x0,y0])
            if kind == 'Femur':
                result[side]['hip'] = coords[0].tolist()
            else:
                groups = [('femur',coords[:2]),('tibia',coords[2:4])] if kind == 'Knee' else [('ankle',coords)]
                for prefix, pair in groups:
                    pair=sorted(pair,key=lambda p:p[0],reverse=side=='L')
                    result[side][prefix+'_lateral']=pair[0].tolist()
                    result[side][prefix+'_medial']=pair[1].tolist()
                if kind=='Knee':result[side]['knee']=coords[4].tolist()
        del model
    return {'landmarks':result,'roi_scores':scores,'model':'SGR-2024','format_version':1}


if __name__ == '__main__':
    import numpy as np
    try:
        root, source, output = map(Path,sys.argv[1:4])
        pixels=np.load(source,allow_pickle=False)
        result=run(pixels,root)
        output.write_text(json.dumps(result,allow_nan=False),encoding='utf-8')
    except Exception:
        # Patient-independent error; local caller offers manual correction.
        sys.stderr.write('Alignment inference failed. Check complete image coverage and model compatibility.\n')
        sys.exit(2)
