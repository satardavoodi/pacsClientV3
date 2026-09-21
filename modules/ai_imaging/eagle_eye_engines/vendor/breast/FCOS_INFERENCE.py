# Imported inference implementation; provenance in ../provenance.json.
import os
import sys
import json
from collections import defaultdict
from typing import Optional, Dict
import torch
import torch.nn as nn
import torch.nn.functional as F
import pandas as pd
from PIL import Image, ImageDraw, ImageFont, UnidentifiedImageError
from torchvision.transforms import v2 as TV2
from torchvision.tv_tensors import Image as TVImage
from torch.utils.data import Dataset, DataLoader
from torchvision.ops import nms
INPUT_DIR = '.'
RECURSIVE = True
INPUT_CSV = None
try:
    from resource_path import get_model_path
    _WEIGHTS_DIR = get_model_path('weights')
except Exception:
    _WEIGHTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'weights')

def _weight_path(filename):
    if not filename:
        return None
    p = os.path.join(str(_WEIGHTS_DIR), filename)
    return p if os.path.isfile(p) else filename
HYBRID_FULL = _weight_path('best_fcos_csv_full_delivery.pt')
HYBRID_STATE = _weight_path('best_fcos_csv_delivery.pth')
DETECTOR_FULL = None
DETECTOR_STATE = None
AUX_STATE = None
OUT_DIR_ROOT = '.'
OUT_PRED_CSV = os.path.join(OUT_DIR_ROOT, 'predictions_infer.csv')
OUT_PRED_STUDY_CSV = os.path.join(OUT_DIR_ROOT, 'predictions_study_infer.csv')
OUT_SUMMARY_TXT = os.path.join(OUT_DIR_ROOT, 'summary_infer.txt')
OUT_SWEEP_CSV = os.path.join(OUT_DIR_ROOT, 'threshold_sweep_counts.csv')
VIZ_OUT_DIR = os.path.join(OUT_DIR_ROOT, 'ALL_VIZ')
VIZ_NAME_MODE = 'basename'
SAVE_ALL_OVERLAYS = True
SAVE_OVERWRITE_SOURCE = False
SAVE_NAME_SUFFIX = '_pred'
IMG_SIZE = (512, 512)
MODEL_SCORE_THR = 0.2
MODEL_NMS_THR = 0.5
DET_EVAL_SCORE_THR = 0.45
AUX_EVAL_THR = 0.75
TTA_HFLIP = True
SWEEP_THRESHOLDS = [x / 100 for x in range(5, 51, 2)]
MIN_BOX_AREA_FRAC = 0.002
AGGREGATE_BY_STUDY = True
STUDY_KEY_MODE = 'parent_dir'
STUDY_VOTE_K = 2
NUM_WORKERS = 0
BATCH_SIZE = 4
DECISION_MODE = 'detector'
torch.backends.cudnn.benchmark = True
_GLOBAL_MODEL_CACHE = None
_GLOBAL_DEVICE_CACHE = None
_GLOBAL_REPORT_CACHE = None

class _Tee:

    def __init__(self, log_fp, *streams):
        self.log_fp = log_fp
        self.streams = streams

    def write(self, data):
        for s in self.streams:
            try:
                s.write(data)
                s.flush()
            except Exception:
                pass
        try:
            self.log_fp.write(data)
            self.log_fp.flush()
        except Exception:
            pass

    def flush(self):
        for s in self.streams:
            try:
                s.flush()
            except Exception:
                pass
        try:
            self.log_fp.flush()
        except Exception:
            pass

def set_input_csv(path: Optional[str]):
    global INPUT_CSV
    INPUT_CSV = str(path) if path else None

def set_input_dir(path: str, recursive: Optional[bool]=None):
    global INPUT_DIR, RECURSIVE
    INPUT_DIR = str(path)
    if recursive is not None:
        RECURSIVE = bool(recursive)

def set_output_dir(path: str):
    global OUT_DIR_ROOT, OUT_PRED_CSV, OUT_PRED_STUDY_CSV, OUT_SUMMARY_TXT, OUT_SWEEP_CSV, VIZ_OUT_DIR
    OUT_DIR_ROOT = str(path)
    os.makedirs(OUT_DIR_ROOT, exist_ok=True)
    OUT_PRED_CSV = os.path.join(OUT_DIR_ROOT, 'predictions_infer.csv')
    OUT_PRED_STUDY_CSV = os.path.join(OUT_DIR_ROOT, 'predictions_study_infer.csv')
    OUT_SUMMARY_TXT = os.path.join(OUT_DIR_ROOT, 'summary_infer.txt')
    OUT_SWEEP_CSV = os.path.join(OUT_DIR_ROOT, 'threshold_sweep_counts.csv')
    VIZ_OUT_DIR = os.path.join(OUT_DIR_ROOT, 'ALL_VIZ')
    os.makedirs(VIZ_OUT_DIR, exist_ok=True)

def set_thresholds(det_eval: Optional[float]=None, aux_eval: Optional[float]=None):
    global DET_EVAL_SCORE_THR, AUX_EVAL_THR
    if det_eval is not None:
        DET_EVAL_SCORE_THR = float(det_eval)
    if aux_eval is not None:
        AUX_EVAL_THR = float(aux_eval)

def get_output_paths() -> Dict[str, str]:
    return {'predictions_csv': OUT_PRED_CSV, 'study_csv': OUT_PRED_STUDY_CSV, 'summary_txt': OUT_SUMMARY_TXT, 'sweep_csv': OUT_SWEEP_CSV, 'viz_dir': VIZ_OUT_DIR}

def list_pngs(root, recursive=True):
    exts = {'.png'}
    files = []
    if recursive:
        for d, _, fnames in os.walk(root):
            for f in fnames:
                if os.path.splitext(f)[1].lower() in exts:
                    files.append(os.path.join(d, f))
    else:
        for f in os.listdir(root):
            p = os.path.join(root, f)
            if os.path.isfile(p) and os.path.splitext(f)[1].lower() in exts:
                files.append(p)
    files.sort()
    return files

class InferenceDataset(Dataset):

    def __init__(self, img_paths):
        self.items = [{'frame': p} for p in img_paths]
        self.tf = TV2.Compose([TV2.ToImage(), TV2.Resize(IMG_SIZE, antialias=True), TV2.ToDtype(torch.float32, scale=True)])

    def __len__(self):
        return len(self.items)

    def __getitem__(self, idx):
        path = self.items[idx]['frame']
        try:
            img = Image.open(path).convert('RGB')
        except (UnidentifiedImageError, FileNotFoundError) as e:
            print(f'[warn] Failed to open {path}: {e} — using blank image.')
            img = Image.new('RGB', (IMG_SIZE[1], IMG_SIZE[0]), color=(0, 0, 0))
        W0, H0 = img.size
        img_tv = TVImage(img)
        img_tv = self.tf(img_tv)
        return (img_tv, {'path': path, 'orig_size': (W0, H0)})

def collate_fn(batch):
    imgs, metas = list(zip(*batch))
    return (list(imgs), list(metas))
from torchvision.models.detection import fcos_resnet50_fpn
from torchvision.models import ResNet50_Weights

class HybridFCOS(nn.Module):

    def __init__(self, detector: nn.Module, drop=0.2):
        super().__init__()
        self.detector = detector
        self.cls_head = None
        self.drop = drop
        self.transform = self.detector.transform

    def _build_head_if_needed(self, feats):
        if self.cls_head is not None:
            return
        with torch.no_grad():
            in_dim = sum((f.shape[1] for f in feats.values()))
        self.cls_head = nn.Sequential(nn.Linear(in_dim, 512, bias=True), nn.ReLU(inplace=True), nn.Dropout(self.drop), nn.Linear(512, 1, bias=True)).to(next(iter(feats.values())).device)

    def _compute_cls_logits(self, images_list):
        feats = self.detector.backbone(images_list.tensors)
        feats = {k: v.detach() for k, v in feats.items()}
        self._build_head_if_needed(feats)
        pooled = [F.adaptive_avg_pool2d(f, 1).flatten(1) for f in feats.values()]
        z = torch.cat(pooled, dim=1) if len(pooled) > 1 else pooled[0]
        logits = self.cls_head(z).squeeze(1)
        return logits

    def forward(self, images):
        outputs = self.detector(images)
        with torch.no_grad():
            images_list, _ = self.detector.transform(images)
            logits = self._compute_cls_logits(images_list)
            probs = torch.sigmoid(logits).detach().cpu().tolist()
        for out, p in zip(outputs, probs):
            out['image_score'] = float(p)
        return outputs

def make_detector(num_classes=1):
    kwargs = dict(weights=None, weights_backbone=None, num_classes=num_classes, score_thresh=MODEL_SCORE_THR, nms_thresh=MODEL_NMS_THR, detections_per_img=100, topk_candidates=1000)
    try:
        model = fcos_resnet50_fpn(**kwargs)
    except TypeError:
        for k in ['score_thresh', 'nms_thresh', 'detections_per_img', 'topk_candidates']:
            kwargs.pop(k, None)
        model = fcos_resnet50_fpn(**kwargs)
    if hasattr(model, 'score_thresh'):
        model.score_thresh = MODEL_SCORE_THR
    if hasattr(model, 'nms_thresh'):
        model.nms_thresh = MODEL_NMS_THR
    if hasattr(model, 'detections_per_img'):
        model.detections_per_img = 100
    if hasattr(model, 'topk_candidates'):
        model.topk_candidates = 1000
    return model

def make_model(num_classes=1):
    base = make_detector(num_classes=num_classes)
    if hasattr(base, 'transform'):
        base.transform.min_size = [IMG_SIZE[0]]
        base.transform.max_size = IMG_SIZE[0]
    return HybridFCOS(base, drop=0.2)

def _force_build_aux_head(model: HybridFCOS, device):
    model.eval()
    with torch.no_grad():
        dummy = [torch.zeros(3, IMG_SIZE[0], IMG_SIZE[1], device=device)]
        images_list, _ = model.detector.transform(dummy)
        _ = model._compute_cls_logits(images_list)
    model.train()

def _filter_sd(sd, prefix):
    out = {}
    plen = len(prefix)
    for k, v in sd.items():
        if k.startswith(prefix):
            out[k[plen:]] = v
    return out

def _try_load_file(path):
    if not path or not os.path.isfile(path):
        return None
    try:
        return torch.load(path, map_location='cpu', weights_only=True)
    except TypeError:
        try:
            return torch.load(path, map_location='cpu')
        except Exception:
            return None
    except Exception:
        try:
            return torch.load(path, map_location='cpu')
        except Exception:
            return None

def _finalize_hparams(model):
    if hasattr(model.detector, 'score_thresh'):
        model.detector.score_thresh = MODEL_SCORE_THR
    if hasattr(model.detector, 'nms_thresh'):
        model.detector.nms_thresh = MODEL_NMS_THR
    if hasattr(model.detector, 'detections_per_img'):
        model.detector.detections_per_img = 100
    if hasattr(model.detector, 'topk_candidates'):
        model.detector.topk_candidates = 1000
    if hasattr(model, 'transform'):
        model.transform.min_size = [IMG_SIZE[0]]
        model.transform.max_size = IMG_SIZE[0]

def load_model():
    raise RuntimeError('Configure the verified state-dict loader before inference.')

def preload_model():
    print('[preload_model] Starting model preload...')
    load_model()
    print('[preload_model] Model preload complete')

def abnormal_from_scores(scores_tensor, thr: float) -> bool:
    if scores_tensor.numel() == 0:
        return False
    return bool((scores_tensor >= thr).any().item())

def abnormal_from_auxprob(prob: float, thr: float) -> bool:
    return bool(prob >= thr)

def resize_boxes_to_original(boxes_xyxy, orig_wh, resize_hw):
    if isinstance(boxes_xyxy, torch.Tensor):
        boxes_list = boxes_xyxy.tolist()
    else:
        boxes_list = [[float(x) for x in b] for b in boxes_xyxy]
    H1, W1 = resize_hw
    W0, H0 = orig_wh
    sx = W0 / float(W1)
    sy = H0 / float(H1)
    return [[x1 * sx, y1 * sy, x2 * sx, y2 * sy] for x1, y1, x2, y2 in boxes_list]

def hflip_tv_image(img_tv):
    return torch.flip(img_tv, dims=[2])

def unflip_boxes_xyxy_on_resized(boxes, resized_hw):
    H, W = resized_hw
    b = boxes.clone()
    x1 = b[:, 0].clone()
    x2 = b[:, 2].clone()
    b[:, 0] = W - 1 - x2
    b[:, 2] = W - 1 - x1
    return b

def merge_tta_predictions(orig_boxes, orig_scores, flip_boxes, flip_scores, nms_thr):
    if orig_boxes.numel() == 0 and flip_boxes.numel() == 0:
        return (orig_boxes, orig_scores)
    all_boxes = torch.cat([orig_boxes, flip_boxes], dim=0) if orig_boxes.numel() > 0 else flip_boxes
    all_scores = torch.cat([orig_scores, flip_scores], dim=0) if orig_scores.numel() > 0 else flip_scores
    keep = nms(all_boxes, all_scores, nms_thr)
    return (all_boxes[keep], all_scores[keep])

def filter_tiny_boxes(boxes, scores, min_area_frac, resized_hw):
    if boxes.numel() == 0:
        return (boxes, scores)
    H, W = resized_hw
    area = (boxes[:, 2] - boxes[:, 0]).clamp(min=0) * (boxes[:, 3] - boxes[:, 1]).clamp(min=0)
    min_area = min_area_frac * (H * W)
    keep = area >= min_area
    if keep.numel() == 0:
        return (boxes.new_zeros((0, 4)), scores.new_zeros((0,)))
    return (boxes[keep], scores[keep])

def study_key_from_path(path, mode='parent_dir'):
    if mode == 'parent_dir':
        return os.path.basename(os.path.dirname(path))
    elif mode == 'basename_prefix':
        base = os.path.basename(path)
        return base.split('_')[0]
    else:
        return os.path.basename(os.path.dirname(path))
GREEN = (0, 255, 0)
RED = (255, 0, 0)
YELLOW = (255, 215, 0)
WHITE = (255, 255, 255)
DARK_BG = (20, 20, 40)

def _draw_text_with_bg(draw, xy, text, fill, bg_fill=(0, 0, 0), font=None, pad=4):
    try:
        bbox = draw.textbbox(xy, text, font=font)
    except Exception:
        w, h = draw.textsize(text, font=font)
        bbox = (xy[0], xy[1], xy[0] + w, xy[1] + h)
    x1, y1, x2, y2 = bbox
    draw.rectangle([x1 - pad, y1 - pad, x2 + pad, y2 + pad], fill=bg_fill)
    draw.text(xy, text, fill=fill, font=font)

def _draw_header_footer(draw, img_width, img_height, label_str, font=None):
    scale_factor = min(img_width, img_height) / 512.0
    scale_factor = max(1.0, min(scale_factor, 4.0))
    header_height = int(60 * scale_factor)
    footer_height = int(65 * scale_factor)
    title_size = int(15 * scale_factor)
    result_size = int(20 * scale_factor)
    footer_size = int(16 * scale_factor)
    draw.rectangle([0, 0, img_width, header_height], fill=DARK_BG)
    draw.rectangle([0, img_height - footer_height, img_width, img_height], fill=DARK_BG)
    brand_text = 'Developed jointly by AI-PACS and Iran Nobat.'
    result_color = GREEN if label_str.lower() == 'normal' else RED
    result_text = f'Result: {label_str.upper()}'
    try:
        from PIL import ImageFont
        try:
            title_font = ImageFont.truetype('arial.ttf', title_size)
            result_font = ImageFont.truetype('arialbd.ttf', result_size)
            footer_font = ImageFont.truetype('arial.ttf', footer_size)
        except:
            title_font = result_font = footer_font = font
    except:
        title_font = result_font = footer_font = font
    padding_x = int(20 * scale_factor)
    padding_y = int(15 * scale_factor)
    _draw_text_with_bg(draw, (padding_x, padding_y), brand_text, fill=WHITE, bg_fill=DARK_BG, font=title_font, pad=0)
    try:
        result_bbox = draw.textbbox((0, 0), result_text, font=result_font)
        result_width = result_bbox[2] - result_bbox[0]
    except:
        result_width = int(len(result_text) * 16 * scale_factor)
    result_x = img_width - result_width - padding_x
    result_y = int(padding_y * 0.8)
    _draw_text_with_bg(draw, (result_x, result_y), result_text, fill=result_color, bg_fill=DARK_BG, font=result_font, pad=0)
    footer_text1 = '© 2025 AI-PACS & Iran Nobat. All rights reserved.'
    footer_text2 = 'Jointly developed AI module in collaboration between AI-PACS and Iran Nobat.'
    try:
        footer_bbox1 = draw.textbbox((0, 0), footer_text1, font=footer_font)
        footer_width1 = footer_bbox1[2] - footer_bbox1[0]
        footer_bbox2 = draw.textbbox((0, 0), footer_text2, font=footer_font)
        footer_width2 = footer_bbox2[2] - footer_bbox2[0]
    except:
        footer_width1 = int(len(footer_text1) * 10 * scale_factor)
        footer_width2 = int(len(footer_text2) * 10 * scale_factor)
    footer_x1 = (img_width - footer_width1) // 2
    footer_y1 = img_height - footer_height + int(8 * scale_factor)
    _draw_text_with_bg(draw, (footer_x1, footer_y1), footer_text1, fill=WHITE, bg_fill=DARK_BG, font=footer_font, pad=0)
    footer_x2 = (img_width - footer_width2) // 2
    footer_y2 = img_height - footer_height + int(28 * scale_factor)
    _draw_text_with_bg(draw, (footer_x2, footer_y2), footer_text2, fill=WHITE, bg_fill=DARK_BG, font=footer_font, pad=0)

def _draw_detection_info_box(draw, img_width, img_height, boxes_info, classification_label=None, laterality=None, font=None):
    if not boxes_info or len(boxes_info) == 0:
        return 0
    scale_factor = min(img_width, img_height) / 512.0
    scale_factor = max(1.0, min(scale_factor, 4.0))
    info_font_size = int(14 * scale_factor)
    line_height = int(24 * scale_factor)
    padding = int(10 * scale_factor)
    box_margin = int(10 * scale_factor)
    try:
        from PIL import ImageFont
        try:
            info_font = ImageFont.truetype('arial.ttf', info_font_size)
            info_font_bold = ImageFont.truetype('arialbd.ttf', info_font_size)
        except:
            info_font = info_font_bold = font
    except:
        info_font = info_font_bold = font
    num_boxes = len(boxes_info)
    num_class_lines = 0
    if classification_label:
        if isinstance(classification_label, list) and len(classification_label) > 0:
            if isinstance(classification_label[0], dict):
                num_class_lines = 1 + len(classification_label)
            else:
                num_class_lines = 1 + len(classification_label)
        elif isinstance(classification_label, str):
            try:
                import ast
                if classification_label.startswith('['):
                    parsed = ast.literal_eval(classification_label)
                    if isinstance(parsed, list):
                        num_class_lines = 1 + len(parsed)
                    else:
                        num_class_lines = 2
                else:
                    num_class_lines = 2
            except:
                num_class_lines = 2
        else:
            num_class_lines = 2
    num_lines = 1 + num_class_lines + num_boxes
    info_box_height = num_lines * line_height + 2 * padding
    max_text_width = 0
    if classification_label:
        title_text = 'Classification:'
        try:
            bbox = draw.textbbox((0, 0), title_text, font=info_font_bold)
            max_text_width = max(max_text_width, bbox[2] - bbox[0])
        except:
            max_text_width = max(max_text_width, len(title_text) * info_font_size * 0.6)
        if isinstance(classification_label, list):
            for result in classification_label:
                if isinstance(result, dict):
                    label = result.get('label', '')
                    prob = result.get('prob', 0.0)
                    text = f'  • {label}: {prob:.1%}'
                else:
                    text = f'  • {result}'
                try:
                    bbox = draw.textbbox((0, 0), text, font=info_font)
                    max_text_width = max(max_text_width, bbox[2] - bbox[0])
                except:
                    max_text_width = max(max_text_width, len(text) * info_font_size * 0.6)
    header_text = 'Detections:'
    try:
        bbox = draw.textbbox((0, 0), header_text, font=info_font_bold)
        max_text_width = max(max_text_width, bbox[2] - bbox[0])
    except:
        max_text_width = max(max_text_width, len(header_text) * info_font_size * 0.6)
    for box_info in boxes_info:
        idx = box_info.get('index', '?')
        score = box_info.get('score', 0.0)
        text = f'  [{idx}] Confidence: {score:.1%}'
        try:
            bbox = draw.textbbox((0, 0), text, font=info_font)
            max_text_width = max(max_text_width, bbox[2] - bbox[0])
        except:
            max_text_width = max(max_text_width, len(text) * info_font_size * 0.6)
    info_box_width = int(max_text_width + 2 * padding)
    if laterality and laterality.upper() == 'R':
        info_box_x = box_margin
    elif laterality and laterality.upper() == 'L':
        info_box_x = img_width - info_box_width - box_margin
    else:
        info_box_x = (img_width - info_box_width) // 2
    footer_height = int(65 * scale_factor)
    info_box_y = img_height - footer_height - info_box_height - box_margin
    draw.rectangle([info_box_x, info_box_y, info_box_x + info_box_width, info_box_y + info_box_height], fill=(30, 30, 50), outline=WHITE, width=2)
    current_y = info_box_y + padding
    text_x = info_box_x + padding
    if classification_label:
        class_results = []
        if isinstance(classification_label, list) and len(classification_label) > 0:
            if isinstance(classification_label[0], dict):
                class_results = classification_label
            else:
                for label in classification_label:
                    class_results.append({'label': str(label), 'prob': 1.0, 'pred': 1})
        elif isinstance(classification_label, str):
            try:
                import ast
                if classification_label.startswith('['):
                    parsed = ast.literal_eval(classification_label)
                    if isinstance(parsed, list):
                        for label in parsed:
                            class_results.append({'label': str(label), 'prob': 1.0, 'pred': 1})
                    else:
                        class_results.append({'label': str(parsed), 'prob': 1.0, 'pred': 1})
                else:
                    class_results.append({'label': classification_label, 'prob': 1.0, 'pred': 1})
            except:
                class_results.append({'label': str(classification_label), 'prob': 1.0, 'pred': 1})
        if class_results:
            title_text = 'Classification:'
            draw.text((text_x, current_y), title_text, fill=WHITE, font=info_font_bold)
            current_y += line_height
            for result in class_results:
                label = result.get('label', '').strip()
                prob = result.get('prob', 0.0)
                pred = result.get('pred', 0)
                if 'Mass' in label:
                    label_color = RED if pred == 1 else (100, 0, 0)
                elif 'Calcification' in label:
                    label_color = (255, 140, 0) if pred == 1 else (120, 70, 0)
                elif 'Asymmetry' in label:
                    label_color = (255, 100, 100) if pred == 1 else (120, 50, 50)
                elif 'No Finding' in label or 'Normal' in label:
                    label_color = GREEN if pred == 1 else (0, 100, 0)
                else:
                    label_color = WHITE if pred == 1 else (150, 150, 150)
                if pred == 1:
                    label_icon = f'  • {label}: {prob:.1%}'
                else:
                    label_icon = f'    {label}: {prob:.1%}'
                draw.text((text_x, current_y), label_icon, fill=label_color, font=info_font)
                current_y += line_height
    header_text = 'Detections:'
    draw.text((text_x, current_y), header_text, fill=WHITE, font=info_font_bold)
    current_y += line_height
    for box_info in boxes_info:
        idx = box_info.get('index', '?')
        score = box_info.get('score', 0.0)
        if score < 0.5:
            score_color = YELLOW
        elif score >= 0.7:
            score_color = RED
            if classification_label:
                first_label = None
                if isinstance(classification_label, list) and len(classification_label) > 0:
                    if isinstance(classification_label[0], dict):
                        first_label = classification_label[0].get('label', '')
                    else:
                        first_label = str(classification_label[0])
                elif isinstance(classification_label, str):
                    try:
                        import ast
                        if classification_label.startswith('['):
                            parsed = ast.literal_eval(classification_label)
                            if isinstance(parsed, list) and parsed:
                                first_label = str(parsed[0])
                        else:
                            first_label = classification_label
                    except:
                        first_label = classification_label
                if first_label:
                    if 'Mass' in first_label:
                        score_color = RED
                    elif 'Calcification' in first_label:
                        score_color = (255, 140, 0)
                    elif 'Asymmetry' in first_label:
                        score_color = (255, 100, 100)
                    elif 'No Finding' in first_label:
                        score_color = GREEN
        else:
            score_color = (255, 200, 100)
        info_text = f'  [{idx}] Confidence: {score:.1%}'
        draw.text((text_x, current_y), info_text, fill=score_color, font=info_font)
        current_y += line_height
    return info_box_height + box_margin

def save_overlay_image(img_path, pred_label_str, pred_boxes_orig=None, pred_scores=None, pred_classes=None, classification_label=None, laterality=None, overwrite=False, suffix='_pred', out_dir=None, name_mode='basename'):
    pred_boxes_orig = pred_boxes_orig or []
    pred_scores = pred_scores or []
    pred_classes = pred_classes or []
    img = Image.open(img_path).convert('RGB')
    W, H = img.size
    draw = ImageDraw.Draw(img)
    scale_factor = min(W, H) / 512.0
    scale_factor = max(1.0, min(scale_factor, 4.0))
    box_font_size = int(24 * scale_factor)
    box_thickness = max(5, int(10 * scale_factor))
    box_padding = int(8 * scale_factor)
    box_offset = int(10 * scale_factor)
    try:
        font = ImageFont.load_default()
        try:
            box_font = ImageFont.truetype('arialbd.ttf', box_font_size)
        except:
            try:
                box_font = ImageFont.truetype('arial.ttf', box_font_size)
            except:
                box_font = font
    except Exception:
        font = None
        box_font = None
    _draw_header_footer(draw, W, H, pred_label_str, font=font)
    boxes_info = []
    for idx, (b, s) in enumerate(zip(pred_boxes_orig, pred_scores)):
        boxes_info.append({'index': idx + 1, 'score': float(s)})
    if boxes_info:
        _draw_detection_info_box(draw, W, H, boxes_info, classification_label=classification_label, laterality=laterality, font=font)
    base_box_color = RED
    if classification_label:
        first_label = None
        if isinstance(classification_label, list) and len(classification_label) > 0:
            if isinstance(classification_label[0], dict):
                first_label = classification_label[0].get('label', '')
            else:
                first_label = str(classification_label[0])
        elif isinstance(classification_label, str):
            try:
                import ast
                if classification_label.startswith('['):
                    parsed = ast.literal_eval(classification_label)
                    if isinstance(parsed, list) and parsed:
                        first_label = str(parsed[0])
                else:
                    first_label = classification_label
            except:
                first_label = classification_label
        if first_label:
            if 'Mass' in first_label:
                base_box_color = RED
            elif 'Calcification' in first_label:
                base_box_color = (255, 140, 0)
            elif 'Asymmetry' in first_label:
                base_box_color = (255, 100, 100)
            elif 'No Finding' in first_label or 'Normal' in first_label:
                base_box_color = GREEN
    elif pred_label_str.lower() == 'normal':
        base_box_color = GREEN
    for idx, (b, s) in enumerate(zip(pred_boxes_orig, pred_scores)):
        x1, y1, x2, y2 = [float(v) for v in b]
        score_value = float(s)
        box_index = idx + 1
        if score_value < 0.5:
            current_box_color = YELLOW
        else:
            current_box_color = base_box_color
        for thickness in range(box_thickness):
            draw.rectangle([x1 - thickness // 2, y1 - thickness // 2, x2 + thickness // 2, y2 + thickness // 2], outline=current_box_color, width=1)
        index_text = f'[{box_index}]'
        try:
            index_bbox = draw.textbbox((0, 0), index_text, font=box_font)
            text_height = index_bbox[3] - index_bbox[1]
        except:
            text_height = int(box_font_size * 1.2)
        index_y = y1 - text_height - int(8 * scale_factor)
        if index_y < int(10 * scale_factor):
            index_y = y1 + int(8 * scale_factor)
        _draw_text_with_bg(draw, (x1 + box_offset, index_y), index_text, fill=WHITE, bg_fill=current_box_color, font=box_font, pad=box_padding)
    base = os.path.splitext(os.path.basename(img_path))[0]
    ext = os.path.splitext(img_path)[1]
    if name_mode == 'parent_basename':
        parent = os.path.basename(os.path.dirname(img_path))
        base = f'{parent}__{base}'
    out_name = f'{base}{ext}' if overwrite else f'{base}{suffix}{ext}'
    if out_dir is None or not os.path.isdir(out_dir):
        out_dir = os.path.dirname(img_path)
    out_path = os.path.join(out_dir, out_name)
    try:
        img.save(out_path)
    except Exception:
        out_path = os.path.join(out_dir, f'{base}{suffix}.png')
        img.save(out_path)
    return out_path

def regenerate_overlays_with_classification(output_root, classification_csv, verbose=True, use_logging=True):
    import ast
    import logging as log_module

    def log_msg(msg):
        if use_logging:
            log_module.info(msg)
        elif verbose:
            print(msg)
    boxes_csv_path = os.path.join(output_root, 'updated_csv_with_boxes.csv')
    if not os.path.isfile(boxes_csv_path):
        log_msg(f'[warn] Boxes CSV not found: {boxes_csv_path}')
        return 0
    df_boxes = pd.read_csv(boxes_csv_path, low_memory=False)
    log_msg(f'[regenerate] Read boxes CSV: {len(df_boxes)} rows')
    if not os.path.isfile(classification_csv):
        log_msg(f'[warn] Classification CSV not found: {classification_csv}')
        return 0
    df_class = pd.read_csv(classification_csv, low_memory=False)
    log_msg(f'[regenerate] Read classification CSV: {len(df_class)} rows')
    PATH_ID_CANDIDATES = ['dicom_full_path', 'full_image_path', 'lesion_image']
    path_col = next((c for c in PATH_ID_CANDIDATES if c in df_class.columns), None)
    if path_col:
        before = len(df_class)
        df_class = df_class.drop_duplicates(subset=[path_col], keep='last')
        log_msg(f'[regenerate] After removing duplicates (by {path_col}): {len(df_class)} rows (was {before})')
    elif 'laterality' in df_class.columns and 'view_position' in df_class.columns:
        log_msg('Ambiguous image association; review the source identity.')
        df_class = df_class.drop_duplicates(subset=['laterality', 'view_position'], keep='last')
        log_msg(f'[regenerate] After removing duplicates: {len(df_class)} rows')
    classification_map_by_path = {}
    classification_map_by_lat_view = {}
    for _, row in df_class.iterrows():
        lat = str(row.get('laterality', '')).strip().upper()
        view = str(row.get('view_position', '')).strip().upper()
        img_key = str(row.get(path_col, '')).strip() if path_col else ''
        results = []
        labels_list = ['Mass', 'Suspicious Calcification', 'Focal Asymmetry', 'No Finding']
        for label in labels_list:
            prob_col = f'prob_{label}'
            pred_col = f'pred_{label}'
            if prob_col in row and pred_col in row:
                prob = row.get(prob_col, 0.0)
                pred = row.get(pred_col, 0)
                results.append({'label': label, 'prob': float(prob), 'pred': int(pred)})
        if not results:
            results.append({'label': 'No Finding', 'prob': 1.0, 'pred': 1})
        if img_key:
            classification_map_by_path[img_key] = results
        if lat and view:
            classification_map_by_lat_view[lat, view] = results
    log_msg(f'[regenerate] Classification map created: {len(classification_map_by_path)} by-path entries, {len(classification_map_by_lat_view)} by-(lat,view) fallback entries')
    for key, val in classification_map_by_path.items():
        log_msg(f'[regenerate]   path={key}: {val}')
    log_msg(f'[regenerate] Regenerating {len(df_boxes)} overlay images with classification labels...')
    viz_dir = os.path.join(output_root, 'ALL_VIZ')
    os.makedirs(viz_dir, exist_ok=True)
    regenerated_count = 0
    for idx, row in df_boxes.iterrows():
        try:
            img_path_png = row.get('png_full_path', '') or row.get('image_path_png', '')
            if not img_path_png or not os.path.isfile(img_path_png):
                log_msg(f'[warn] Row {idx}: PNG not found or invalid: {img_path_png}')
                continue
            lat = str(row.get('laterality', '')).strip().upper()
            view = str(row.get('view_position', '')).strip().upper()
            if (not lat or not view) and 'dicom_full_path' in row:
                dicom_path = row.get('dicom_full_path', '')
                if dicom_path and os.path.isfile(dicom_path):
                    try:
                        import pydicom
                        dcm = pydicom.dcmread(dicom_path, stop_before_pixels=True)
                        if not lat and hasattr(dcm, 'ImageLaterality'):
                            lat = str(dcm.ImageLaterality).strip().upper()
                        if not view and hasattr(dcm, 'ViewPosition'):
                            view = str(dcm.ViewPosition).strip().upper()
                        if (not lat or not view) and hasattr(dcm, 'SeriesDescription'):
                            series_desc = str(dcm.SeriesDescription).strip()
                            if '-' in series_desc:
                                parts = series_desc.split('-', 1)
                                if len(parts) == 2:
                                    pre, post = (parts[0].strip(), parts[1].strip())
                                    if not lat and pre and (pre[0].upper() in ('R', 'L')):
                                        lat = pre[0].upper()
                                    if not view:
                                        i = 0
                                        while i < len(post) and post[i].isalpha():
                                            i += 1
                                        view = post[:i].upper()
                    except Exception as e:
                        log_msg(f'[warn] Could not read DICOM metadata for row {idx}: {e}')
            log_msg(f'[debug] Row {idx}: lat={lat}, view={view}, png={os.path.basename(img_path_png)}')
            dicom_path_for_lookup = str(row.get('dicom_full_path', '')).strip()
            class_results = classification_map_by_path.get(dicom_path_for_lookup, [])
            if not class_results:
                class_results = classification_map_by_lat_view.get((lat, view), [])
            if not class_results:
                log_msg(f'[warn] No classification found for ({lat}, {view})')
            boxes_str = row.get('bbox_original_coords', '') or row.get('box', '')
            try:
                if isinstance(boxes_str, str) and boxes_str.strip():
                    boxes = ast.literal_eval(boxes_str)
                else:
                    boxes = []
            except Exception as e:
                log_msg(f'[warn] Row {idx}: Could not parse boxes: {e}')
                boxes = []
            scores_str = row.get('bbox_scores', '') or row.get('scores', '')
            try:
                if isinstance(scores_str, str) and scores_str.strip():
                    scores = ast.literal_eval(scores_str)
                    log_msg(f'[debug] Row {idx}: Parsed {len(scores)} scores from CSV')
                else:
                    scores = []
            except Exception as e:
                log_msg(f'[warn] Row {idx}: Could not parse scores: {e}')
                scores = []
            if len(boxes) > 0 and len(scores) == 0:
                scores = [1.0] * len(boxes)
                log_msg(f'[warn] Row {idx}: No scores found, using default 1.0 for {len(boxes)} boxes')
            pred_label = row.get('pred_label_str', '').lower()
            if not pred_label:
                pred_label = 'abnormal' if len(boxes) > 0 else 'normal'
            base_name = os.path.splitext(os.path.basename(img_path_png))[0]
            old_pred_file = os.path.join(viz_dir, f'{base_name}_pred.png')
            if os.path.isfile(old_pred_file):
                try:
                    os.remove(old_pred_file)
                    log_msg(f'[debug] Removed old: {os.path.basename(old_pred_file)}')
                except Exception as e:
                    log_msg(f'[warn] Could not remove old file: {e}')
            out_path = save_overlay_image(img_path=img_path_png, pred_label_str=pred_label, pred_boxes_orig=boxes, pred_scores=scores, pred_classes=[], classification_label=class_results, laterality=lat, overwrite=False, suffix='_pred', out_dir=viz_dir, name_mode='basename')
            regenerated_count += 1
            log_msg(f'[regenerate] Processed {regenerated_count}/{len(df_boxes)}: {os.path.basename(out_path)}')
        except Exception as e:
            import traceback
            log_msg(f"[ERROR] Failed to regenerate row {idx}, png={row.get('image_path_png', 'unknown')}")
            log_msg(f'        Error: {e}')
            log_msg(f'        Traceback: {traceback.format_exc()}')
            continue
    log_msg(f'[regenerate] Regenerated {regenerated_count} overlay images with classification labels')
    return regenerated_count

def run_inference():
    img_paths = list_pngs(INPUT_DIR, recursive=RECURSIVE)
    if len(img_paths) == 0:
        print(f'No PNG files found in: {INPUT_DIR}')
        return
    os.makedirs(OUT_DIR_ROOT, exist_ok=True)
    print(f'Images to infer: {len(img_paths)}')
    ds = InferenceDataset(img_paths)
    loader = DataLoader(ds, batch_size=BATCH_SIZE, shuffle=False, num_workers=NUM_WORKERS, pin_memory=True, collate_fn=collate_fn)
    model, device, load_report = load_model()
    per_image_records = []
    with torch.inference_mode(), torch.amp.autocast('cuda', enabled=torch.cuda.is_available()):
        for images, metas in loader:
            images = [im.to(device) for im in images]
            outputs = model(images)
            if TTA_HFLIP:
                flipped = [hflip_tv_image(im) for im in images]
                outputs_flip = model(flipped)
            else:
                outputs_flip = [None] * len(outputs)
            for meta, out, out_f in zip(metas, outputs, outputs_flip):
                path = meta['path']
                scores = out.get('scores', torch.empty(0, device=device))
                boxes = out.get('boxes', torch.empty(0, 4, device=device))
                aux_p = float(out.get('image_score', 0.0))
                if TTA_HFLIP and out_f is not None:
                    scores_f = out_f.get('scores', torch.empty(0, device=device))
                    boxes_f = out_f.get('boxes', torch.empty(0, 4, device=device))
                    aux_p_f = float(out_f.get('image_score', 0.0))
                    boxes_f_unflipped = unflip_boxes_xyxy_on_resized(boxes_f, IMG_SIZE)
                    boxes, scores = merge_tta_predictions(boxes, scores, boxes_f_unflipped, scores_f, nms_thr=MODEL_NMS_THR)
                    aux_p = 0.5 * (aux_p + aux_p_f)
                boxes, scores = filter_tiny_boxes(boxes, scores, MIN_BOX_AREA_FRAC, IMG_SIZE)
                per_image_records.append({'path': path, 'orig_size': meta['orig_size'], 'scores': scores.detach().cpu(), 'boxes': boxes.detach().cpu(), 'aux_prob': float(aux_p)})
    rows = []
    cnt = {'det_abn': 0, 'det_norm': 0, 'aux_abn': 0, 'aux_norm': 0, 'fused_abn': 0, 'fused_norm': 0, 'final_abn': 0, 'final_norm': 0}
    study_groups = defaultdict(list) if AGGREGATE_BY_STUDY else None
    for rec in per_image_records:
        path = rec['path']
        scores = rec['scores']
        boxes = rec['boxes']
        aux_p = rec['aux_prob']
        p_det = abnormal_from_scores(scores, DET_EVAL_SCORE_THR)
        p_aux = abnormal_from_auxprob(aux_p, AUX_EVAL_THR)
        p_fuse = p_det or p_aux
        p_final = p_det
        cnt['det_abn'] += int(p_det)
        cnt['det_norm'] += int(not p_det)
        cnt['aux_abn'] += int(p_aux)
        cnt['aux_norm'] += int(not p_aux)
        cnt['fused_abn'] += int(p_fuse)
        cnt['fused_norm'] += int(not p_fuse)
        cnt['final_abn'] += int(p_final)
        cnt['final_norm'] += int(not p_final)
        keep = scores >= DET_EVAL_SCORE_THR if scores.numel() > 0 else torch.zeros(0, dtype=torch.bool)
        scores_k = scores[keep].tolist() if scores.numel() > 0 else []
        boxes_k = boxes[keep].tolist() if boxes.numel() > 0 else []
        W0, H0 = rec['orig_size']
        boxes_k_orig = resize_boxes_to_original(boxes_k, (W0, H0), IMG_SIZE) if len(boxes_k) > 0 else []
        viz_boxes = boxes_k_orig if p_final else []
        pred_label_str = 'abnormal' if p_final else 'normal'
        viz_path = ''
        if SAVE_ALL_OVERLAYS:
            viz_path = save_overlay_image(img_path=path, pred_label_str=pred_label_str, pred_boxes_orig=viz_boxes, pred_scores=scores_k if p_final else [], overwrite=False, suffix=SAVE_NAME_SUFFIX, out_dir=VIZ_OUT_DIR, name_mode=VIZ_NAME_MODE)
        rows.append({'frame': path, 'det_label_pred': 'abnormal' if p_det else 'normal', 'aux_label_pred': 'abnormal' if p_aux else 'normal', 'fused_label_pred': 'abnormal' if p_fuse else 'normal', 'final_label_pred': 'abnormal' if p_final else 'normal', 'num_dets': int(scores.numel()), 'num_dets_ge_thr': int(len(scores_k)), 'max_score': float(max(scores.tolist()) if scores.numel() > 0 else 0.0), 'aux_prob': float(aux_p), 'scores_json': json.dumps([float(s) for s in scores_k]), 'boxes_json': json.dumps([[float(x) for x in b] for b in boxes_k]), 'boxes_json_original': json.dumps([[float(x) for x in b] for b in boxes_k_orig]), 'viz_path': viz_path})
        if AGGREGATE_BY_STUDY:
            key = study_key_from_path(path, STUDY_KEY_MODE)
            study_groups[key].append({'pred_abn': p_fuse, 'path': path})
    os.makedirs(os.path.dirname(OUT_PRED_CSV) or '.', exist_ok=True)
    pd.DataFrame(rows).to_csv(OUT_PRED_CSV, index=False)
    print(f'Saved per-image predictions → {OUT_PRED_CSV}')
    study_summary_text = ''
    if AGGREGATE_BY_STUDY and study_groups:
        study_rows = []
        for key, tiles in study_groups.items():
            num_abn_tiles = sum((1 for t in tiles if t['pred_abn']))
            pred_study_abn = num_abn_tiles >= STUDY_VOTE_K
            study_rows.append({'study_key': key, 'pred_label': 'abnormal' if pred_study_abn else 'normal', 'num_tiles': len(tiles), 'num_abnormal_tiles': num_abn_tiles})
        pd.DataFrame(study_rows).to_csv(OUT_PRED_STUDY_CSV, index=False)
        print(f'Saved study-level predictions → {OUT_PRED_STUDY_CSV}')
        abn_studies = sum((1 for r in study_rows if r['pred_label'] == 'abnormal'))
        norm_studies = sum((1 for r in study_rows if r['pred_label'] == 'normal'))
        study_summary_text = f'\nStudy-level (aggregated) predictions\n------------------------------------\nVote rule: abnormal if ≥{STUDY_VOTE_K} tiles abnormal (key={STUDY_KEY_MODE})\nStudies predicted ABNORMAL: {abn_studies}\nStudies predicted NORMAL  : {norm_studies}\n'
        print(study_summary_text)
    sweep_rows = []
    for thr in SWEEP_THRESHOLDS:
        det_abn = 0
        fused_abn = 0
        for rec in per_image_records:
            p_det = abnormal_from_scores(rec['scores'], thr)
            p_aux = abnormal_from_auxprob(rec['aux_prob'], AUX_EVAL_THR)
            p_fuse = p_det or p_aux
            det_abn += int(p_det)
            fused_abn += int(p_fuse)
        sweep_rows.append({'thr': thr, 'det_abnormal_count': det_abn, 'fused_abnormal_count': fused_abn})
    pd.DataFrame(sweep_rows).to_csv(OUT_SWEEP_CSV, index=False)
    print(f'Saved sweep counts → {OUT_SWEEP_CSV}')
    with open(OUT_SUMMARY_TXT, 'w', encoding='utf-8') as f:
        f.write('Inference Summary (NO ground truth)\n')
        f.write('-----------------------------------\n')
        f.write(f'Images processed                  : {len(per_image_records)}\n')
        f.write(f'Detector decision threshold used  : {DET_EVAL_SCORE_THR:.2f}\n')
        f.write(f'Aux image_score threshold used    : {AUX_EVAL_THR:.2f}\n')
        f.write(f'Detector runtime threshold        : {MODEL_SCORE_THR:.2f}\n')
        f.write(f'NMS threshold                     : {MODEL_NMS_THR:.2f}\n')
        f.write(f'TTA horizontal flip enabled?      : {TTA_HFLIP}\n')
        f.write(f'Min box area fraction             : {MIN_BOX_AREA_FRAC:.5f}\n')
        f.write(f'Final decision mode               : {DECISION_MODE} (FINAL == DETECTOR)\n')
        f.write('\n== Weight loading ==\n')
        f.write(f"Mode: {load_report.get('mode')}\n")
        f.write(f"Path(s): {load_report.get('path_used')}\n")
        f.write(f"Details: {load_report.get('details')}\n")
        f.write(f'\nCounts by decision mode:\n')
        f.write(f"[DETECTOR] abnormal:{cnt['det_abn']} normal:{cnt['det_norm']}\n")
        f.write(f"[AUX     ] abnormal:{cnt['aux_abn']} normal:{cnt['aux_norm']}\n")
        f.write(f"[FUSED OR] abnormal:{cnt['fused_abn']} normal:{cnt['fused_norm']}\n")
        f.write(f"[FINAL   ] abnormal:{cnt['final_abn']} normal:{cnt['final_norm']}  (same as DETECTOR)\n")
        f.write(f'\nPer-image CSV : {OUT_PRED_CSV}\n')
        f.write(f'Sweep CSV     : {OUT_SWEEP_CSV}\n')
        f.write(f'Viz folder    : {VIZ_OUT_DIR}\n')
        if study_summary_text:
            f.write(study_summary_text)
    print(f'Saved summary → {OUT_SUMMARY_TXT}')
    if INPUT_CSV and os.path.isfile(INPUT_CSV):
        try:
            df_in = pd.read_csv(INPUT_CSV)
            df_pred = pd.read_csv(OUT_PRED_CSV)[['frame', 'boxes_json_original', 'scores_json']]
            df_pred.rename(columns={'frame': 'png_full_path', 'boxes_json_original': 'box', 'scores_json': 'scores'}, inplace=True)
            df_out = df_in.merge(df_pred, on='png_full_path', how='left')
            out_csv_with_boxes = os.path.join(OUT_DIR_ROOT, 'updated_csv_with_boxes.csv')
            df_out.to_csv(out_csv_with_boxes, index=False)
            print(f'Updated input CSV with boxes (ORIGINAL coords) & scores → {out_csv_with_boxes}')
        except Exception as e:
            print(f'[warn] Failed to update input CSV: {e}')

def run_inference_safe(input_dir: str, output_dir: str, det_eval_thr: Optional[float]=None, aux_eval_thr: Optional[float]=None, log_file: Optional[str]=None, input_csv: Optional[str]=None) -> str:
    if not isinstance(input_dir, str) or not input_dir:
        return '[error] input_dir must be a non-empty string'
    if not isinstance(output_dir, str) or not output_dir:
        return '[error] output_dir must be a non-empty string'
    if not os.path.isdir(input_dir):
        return f'[error] input_dir does not exist: {input_dir}'
    set_input_dir(input_dir, recursive=True)
    set_output_dir(output_dir)
    set_thresholds(det_eval=det_eval_thr, aux_eval=aux_eval_thr)
    set_input_csv(input_csv)
    if log_file is None:
        log_file = os.path.join(output_dir, 'run.log')
    os.makedirs(os.path.dirname(log_file) or '.', exist_ok=True)
    try:
        with open(log_file, 'w', encoding='utf-8') as fp:
            tee_out = _Tee(fp, sys.__stdout__)
            tee_err = _Tee(fp, sys.__stderr__)
            old_out, old_err = (sys.stdout, sys.stderr)
            sys.stdout, sys.stderr = (tee_out, tee_err)
            try:
                print(f'[info] Starting inference with input_dir={input_dir}')
                print(f'[info] Output dir: {output_dir}')
                print(f'[info] Thresholds: DET_EVAL_SCORE_THR={DET_EVAL_SCORE_THR:.2f}, AUX_EVAL_THR={AUX_EVAL_THR:.2f}')
                run_inference()
                print('[info] Inference finished.')
            except RuntimeError as e:
                if 'out of memory' in str(e).lower():
                    print('[error] CUDA out of memory. Consider reducing BATCH_SIZE or IMG_SIZE.')
                else:
                    print(f'[error] RuntimeError: {e}')
                return f'[error] Inference failed: {e}'
            except Exception as e:
                print(f'[error] Unexpected failure: {e}')
                return f'[error] Inference failed: {e}'
            finally:
                sys.stdout, sys.stderr = (old_out, old_err)
    except Exception as e:
        run_inference()
        return f'[warn] Logging failed ({e}); inference finished without log tee. Outputs: {output_dir}'
    return f'FINISHED: saved outputs to {output_dir}. Log: {log_file}'
