# Imported inference implementation; provenance in ../provenance.json.
import os
import math
import logging
from typing import Optional, List, Tuple
import numpy as np
import cv2
from PIL import Image, ImageOps
import torch
import torch.nn as nn
import timm
import albumentations as A
from albumentations.pytorch import ToTensorV2
log = logging.getLogger('BoneAgeAPI')
if not log.handlers:
    logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(levelname)s | %(message)s')
MODEL_WEIGHTS = os.environ.get('BONE_AGE_MODEL_WEIGHTS', os.path.join(os.path.dirname(__file__), 'final_model.pth'))
MODEL_NAME = 'eva02_base_patch14_448.mim_in22k_ft_in22k_in1k'
IMG_SIZE = 448
USE_GENDER = True
DROPOUT_RATE = 0.3
DROP_PATH_RATE = 0.1
MAX_AGE_MONTHS = 228.0
TARGET_MIN, TARGET_MAX = (0.0, 228.0)
MEAN_RGB = [0.2631, 0.2631, 0.2631]
STD_RGB = [0.2243, 0.2243, 0.2243]
CLAHE_CLIP_LIMIT = 3.0
CLAHE_TILE_GRID = (8, 8)
USE_FLIP_TTA = True

def sex_to_id(s: str) -> int:
    s = str(s).strip().lower()
    return 1 if s in {'male', 'm', '1', 'true', 't'} else 0

class GenderFiLM(nn.Module):

    def __init__(self, feature_dim: int, embed_dim: int=128):
        super().__init__()
        self.embed = nn.Embedding(2, embed_dim)
        self.mlp = nn.Sequential(nn.Linear(embed_dim, embed_dim * 2), nn.SiLU(), nn.LayerNorm(embed_dim * 2), nn.Linear(embed_dim * 2, embed_dim * 2), nn.SiLU(), nn.Linear(embed_dim * 2, feature_dim * 2))

    def forward(self, features: torch.Tensor, gender: torch.Tensor) -> torch.Tensor:
        g_emb = self.embed(gender)
        out = self.mlp(g_emb)
        gamma, beta = out.chunk(2, dim=-1)
        return gamma * features + beta

class ResidualRegressionHead(nn.Module):

    def __init__(self, in_dim: int, hidden_dim: int=512, dropout: float=0.3):
        super().__init__()
        self.block1 = nn.Sequential(nn.Linear(in_dim, hidden_dim), nn.LayerNorm(hidden_dim), nn.GELU(), nn.Dropout(dropout))
        self.block2 = nn.Sequential(nn.Linear(hidden_dim, hidden_dim // 2), nn.LayerNorm(hidden_dim // 2), nn.GELU(), nn.Dropout(dropout * 0.5))
        self.skip = nn.Linear(in_dim, hidden_dim // 2, bias=False)
        self.out = nn.Linear(hidden_dim // 2, 1)

    def forward(self, x):
        h = self.block1(x)
        h = self.block2(h) + self.skip(x)
        return self.out(h).squeeze(-1)

class BoneAgeViT(nn.Module):

    def __init__(self, model_name: str, use_gender: bool=True, dropout_rate: float=0.3, drop_path_rate: float=0.1, pretrained_backbone: bool=False):
        super().__init__()
        self.use_gender = use_gender
        self.backbone = timm.create_model(model_name, pretrained=pretrained_backbone, num_classes=0, global_pool='token', drop_path_rate=drop_path_rate)
        feat_dim = self.backbone.num_features
        self.vit_blocks = self._get_vit_blocks()
        self.gender_film = GenderFiLM(feat_dim, embed_dim=128) if use_gender else None
        self.shared = nn.Sequential(nn.LayerNorm(feat_dim), nn.Dropout(dropout_rate))
        self.reg_head = ResidualRegressionHead(feat_dim, hidden_dim=512, dropout=dropout_rate)
        self.unc_head = nn.Sequential(nn.Linear(feat_dim, 128), nn.GELU(), nn.Dropout(dropout_rate * 0.5), nn.Linear(128, 1))

    def _get_vit_blocks(self):
        if hasattr(self.backbone, 'blocks'):
            return self.backbone.blocks
        elif hasattr(self.backbone, 'layers'):
            return self.backbone.layers
        return nn.ModuleList()

    def forward(self, x: torch.Tensor, gender: torch.Tensor=None) -> Tuple[torch.Tensor, torch.Tensor]:
        features = self.backbone(x)
        if features.dim() == 3:
            features = features.mean(dim=1)
        if self.use_gender and gender is not None:
            features = self.gender_film(features, gender)
        shared = self.shared(features)
        pred = self.reg_head(shared)
        logvar = self.unc_head(shared).squeeze(-1)
        return (pred, logvar)

def load_model(weights_path: str, device: torch.device) -> BoneAgeViT:
    model = BoneAgeViT(MODEL_NAME, use_gender=USE_GENDER, dropout_rate=DROPOUT_RATE, drop_path_rate=DROP_PATH_RATE, pretrained_backbone=False).to(device)
    state = torch.load(weights_path, map_location=device)
    if isinstance(state, dict) and 'model_state_dict' in state:
        state = state['model_state_dict']
    model.load_state_dict(state, strict=True)
    model.eval()
    return model

def letterbox_resize(gray: np.ndarray, size: int) -> np.ndarray:
    h, w = gray.shape[:2]
    scale = size / max(h, w)
    new_w, new_h = (max(1, round(w * scale)), max(1, round(h * scale)))
    resized = cv2.resize(gray, (new_w, new_h), interpolation=cv2.INTER_AREA)
    canvas = np.zeros((size, size), dtype=np.uint8)
    top = (size - new_h) // 2
    left = (size - new_w) // 2
    canvas[top:top + new_h, left:left + new_w] = resized
    return canvas

def bone_specific_preprocessing(image_rgb: np.ndarray, debug_tag: str='') -> np.ndarray:
    if image_rgb is None or image_rgb.size == 0:
        log.error(f"[preproc]{(' ' + debug_tag if debug_tag else '')} empty image — returning blank canvas")
        return np.zeros((IMG_SIZE, IMG_SIZE, 3), dtype=np.uint8)
    gray = cv2.cvtColor(image_rgb, cv2.COLOR_RGB2GRAY) if image_rgb.ndim == 3 else image_rgb
    clahe = cv2.createCLAHE(clipLimit=CLAHE_CLIP_LIMIT, tileGridSize=CLAHE_TILE_GRID)
    enhanced = clahe.apply(gray)
    letterboxed = letterbox_resize(enhanced, IMG_SIZE)
    rgb = cv2.cvtColor(letterboxed, cv2.COLOR_GRAY2RGB)
    h, w = image_rgb.shape[:2]
    aspect = w / h if h else 0
    nonzero_frac = float(np.count_nonzero(letterboxed)) / letterboxed.size
    log.info(f"[preproc][diag]{(' ' + debug_tag if debug_tag else '')} source_aspect_w/h={aspect:.2f} letterbox_nonzero_frac={nonzero_frac:.2f}")
    log.info(f"[preproc]{(' ' + debug_tag if debug_tag else '')} input={image_rgb.shape[1]}x{image_rgb.shape[0]} -> letterboxed {IMG_SIZE}x{IMG_SIZE} | out mean={rgb.mean():.1f} std={rgb.std():.1f}")
    return rgb

def get_val_transform():
    return A.Compose([A.Resize(IMG_SIZE, IMG_SIZE), A.Normalize(mean=MEAN_RGB, std=STD_RGB), ToTensorV2()])

def pil_to_rgb_ndarray(im: Image.Image) -> np.ndarray:
    return np.array(im.convert('RGB'))

@torch.no_grad()
def predict_one(model: BoneAgeViT, image: Image.Image, sex_id: int, device: torch.device, use_flip_tta: bool=USE_FLIP_TTA, debug_tag: str='') -> float:
    rgb = pil_to_rgb_ndarray(image)
    processed = bone_specific_preprocessing(rgb, debug_tag=debug_tag)
    tf = get_val_transform()
    tensor = tf(image=processed)['image'].unsqueeze(0).to(device)
    gender = torch.tensor([sex_id], dtype=torch.long, device=device)
    if use_flip_tta:
        pred_a, logvar_a = model(tensor, gender)
        pred_b, logvar_b = model(torch.flip(tensor, dims=[3]), gender)
        preds = torch.stack([pred_a, pred_b])
        logvars = torch.stack([logvar_a, logvar_b])
        lv_clamped = torch.clamp(logvars, min=-4.0, max=2.0)
        inv_var = torch.exp(-lv_clamped)
        w = inv_var / (inv_var.sum(dim=0, keepdim=True) + 1e-08)
        pred = (preds * w).sum(dim=0)
    else:
        pred, _ = model(tensor, gender)
    pred_months = pred.item() * MAX_AGE_MONTHS
    clamped = float(max(TARGET_MIN, min(TARGET_MAX, pred_months)))
    if clamped != pred_months:
        log.warning(f"[predict_one]{(' ' + debug_tag if debug_tag else '')} raw prediction {pred_months:.2f} clamped to {clamped:.2f} months")
    log.info(f"[predict_one]{(' ' + debug_tag if debug_tag else '')} sex_id={sex_id} use_flip_tta={use_flip_tta} -> {clamped:.2f} months ({clamped / 12.0:.2f} years)")
    return clamped

def main():
    import argparse
    parser = argparse.ArgumentParser(description='Single-step bone age inference on one image')
    parser.add_argument('image_path')
    parser.add_argument('--sex', default='female', choices=['male', 'female'])
    parser.add_argument('--no-tta', action='store_true', help='disable flip TTA')
    args = parser.parse_args()
    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    if not os.path.isfile(MODEL_WEIGHTS):
        raise FileNotFoundError(f'Weights not found: {MODEL_WEIGHTS}')
    model = load_model(MODEL_WEIGHTS, device)
    with Image.open(args.image_path) as im:
        im = ImageOps.exif_transpose(im)
        pred_m = predict_one(model, im, sex_to_id(args.sex), device, use_flip_tta=not args.no_tta, debug_tag=os.path.basename(args.image_path))
    print('----- Inference -----')
    print(f'Image: {args.image_path}')
    print(f'Sex: {args.sex}')
    print(f'Predicted bone age: {pred_m:.2f} months ({pred_m / 12.0:.2f} years)')
