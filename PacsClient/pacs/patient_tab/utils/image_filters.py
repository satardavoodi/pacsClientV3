"""
Image Filtering Module for Medical Image Enhancement
====================================================
فیلترها به دو دسته اصلی تقسیم می‌شوند:
۱. فیلترهای هموارسازی (Smoothing) برای کاهش نویز
۲. فیلترهای تیزکننده (Sharpening) برای افزایش وضوح

تمامی پارامترها بر اساس واحد میلی‌متر تنظیم شده‌اند و نسبت به spacing تصویر تطبیق می‌یابند.
"""

import os
import SimpleITK as sitk
import numpy as np
import time
from pathlib import Path
import json
from typing import Dict

# Attempt to load project-level config path; fallback to local ./config directory
try:
    from PacsClient.utils.config import SOCKET_CONFIG_PATH
except Exception:
    SOCKET_CONFIG_PATH = Path.cwd() / "config"

# --- Configuration file for modality grid layouts ---
FILTER_CONFIG_PATH = Path(SOCKET_CONFIG_PATH) / "filter_settings.json"


def _smooth_xy_recursive(img: sitk.Image, sigma_xy: float = 0.8, sigma_z: float | None = None) -> sitk.Image:
    """
    هموارسازی گاوسی بازگشتی روی صفحات XY با امکان اعمال در جهت Z برای تصاویر سه‌بعدی.
    
    این تابع از فیلتر گاوسی بازگشتی (RecursiveGaussian) استفاده می‌کند که از نظر محاسباتی
    بهینه‌تر از فیلتر گاوسی استاندارد است. فیلتر ابتدا در جهت X، سپس Y و در صورت
    نیاز در جهت Z اعمال می‌شود.
    
    Parameters
    ----------
    img : sitk.Image
        تصویر ورودی SimpleITK (ideally already float32 when called from apply_filters)
    sigma_xy : float, default=0.8
        مقدار سیگمای فیلتر گاوسی در صفحات XY (میلی‌متر)
    sigma_z : float or None, default=None
        مقدار سیگمای فیلتر گاوسی در جهت Z (میلی‌متر)
        • اگر None باشد، برابر sigma_xy در نظر گرفته می‌شود
        • اگر 0 باشد یا تصویر 2D باشد، در جهت Z اعمال نمی‌شود
        
    Returns
    -------
    sitk.Image
        تصویر هموار شده — returned in the SAME pixel type as input.
        v2.2.3.2.3: When caller passes float32 (apply_filters already casts),
        the redundant Cast(float32) at entry and Cast(original) at exit are
        skipped.  This eliminates 6 GIL-holding cast operations per MR series
        (3 calls × 2 casts each), saving ~100-200ms of GIL time during
        Mode B DL_WARMUP background loads.
    """
    # v2.2.3.2.3: Only cast if input is NOT already float32 — the common
    # case from apply_filters() is that it already casted at the top.
    _input_pixel_id = img.GetPixelID()
    _already_float32 = (_input_pixel_id == sitk.sitkFloat32)
    if _already_float32:
        imgf = img
    else:
        imgf = sitk.Cast(img, sitk.sitkFloat32)

    # اعمال فیلتر گاوسی بازگشتی در جهت X
    out = sitk.RecursiveGaussian(imgf, sigma=sigma_xy, direction=0)
    # اعمال فیلتر گاوسی بازگشتی در جهت Y
    out = sitk.RecursiveGaussian(out, sigma=sigma_xy, direction=1)

    # اعمال اختیاری در جهت Z برای تصاویر سه‌بعدی
    if out.GetDimension() == 3:
        nx, ny, nz = out.GetSize()
        if sigma_z is None:
            sigma_z = sigma_xy  # مقدار پیش‌فرض
        # فقط اگر تعداد اسلایس‌ها کافی باشد و sigma مثبت باشد
        if nz >= 4 and sigma_z > 0:
            out = sitk.RecursiveGaussian(out, sigma=sigma_z, direction=2)

    # v2.2.3.2.3: Return in the same pixel type as input — avoid
    # redundant Cast when caller is already working in float32.
    if _already_float32:
        return out
    return sitk.Cast(out, _input_pixel_id)


def _clip_to_reference_range(
    sharpened_arr: np.ndarray,
    reference_arr: np.ndarray,
) -> np.ndarray:
    """
    Clamp sharpened data back to the original intensity range.

    This prevents bright/dark overshoot halos at strong tissue/background
    edges, which is especially visible on MR after repeated sharpening stages.
    """
    ref_min = float(np.min(reference_arr))
    ref_max = float(np.max(reference_arr))
    if ref_max <= ref_min:
        return np.asarray(reference_arr, dtype=np.float32)
    return np.clip(np.asarray(sharpened_arr, dtype=np.float32), ref_min, ref_max)


def _radius_from_mm(mm: float, spacing: tuple[float, ...], dim: int) -> list[int]:
    """
    تبدیل پهنای ساختاری از میلی‌متر به شعاع پیکسلی برای هر بعد.
    
    این تابع برای تبدیل اندازه‌های فیزیکی (میلی‌متر) به واحد پیکسل استفاده می‌شود
    تا فیلترها مستقل از رزولوشن تصویر عمل کنند.
    
    Parameters
    ----------
    mm : float
        پهنای ساختاری بر حسب میلی‌متر
        • مقدار مثبت: شعاع مورد نظر
        • مقدار صفر یا منفی: حداقل یک پیکسل در نظر گرفته می‌شود
    spacing : tuple[float, ...]
        فاصله پیکسل‌ها در هر بعد بر حسب میلی‌متر
        • مثال برای CT: (0.5, 0.5, 1.0) به معنی 0.5mm در XY و 1mm در Z
    dim : int
        تعداد ابعاد تصویر (۲ برای 2D، ۳ برای 3D)
        
    Returns
    -------
    list[int]
        لیست شعاع‌ها در هر بعد بر حسب پیکسل
        • حداقل مقدار ۱ پیکسل است حتی اگر mm کوچک باشد
        
    Examples
    --------
    >>> _radius_from_mm(2.0, (0.5, 0.5, 1.0), 3)
    [4, 4, 2]  # 2mm / 0.5mm = 4 پیکسل در XY، 2mm / 1.0mm = 2 پیکسل در Z
    """
    if mm is None or mm <= 0:
        return [1] * dim
    return [max(1, int(round(mm / spacing[i]))) for i in range(dim)]


def edge_smooth_ultrafast(
    img: sitk.Image,
    *,
    blur_sigma_mm: float = 1.0,
    edge_sigma_mm: float = 0.4,
    k_std: float = 2.5,
    pow_sharp: float = 1.0,
    w_blur_mm: float = 0.8,
    sigma_z: float | None = None
) -> sitk.Image:
    """
    هموارسازی هوشمند فقط در اطراف لبه‌ها با سرعت بالا.

    این تابع یک روش پیشرفته برای نرم کردن لبه‌ها بدون از دست دادن جزئیات است.
    ابتدا لبه‌های قوی شناسایی می‌شوند، سپس یک ناحیه اطراف آنها به صورت
    نرم محو می‌شود. این کار باعث می‌شود لبه‌ها طبیعی‌تر به نظر برسند
    در حالی که جزئیات ظریف حفظ می‌شوند.

    Parameters
    ----------
    img : sitk.Image
        تصویر ورودی SimpleITK
    blur_sigma_mm : float, default=1.0
        شدت هموارسازی اعمال شده روی لبه‌ها (میلی‌متر)
        • مقدار بیشتر: لبه‌های نرم‌تر
        • مقدار کمتر: حفظ تیزی لبه‌ها
        • محدوده پیشنهادی: 0.5 تا 2.0 میلی‌متر
    edge_sigma_mm : float, default=0.4
        سیگمای گاوسی برای تشخیص لبه‌ها (میلی‌متر)
        • مقدار بیشتر: تشخیص لبه‌های درشت‌تر
        • مقدار کمتر: تشخیص لبه‌های ظریف‌تر
        • محدوده پیشنهادی: 0.2 تا 0.8 میلی‌متر
    k_std : float, default=2.5
        ضریب انحراف معیار برای آستانه‌گذاری لبه‌ها
        • مقدار بیشتر: فقط قوی‌ترین لبه‌ها شناسایی می‌شوند
        • مقدار کمتر: لبه‌های ضعیف‌تر هم شناسایی می‌شوند
        • فرمول آستانه: mean(gradient) + k_std * std(gradient)
        • محدوده پیشنهادی: 1.5 تا 3.5
    pow_sharp : float, default=1.0
        توان برای تنظیم سختی ماسک لبه‌ها
        • مقدار کمتر از 1: ماسک نرم‌تر، انتقال ملایم‌تر
        • مقدار بیشتر از 1: ماسک سخت‌تر، انتقال ناگهانی‌تر
        • محدوده پیشنهادی: 0.5 تا 2.0
    w_blur_mm : float, default=0.8
        پهنای ناحیه اطراف لبه که محو می‌شود (میلی‌متر)
        • مقدار بیشتر: ناحیه بزرگتری اطراف لبه محو می‌شود
        • مقدار کمتر: فقط لبه اصلی محو می‌شود
        • محدوده پیشنهادی: 0.5 تا 1.5 میلی‌متر
    sigma_z : float or None, default=None
        سیگمای هموارسازی در جهت Z برای تصاویر 3D
        • اگر None باشد، مقدار blur_sigma_mm استفاده می‌شود
        • برای برش‌های ضخیم (>2mm) مقدار کوچکتر پیشنهاد می‌شود

    Returns
    -------
    sitk.Image
        تصویر با لبه‌های نرم شده

    Algorithm
    ---------
    1. محاسبه گرادیان تصویر با گاوسی (تشخیص لبه‌ها)
    2. آستانه‌گذاری روی گرادیان برای شناسایی لبه‌های قوی
    3. گشایش (dilation) ماسک برای گسترش ناحیه اطراف لبه
    4. ایجاد ماسک نرم با feathering برای انتقال ملایم
    5. ترکیب تصویر اصلی و تصویر محو شده با استفاده از ماسک

    Notes
    -----
    - این فیلتر برای کاهش آثار پلکانی (staircase artifacts) در تصاویر مفید است
    - در مقایسه با هموارسازی کل تصویر، جزئیات مهم حفظ می‌شوند
    """
    # ذخیره نوع داده اصلی
    orig_type = img.GetPixelID()
    spacing = img.GetSpacing()
    dim = img.GetDimension()

    # 1) تبدیل به float32 برای محاسبات
    imgf = sitk.Cast(img, sitk.sitkFloat32)

    # 2) محاسبه قدرت لبه‌ها با گرادیان گاوسی
    g = sitk.GradientMagnitudeRecursiveGaussian(imgf, sigma=edge_sigma_mm)
    stats = sitk.StatisticsImageFilter()
    stats.Execute(g)
    thr = float(stats.GetMean() + k_std * stats.GetSigma())

    # 3) ایجاد ماسک باینری لبه‌های قوی و گسترش آن
    edge_bin = sitk.BinaryThreshold(g, lowerThreshold=thr, upperThreshold=1e9, insideValue=1, outsideValue=0)
    radius = _radius_from_mm(w_blur_mm, spacing, dim)
    edge_dil = sitk.BinaryDilate(edge_bin, radius)

    # 4) ایجاد ماسک نرم برای انتقال ملایم
    mask = sitk.SmoothingRecursiveGaussian(
        sitk.Cast(edge_dil, sitk.sitkFloat32),
        sigma=max(0.1, w_blur_mm * 0.35)
    )
    mask = sitk.RescaleIntensity(mask, 0.0, 1.0)  # تضمین محدوده [0,1]

    # تنظیم سختی ماسک
    if pow_sharp != 1.0:
        mask = sitk.Pow(mask, pow_sharp)
        mask = sitk.RescaleIntensity(mask, 0.0, 1.0)

    # 5) ایجاد نسخه محو شده برای ترکیب
    blur = _smooth_xy_recursive(imgf, sigma_xy=blur_sigma_mm, sigma_z=sigma_z)

    # 6) ترکیب هوشمند: فقط نواحی ماسک شده محو می‌شوند
    out = sitk.Add(
        sitk.Multiply(imgf, sitk.Subtract(1.0, mask)),
        sitk.Multiply(blur, mask)
    )

    return sitk.Cast(out, orig_type)


def apply_unsharp_mask(img: sitk.Image, amount: float = 0.5, radius: float = 1.0) -> sitk.Image:
    """
    اعمال Unsharp Masking برای افزایش تیزی تصویر.

    این تکنیک کلاسیک با تفریق یک نسخه محو شده از تصویر اصلی،
    جزئیات فرکانس بالا را استخراج و تقویت می‌کند.

    Parameters
    ----------
    img : sitk.Image
        تصویر ورودی SimpleITK
    amount : float, default=0.5
        شدت اعمال تیزی (ضریب تقویت جزئیات)
        • 0.0: هیچ تغییری اعمال نمی‌شود
        • 0.3-0.7: مقدار متعادل برای بیشتر تصاویر
        • 1.0-2.0: تیزی قوی، ممکن است نویز را نیز تقویت کند
        • محدوده ایمن: 0.1 تا 1.5
    radius : float, default=1.0
        شعاع محو کردن برای ایجاد ماسک (میلی‌متر)
        • مقدار بیشتر: جزئیات درشت‌تر تقویت می‌شوند
        • مقدار کمتر: جزئیات ظریف‌تر تقویت می‌شوند
        • محدوده پیشنهادی: 0.3 تا 2.0 میلی‌متر

    Returns
    -------
    sitk.Image
        تصویر تیز شده

    Formula
    -------
    sharpened = original + amount * (original - blurred)

    Notes
    -----
    - برای تصاویر با نویز زیاد، amount کمتری استفاده شود
    - در تصاویر CT، radius=0.8 و amount=0.4 معمولاً خوب کار می‌کند
    - در تصاویر MR، radius=1.2 و amount=0.3 بهتر است
    """
    # ذخیره نوع داده اصلی
    orig_type = img.GetPixelID()

    # تبدیل به float برای محاسبات
    imgf = sitk.Cast(img, sitk.sitkFloat32)

    # ایجاد نسخه محو شده - radius is already in mm, so we can use it directly
    blurred = sitk.SmoothingRecursiveGaussian(imgf, sigma=radius)

    # استخراج جزئیات فرکانس بالا
    details = sitk.Subtract(imgf, blurred)

    # اضافه کردن جزئیات تقویت شده به تصویر اصلی
    sharpened = sitk.Add(imgf, sitk.Multiply(details, amount))

    return sitk.Cast(sharpened, orig_type)


def smoothing(itk_image: sitk.Image) -> sitk.Image:
    """
    فیلتر هموارسازی ترکیبی برای کاهش نویز و بهبود ظاهر لبه‌ها.
    
    این تابع یک پالایش دو مرحله‌ای انجام می‌دهد:
    ۱. هموارسازی گاوسی برای کاهش نویز
    ۲. Unsharp Masking ملایم برای حفظ جزئیات
    
    Parameters
    ----------
    itk_image : sitk.Image
        تصویر ورودی SimpleITK
        
    Returns
    -------
    sitk.Image
        تصویر هموار شده با حفظ جزئیات
        
    Notes
    -----
    - فقط برای تصاویر سه‌بعدی با حداقل ۴ اسلایس اعمال می‌شود
    - پارامترها برای تعادل بهینه بین نویزگیری و حفظ جزئیات تنظیم شده‌اند
    - برای تصاویر دو بعدی یا با اسلایس کم، تصویر بدون تغییر بازگردانده می‌شود
    """
    # بررسی ابعاد تصویر
    nx, ny, nz = itk_image.GetSize()
    if nz < 4:
        return itk_image
    
    # مرحله ۱: هموارسازی گاوسی برای کاهش نویز
    # سیگمای 0.4 میلی‌متر: تعادل خوب بین نویزگیری و حفظ جزئیات
    itk_image = sitk.SmoothingRecursiveGaussian(itk_image, sigma=0.4)
    
    # مرحله ۲: Unsharp Masking ملایم برای بازگرداندن جزئیات
    # amount=0.25: تقویت ملایم جزئیات بدون ایجاد نویز
    # radius=1.0mm: تمرکز روی جزئیات متوسط
    itk_image = apply_unsharp_mask(itk_image, amount=0.25, radius=1.0)
    
    return itk_image


def apply_gaussian_sharpening(img: sitk.Image, sigma: float = 0.8, alpha: float = 0.5) -> sitk.Image:
    """
    تیز کردن تصویر با استفاده از تفاضل گاوسی‌ها (Difference of Gaussians - DoG).

    این روش با تفریق دو فیلتر گاوسی با مقیاس‌های مختلف،
    محدوده خاصی از فرکانس‌ها را تقویت می‌کند.

    Parameters
    ----------
    img : sitk.Image
        تصویر ورودی SimpleITK
    sigma : float, default=0.8
        سیگمای گاوسی کوچک (جزئیات) بر حسب میلی‌متر
        • مقدار بیشتر: جزئیات درشت‌تر تقویت می‌شوند
        • مقدار کمتر: جزئیات ظریف‌تر تقویت می‌شوند
        • محدوده پیشنهادی: 0.3 تا 1.5 میلی‌متر
    alpha : float, default=0.5
        شدت تیز کردن (ضریب تقویت جزئیات استخراج شده)
        • 0.0: هیچ اثری ندارد
        • 0.3-0.6: مقدار متعادل
        • 0.7-1.0: تقویت قوی، ممکن است نویز ایجاد کند
        • محدوده ایمن: 0.1 تا 0.8

    Returns
    -------
    sitk.Image
        تصویر تیز شده

    Formula
    -------
    DoG = G_small - G_large
    sharpened = original + alpha * DoG

    Where:
        G_small = Gaussian(sigma)
        G_large = Gaussian(sigma * 2.0)

    Notes
    -----
    - DoG یک تقریب خوب از فیلتر لاپلاسین-گاوسی است
    - برای تقویت جزئیات در مقیاس خاص مفید است
    - نسبت سیگماهای کوچک و بزرگ معمولاً 1:2 است
    """
    # ذخیره نوع داده اصلی
    orig_type = img.GetPixelID()
    imgf = sitk.Cast(img, sitk.sitkFloat32)

    # گاوسی با سیگمای کوچک (حفظ جزئیات) - sigma is already in mm, so we can use it directly
    gauss_small = sitk.SmoothingRecursiveGaussian(imgf, sigma=sigma)

    # گاوسی با سیگمای بزرگ (هموارسازی بیشتر) - sigma is already in mm, so we can use it directly
    gauss_large = sitk.SmoothingRecursiveGaussian(imgf, sigma=sigma * 2.0)

    # تفاضل دو گاوسی (استخراج جزئیات فرکانس متوسط)
    details = sitk.Subtract(gauss_small, gauss_large)

    # اضافه کردن جزئیات تقویت شده به تصویر اصلی
    sharpened = sitk.Add(imgf, sitk.Multiply(details, alpha))

    return sitk.Cast(sharpened, orig_type)


def apply_laplacian_sharpening(img: sitk.Image, alpha: float = 0.3, _pre_cast: bool = False) -> sitk.Image:
    """
    تیز کردن تصویر با استفاده از لاپلاسین-گاوسی.

    لاپلاسین مشتق دوم تصویر را محاسبه می‌کند و برای آشکارسازی
    سریع تغییرات شدت (لبه‌ها) مناسب است.

    Parameters
    ----------
    img : sitk.Image
        تصویر ورودی SimpleITK
    alpha : float, default=0.3
        شدت تیز کردن (ضریب لاپلاسین منفی)
        • 0.0: هیچ اثری ندارد
        • 0.1-0.3: تقویت ملایم لبه‌ها
        • 0.4-0.6: تقویت قوی، ممکن است overshoot ایجاد کند
        • محدوده ایمن: 0.05 تا 0.5

    Returns
    -------
    sitk.Image
        تصویر تیز شده

    Formula
    -------
    sharpened = original - alpha * Laplacian(original)

    Notes
    -----
    - لاپلاسین به نویز حساس است، بنابراین بهتر است روی تصویر نسبتاً هموار اعمال شود
    - سیگمای لاپلاسین-گاوسی روی 0.5 میلی‌متر ثابت است (تعادل بهینه)
    - منفی کردن لاپلاسین ضروری است زیرا لاپلاسین در مرکز منفی و در اطراف مثبت است
    - برای تیز کردن لبه‌های تیز بسیار موثر است
    """
    # v2.2.3.1.0: cast-once — skip redundant Cast when called from apply_filters chain
    if not _pre_cast:
        orig_type = img.GetPixelID()
        img = sitk.Cast(img, sitk.sitkFloat32)

    # v2.2.3.0.8: Gaussian kernel in ITK; arithmetic in numpy.
    orig_arr = sitk.GetArrayFromImage(img).astype(np.float32)
    laplacian_arr = sitk.GetArrayFromImage(
        sitk.LaplacianRecursiveGaussian(img, sigma=0.5)
    ).astype(np.float32)
    sharpened_arr = _clip_to_reference_range(
        orig_arr - laplacian_arr * float(alpha),
        orig_arr,
    )

    result = sitk.GetImageFromArray(sharpened_arr)
    result.CopyInformation(img)
    if not _pre_cast:
        return sitk.Cast(result, orig_type)
    return result


def apply_adaptive_sharpening(
    img: sitk.Image,
    base_amount: float = 0.3,
    edge_boost: float = 1.5,
    sigma: float = 0.6,
    _pre_cast: bool = False,
) -> sitk.Image:
    """
    تیز کردن تطبیقی که بر اساس قدرت لبه‌ها، شدت تیز کردن را تنظیم می‌کند.

    این روش هوشمند بر مناطق با گرادیان قوی (لبه‌ها) بیشتر تأکید می‌کند
    و در مناطق هموار تیز کردن کمتری اعمال می‌کند.

    Parameters
    ----------
    img : sitk.Image
        تصویر ورودی SimpleITK
    base_amount : float, default=0.3
        مقدار پایه تیز کردن در کل تصویر
        • حداقل تیز کردن اعمال شده حتی در مناطق هموار
        • محدوده پیشنهادی: 0.1 تا 0.5
    edge_boost : float, default=1.5
        ضریب تقویت اضافی در مناطق لبه‌دار
        • مقدار بیشتر: تقویت قوی‌تر لبه‌ها
        • مقدار کمتر: تیز کردن یکنواخت‌تر
        • محدوده پیشنهادی: 1.0 تا 3.0
    sigma : float, default=0.6
        سیگمای گاوسی برای محاسبه گرادیان (میلی‌متر)
        • مقدار بیشتر: تشخیص لبه‌های درشت‌تر
        • مقدار کمتر: تشخیص لبه‌های ظریف‌تر
        • محدوده پیشنهادی: 0.3 تا 1.2 میلی‌متر

    Returns
    -------
    sitk.Image
        تصویر تیز شده به صورت تطبیقی

    Formula
    -------
    weight_map = base_amount + edge_boost * normalized_gradient
    sharpened = original + weight_map * (original - blurred)

    Notes
    -----
    - برای تصاویری که هم نواحی هموار و هم نواحی با جزئیات زیاد دارند ایده‌آل است
    - از oversharpening نواحی هموار جلوگیری می‌کند
    - edge_boost=2.0 برای CT و edge_boost=1.0 برای MR مناسب است
    """
    # v2.2.3.1.0: cast-once — skip redundant Cast when called from apply_filters chain
    if not _pre_cast:
        orig_type = img.GetPixelID()
        img = sitk.Cast(img, sitk.sitkFloat32)

    # v2.2.3.0.8: Only 2 ITK calls (GradientMagnitude + Smooth); all arithmetic numpy.
    # OLD: 10 ITK pipeline calls  →  NEW: 2 ITK calls + numpy ops (~0ms overhead)
    orig_arr = sitk.GetArrayFromImage(img).astype(np.float32)
    gradient_arr = sitk.GetArrayFromImage(
        sitk.GradientMagnitudeRecursiveGaussian(img, sigma=sigma)
    ).astype(np.float32)
    blurred_arr = sitk.GetArrayFromImage(
        sitk.SmoothingRecursiveGaussian(img, sigma=sigma)
    ).astype(np.float32)

    # Normalize gradient to [0, 1] in numpy
    g_min, g_max = gradient_arr.min(), gradient_arr.max()
    gradient_norm = (gradient_arr - g_min) / (g_max - g_min + 1e-8)

    edge_weight = float(base_amount) + gradient_norm * float(edge_boost)
    details = orig_arr - blurred_arr
    sharpened_arr = _clip_to_reference_range(
        orig_arr + details * edge_weight,
        orig_arr,
    )

    result = sitk.GetImageFromArray(sharpened_arr.astype(np.float32))
    result.CopyInformation(img)
    if not _pre_cast:
        return sitk.Cast(result, orig_type)
    return result


def apply_multiscale_sharpening(
    img: sitk.Image,
    sigmas: list[float] = [0.8, 1.5, 2.5],
    amounts: list[float] = [0.4, 0.2, 0.1],
    _pre_cast: bool = False,
) -> sitk.Image:
    """
    تیز کردن چندمقیاسه برای تقویت همزمان جزئیات در مقیاس‌های مختلف.

    این روش جزئیات را در چندین مقیاس فضایی استخراج و تقویت می‌کند:
    - مقیاس کوچک: جزئیات ظریف و بافت
    - مقیاس متوسط: ساختارهای کوچک
    - مقیاس بزرگ: ساختارهای درشت

    Parameters
    ----------
    img : sitk.Image
        تصویر ورودی SimpleITK
    sigmas : list[float], default=[0.8, 1.5, 2.5]
        لیست سیگماهای گاوسی برای مقیاس‌های مختلف (میلی‌متر)
        • مقادیر کوچک: جزئیات ظریف
        • مقادیر متوسط: ساختارهای کوچک
        • مقادیر بزرگ: ساختارهای درشت
        • معمولاً ۳ تا ۵ مقیاس با نسبت هندسی (مثلاً 1:2:4)
    amounts : list[float], default=[0.4, 0.2, 0.1]
        شدت تیز کردن در هر مقیاس
        • معمولاً مقیاس‌های کوچک مقدار بیشتر (جزئیات مهم)
        • مقیاس‌های بزرگ مقدار کمتر (جلوگیری از ایجاد هاله)
        • مجموع مقادیر نباید از 1.0 خیلی بیشتر شود

    Returns
    -------
    sitk.Image
        تصویر تیز شده با جزئیات چندمقیاسه

    Notes
    -----
    - طول لیست sigmas و amounts باید برابر باشد
    - برای تصاویر MR با بافت پیچیده بسیار موثر است
    - مقدارهای پیشنهادی برای CT: [0.6, 1.2, 2.4] با مقادیر [0.3, 0.15, 0.05]
    - می‌تواند زمان محاسبه بیشتری نسبت به روش‌های تک‌مقیاسه داشته باشد
    """
    # v2.2.3.1.0: cast-once — skip redundant Cast when called from apply_filters chain
    if not _pre_cast:
        orig_type = img.GetPixelID()
        img = sitk.Cast(img, sitk.sitkFloat32)

    # v2.2.3.0.8: Use numpy for arithmetic; ITK only for the Gaussian kernel.
    # sitk.Add/Subtract/Multiply each trigger a full ITK pipeline rebuild
    # (~1-3ms each); replacing them with numpy ops drops that overhead to ~0.
    reference_arr = sitk.GetArrayFromImage(img).astype(np.float32)
    sharpened_arr = reference_arr.copy()

    # اعمال تیز کردن در هر مقیاس - sigmas are already in mm, so we can use them directly
    for sigma, amount in zip(sigmas, amounts):
        # ── GIL yield between multiscale iterations ──
        time.sleep(0.01)
        # Run Gaussian in ITK (RecursiveGaussian is C++ and fastest available)
        tmp = sitk.GetImageFromArray(sharpened_arr)
        tmp.CopyInformation(img)
        blurred_arr = sitk.GetArrayFromImage(
            sitk.SmoothingRecursiveGaussian(tmp, sigma=sigma)
        )
        # numpy arithmetic — near-zero cost
        details_arr = sharpened_arr - blurred_arr
        sharpened_arr = _clip_to_reference_range(
            sharpened_arr + details_arr * float(amount),
            reference_arr,
        )

    result = sitk.GetImageFromArray(sharpened_arr)
    result.CopyInformation(img)
    if not _pre_cast:
        return sitk.Cast(result, orig_type)
    return result


def apply_filters(
    itk_image: sitk.Image,
    metadata: dict,
    filter_settings_path: Path = FILTER_CONFIG_PATH,
    max_itk_threads: "int | None" = None,
) -> sitk.Image:
    """
    Advanced SimpleITK filtering pipeline.

    Reference behavior:
    - MR: noise reduction + multiscale sharpening + laplacian sharpening + adaptive sharpening
    - CT: noise reduction only

    v2.2.3.1.5 fixes (over v2.2.3.1.4)
    ------------------------------------
    - Fixed white line artifacts at tissue/background edges by clamping
      the unsharp mask output to the original data range.  PooyanPacs
      avoids this naturally because it operates on 8-bit [0,255]
      BitmapSource; 16-bit DICOM data needs explicit clamping.
    - Reduced unsharp amount from 0.40 to 0.25 (mild: 0.20) since
      16-bit data has much sharper edge transitions than 8-bit.
    - Reduced inter-stage sleep from 50ms to 5ms (only 2 lightweight
      stages now; 50ms × 9 series = 450ms wasted during warmup).
    - Increased ITK thread count from 2 to min(cpu, 4) since the
      pipeline is much lighter; halves RecursiveGaussian wall time.

    v2.2.3.1.4 redesign
    --------------------
    Replaced the 4-stage 3D pipeline (noise + multiscale_sharpening +
    laplacian_sharpening + adaptive_sharpening = 7+ full 3D Gaussian passes)
    with a lightweight 2-stage XY-only pipeline derived from PooyanPacs:

1. XY-only Gaussian noise reduction (σ=0.275, no Z-pass)
    2. Single XY-only unsharp mask (σ=1.0, amount=0.25, clamped)

    The PooyanPacs unsharp mask formula:
        output = original + amount * (original - GaussianBlur(original))
    with clamping to [min, max] of original data range.
    """
    import logging
    logger = logging.getLogger(__name__)

    def _merge_supported(base: dict, override: dict) -> dict:
        """Merge override into base, but only for keys already present in base."""
        for k, v in (override or {}).items():
            if k not in base:
                continue
            if isinstance(base.get(k), dict) and isinstance(v, dict):
                _merge_supported(base[k], v)
            else:
                base[k] = v
        return base

    # ------------------------------------------------------------------
    # Default filter configuration (reference SimpleITK path)
    # ------------------------------------------------------------------
    DEFAULT_FILTERS = {
        "MR": {
            "enabled": True,
            "min_slices": 4,
            "noise_reduction": {
                "enabled": True,
                "sigma": 0.275,
                "mild_sigma": 0.33,
            },
            "lowres_anti_alias": {
                "enabled": True,
                "matrix_threshold": 384,
                "sigma": 0.30,
                "blend": 0.15,
                "mild_sigma": 0.35,
                "mild_blend": 0.18,
            },
            "multiscale_sharpening": {
                "enabled": True,
                "sigmas": [0.5, 1.0, 2.0],
                "amounts": [0.25, 0.12, 0.06],
                "mild_sigmas": [0.5, 1.0, 2.0, 4.0],
                "mild_amounts": [0.20, 0.10, 0.05, 0.025],
            },
            "laplacian_sharpening": {
                "enabled": True,
                "alpha": 0.12,
                "mild_alpha": 0.10,
            },
            "adaptive_sharpening": {
                "enabled": True,
                "base_amount": 0.12,
                "edge_boost": 0.90,
                "sigma": 0.70,
                "mild_base_amount": 0.10,
                "mild_edge_boost": 0.80,
                "mild_sigma": 0.80,
            },
        },
        "CT": {
            "enabled": True,
            "min_slices": 4,
            "noise_reduction": {
                "enabled": True,
                "sigma": 0.275,
                "mild_sigma": 0.33,
            },
            "lowres_anti_alias": {
                "enabled": True,
                "matrix_threshold": 384,
                "sigma": 0.26,
                "blend": 0.12,
                "mild_sigma": 0.30,
                "mild_blend": 0.14,
            },
        },
    }

    # ------------------------------------------------------------------
    # Timing start
    # ------------------------------------------------------------------
    t0 = time.time()

    series_meta = metadata.get("series", {}) if isinstance(metadata, dict) else {}
    modality = str(series_meta.get("modality", "") or "").upper()
    series_name = str(series_meta.get("series_name", "Unknown") or "Unknown")

    # logger.info(
    #     f"Applying filters to series: {series_name} | modality: {modality} | spacing: {itk_image.GetSpacing()}"
    # )

    # ------------------------------------------------------------------
    # Load external filter overrides (optional)
    # ------------------------------------------------------------------
    filter_settings = {}
    try:
        if filter_settings_path.exists():
            with open(filter_settings_path, "r", encoding="utf-8") as f:
                filter_settings = json.load(f)
            #logger.info(f"Loaded filter settings from {filter_settings_path}")
        else:
            logger.warning(f"Filter settings file does not exist: {filter_settings_path}")
    except Exception as e:
        logger.error(f"Failed to load filter settings: {e}")
        import traceback
        logger.error(traceback.format_exc())

    modality_settings = DEFAULT_FILTERS.get(modality)
    if modality_settings is None:
        if modality:
            logger.info("No SimpleITK filters configured for modality '%s'", modality)
        return itk_image

    # merge external overrides (supported keys only)
    if modality in filter_settings and isinstance(filter_settings[modality], dict):
        modality_settings = _merge_supported(modality_settings, filter_settings[modality])

    # بررسی می‌کنیم آیا فیلترها برای این مودالیته فعال هستند
    if not modality_settings.get("enabled", True):
        #logger.info(f"Filters disabled for {modality} - returning original image")
        return itk_image

    # ------------------------------------------------------------------
    # Sanity checks (برای MR و CT اعمال می‌شود)
    # ------------------------------------------------------------------
    nx, ny, nz = itk_image.GetSize()
    min_slices = modality_settings.get("min_slices", 4)

    if nz < min_slices:
        logger.warning(f"Not enough slices ({nz} < {min_slices}), skipping filters")
        return itk_image

    #logger.info(f"Starting filter pipeline for {modality} ({nx}×{ny}×{nz})")

    # Determine mild mode based on spacing (stable logic: meaningful for MR)
    spacing = itk_image.GetSpacing()
    max_spacing = max(spacing) if spacing else 0
    mild_mode = (modality == "MR") and (max_spacing > 1.5)

    # v2.2.3.2.0: Adaptive ITK thread count — reserve 2 cores for VTK render.
    # • 4-core: 2 threads  (smoother scroll during load, ITK takes a bit longer)
    # • 6-core: 4 threads  (same as previous cap)
    # • 8-core: 6 threads  (faster ITK AND still leaves 2 cores for VTK)
    # DL_WARMUP background loads still override via max_itk_threads=2.
    _itk_cpu_count = os.cpu_count() or 4
    _filter_threads = max(min(_itk_cpu_count - 2, 8), 2)
    if max_itk_threads is not None:
        _filter_threads = min(_filter_threads, max(1, int(max_itk_threads)))
    try:
        sitk.ProcessObject.SetGlobalDefaultNumberOfThreads(_filter_threads)
    except Exception:
        pass

    # v2.2.3.2.0: Lower this worker thread's OS scheduling priority during the
    # heavy ITK Gaussian pass so VTK render (main thread, NORMAL priority)
    # always wins CPU time → eliminates 100-300ms scroll spikes during load.
    import sys as _sys
    _lowered_priority = False
    if _sys.platform == 'win32':
        try:
            import ctypes as _ct
            _ct.windll.kernel32.SetThreadPriority(
                _ct.windll.kernel32.GetCurrentThread(), -1  # THREAD_PRIORITY_BELOW_NORMAL
            )
            _lowered_priority = True
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Phase 1 (v2.2.3.1.6): Cast-once to float32 before all filter stages.
    # Previously the cast was buried inside "if modality == 'MR'" so:
    #   - CT never benefited; noise reduction ran on int16 (ITK internally
    #     promoted to float32 for each Gaussian pass, then cast back).
    #   - MR's two-stage pipeline did: int16 noise-red → Cast(float32) →
    #     unsharp mask blur (float32) → Cast(int16).
    # Casting once here avoids ALL intermediate int16↔float32 round-trips.
    # Measured saving: ~50–150ms per MR series on test hardware.
    # Cast-back to original pixel type happens once at the very end.
    # ------------------------------------------------------------------
    _orig_pixel_type = itk_image.GetPixelID()
    _orig_min = None
    _orig_max = None
    try:
        _mm = sitk.MinimumMaximumImageFilter()
        _mm.Execute(itk_image)
        _orig_min = float(_mm.GetMinimum())
        _orig_max = float(_mm.GetMaximum())
    except Exception:
        pass
    if _orig_pixel_type != sitk.sitkFloat32:
        itk_image = sitk.Cast(itk_image, sitk.sitkFloat32)

    # ------------------------------------------------------------------
    # Noise reduction
    # ------------------------------------------------------------------
    noise_cfg = modality_settings.get("noise_reduction", {})
    if noise_cfg.get("enabled", True):
        sigma = noise_cfg.get("mild_sigma", noise_cfg.get("sigma", 0.25)) if mild_mode else noise_cfg.get("sigma", 0.25)
        ct_high_slice_threshold = int(noise_cfg.get("ct_high_slice_threshold", 320))
        if modality == "CT" and int(nz) >= ct_high_slice_threshold:
            itk_image = _smooth_xy_recursive(itk_image, sigma_xy=float(sigma), sigma_z=0.0)
        else:
            itk_image = sitk.SmoothingRecursiveGaussian(itk_image, sigma=float(sigma))

    # ------------------------------------------------------------------
    # Low-resolution anti-alias (conservative, matrix-gated)
    # ------------------------------------------------------------------
    lowres_cfg = modality_settings.get("lowres_anti_alias", {})
    lowres_enabled = bool(lowres_cfg.get("enabled", True))
    lowres_threshold = int(lowres_cfg.get("matrix_threshold", 384))
    lowres_gate = int(min(nx, ny)) <= lowres_threshold
    if lowres_enabled and lowres_gate:
        aa_sigma = (
            float(lowres_cfg.get("mild_sigma", lowres_cfg.get("sigma", 0.30)))
            if mild_mode
            else float(lowres_cfg.get("sigma", 0.30))
        )
        aa_blend = (
            float(lowres_cfg.get("mild_blend", lowres_cfg.get("blend", 0.15)))
            if mild_mode
            else float(lowres_cfg.get("blend", 0.15))
        )
        aa_blend = max(0.0, min(aa_blend, 0.45))
        if aa_sigma > 0.0 and aa_blend > 0.0:
            aa_smoothed = _smooth_xy_recursive(itk_image, sigma_xy=aa_sigma, sigma_z=0.0)
            itk_image = sitk.Add(
                sitk.Multiply(itk_image, 1.0 - aa_blend),
                sitk.Multiply(aa_smoothed, aa_blend),
            )

    # ── GIL yield: brief pause between stages ──
    # v2.2.3.2.3: 2ms is enough for the main thread to process one VTK render
    # cycle (~18ms budget).  Longer sleeps slow down background loads without
    # proportional scroll benefit.
    time.sleep(0.002)

    # ------------------------------------------------------------------
    # Multiscale sharpening
    # ------------------------------------------------------------------
    if modality == "MR":
        ms_cfg = modality_settings.get("multiscale_sharpening", {})
        if ms_cfg.get("enabled", True):
            sigmas = ms_cfg.get("mild_sigmas", ms_cfg.get("sigmas", [0.5, 1.0, 2.0])) if mild_mode else ms_cfg.get("sigmas", [0.5, 1.0, 2.0])
            amounts = ms_cfg.get("mild_amounts", ms_cfg.get("amounts", [0.25, 0.12, 0.06])) if mild_mode else ms_cfg.get("amounts", [0.25, 0.12, 0.06])
            itk_image = apply_multiscale_sharpening(itk_image, sigmas=sigmas, amounts=amounts)

        time.sleep(0.002)

        lap_cfg = modality_settings.get("laplacian_sharpening", {})
        if lap_cfg.get("enabled", True):
            alpha = lap_cfg.get("mild_alpha", lap_cfg.get("alpha", 0.12)) if mild_mode else lap_cfg.get("alpha", 0.12)
            itk_image = apply_laplacian_sharpening(itk_image, alpha=float(alpha))

        time.sleep(0.002)

        ad_cfg = modality_settings.get("adaptive_sharpening", {})
        if ad_cfg.get("enabled", True):
            base_amount = ad_cfg.get("mild_base_amount", ad_cfg.get("base_amount", 0.12)) if mild_mode else ad_cfg.get("base_amount", 0.12)
            edge_boost = ad_cfg.get("mild_edge_boost", ad_cfg.get("edge_boost", 0.90)) if mild_mode else ad_cfg.get("edge_boost", 0.90)
            sigma_val = ad_cfg.get("mild_sigma", ad_cfg.get("sigma", 0.70)) if mild_mode else ad_cfg.get("sigma", 0.70)
            itk_image = apply_adaptive_sharpening(
                itk_image,
                base_amount=float(base_amount),
                edge_boost=float(edge_boost),
                sigma=float(sigma_val),
            )

    # ------------------------------------------------------------------
    # Cast back to original pixel type once — covers BOTH CT and MR paths.
    # (Previously only inside "if modality == 'MR'" — CT returned float32.)
    # ------------------------------------------------------------------
    if _orig_pixel_type != sitk.sitkFloat32:
        if (
            _orig_min is not None
            and _orig_max is not None
            and float(_orig_max) >= float(_orig_min)
        ):
            itk_image = sitk.Clamp(
                itk_image,
                sitk.sitkFloat32,
                lowerBound=float(_orig_min),
                upperBound=float(_orig_max),
            )
        itk_image = sitk.Cast(itk_image, _orig_pixel_type)

    # Timing end
    _dt = time.time() - t0
    logger.info(
        "viewer-data stage=apply_filters mod=%s slices=%d threads=%d duration_ms=%.0f",
        modality, nz, _filter_threads, _dt * 1000.0,
        extra={"component": "viewer", "function": "image_filters.apply_filters", "stage": "apply_filters"},
    )

    # Restore ITK thread count so any subsequent interactive loads get full CPU.
    try:
        sitk.ProcessObject.SetGlobalDefaultNumberOfThreads(_itk_cpu_count)
    except Exception:
        pass

    # Restore normal thread priority so subsequent work (DB writes, etc.) are not penalised.
    if _lowered_priority:
        try:
            _ct.windll.kernel32.SetThreadPriority(
                _ct.windll.kernel32.GetCurrentThread(), 0  # THREAD_PRIORITY_NORMAL
            )
        except Exception:
            pass

    return itk_image

def enhance_resolution(itk_image: sitk.Image, scale_factor: float = 1.5) -> sitk.Image:
    """
    افزایش رزولوشن تصویر با روش resampling.
    
    Parameters
    ----------
    itk_image : sitk.Image
        تصویر ورودی
    scale_factor : float, default=1.5
        ضریب بزرگنمایی
        • 1.0: بدون تغییر
        • 1.5: 50% بزرگتر
        • 2.0: دو برابر
        • محدوده پیشنهادی: 1.2 تا 2.0
        
    Returns
    -------
    sitk.Image
        تصویر با رزولوشن افزایش یافته
    """
    original_size = itk_image.GetSize()
    original_spacing = itk_image.GetSpacing()
    
    # محاسبه اندازه و spacing جدید
    new_size = [int(original_size[i] * scale_factor) for i in range(itk_image.GetDimension())]
    new_spacing = [original_spacing[i] / scale_factor for i in range(itk_image.GetDimension())]
    
    # تنظیمات resampler
    resampler = sitk.ResampleImageFilter()
    resampler.SetSize(new_size)
    resampler.SetOutputSpacing(new_spacing)
    resampler.SetOutputOrigin(itk_image.GetOrigin())
    resampler.SetOutputDirection(itk_image.GetDirection())
    resampler.SetInterpolator(sitk.sitkBSpline)  # BSpline برای بهترین کیفیت
    resampler.SetDefaultPixelValue(itk_image.GetPixelIDValue())
    
    return resampler.Execute(itk_image)


def enhance_local_contrast(itk_image: sitk.Image, radius_mm: float = 10.0) -> sitk.Image:
    """
    بهبود کنتراست محلی برای آشکارسازی جزئیات.

    Parameters
    ----------
    itk_image : sitk.Image
        تصویر ورودی
    radius_mm : float, default=10.0
        شعاع همسایگی برای محاسبه آماره‌های محلی (میلی‌متر)
        • کوچک: بهبود کنتراست محلی دقیق
        • بزرگ: بهبود کنتراست ناحیه‌ای
        • محدوده پیشنهادی: 5.0 تا 20.0 میلی‌متر

    Returns
    -------
    sitk.Image
        تصویر با کنتراست محلی بهبود یافته
    """
    imgf = sitk.Cast(itk_image, sitk.sitkFloat32)

    # تبدیل شعاع به پیکسل
    spacing = itk_image.GetSpacing()
    radius_pixels = [int(radius_mm / s) for s in spacing]

    # محاسبه میانگین محلی
    local_mean = sitk.Mean(imgf, radius_pixels)

    # محاسبه انحراف معیار محلی
    squared = sitk.Multiply(imgf, imgf)
    local_mean_sq = sitk.Mean(squared, radius_pixels)
    local_std = sitk.Sqrt(sitk.Subtract(local_mean_sq, sitk.Multiply(local_mean, local_mean)))

    # بهبود کنتراست: (I - mean) / (std + epsilon)
    epsilon = 0.001  # جلوگیری از تقسیم بر صفر
    enhanced = sitk.Divide(sitk.Subtract(imgf, local_mean), sitk.Add(local_std, epsilon))

    # نرمالایز کردن به محدوده اصلی
    stats = sitk.StatisticsImageFilter()
    stats.Execute(imgf)
    enhanced = sitk.RescaleIntensity(enhanced, stats.GetMinimum(), stats.GetMaximum())

    return sitk.Cast(enhanced, itk_image.GetPixelID())


def apply_filters_to_multiple_series(series_list, metadata_list, filter_type, filter_params):
    """
    Apply filters to multiple series based on filter type and parameters.

    Parameters
    ----------
    series_list : list
        List of SimpleITK images
    metadata_list : list
        List of metadata corresponding to each series
    filter_type : str
        Type of filter to apply
    filter_params : dict
        Parameters for the filter

    Returns
    -------
    list
        List of filtered SimpleITK images
    """
    filtered_series = []

    for i, (series, metadata) in enumerate(zip(series_list, metadata_list)):
        try:
            # Apply the appropriate filter based on type
            if filter_type == "smoothing":
                filtered = smoothing(series)
            elif filter_type == "unsharp_mask":
                amount = filter_params.get("amount", 0.5)
                radius = filter_params.get("radius", 1.0)
                filtered = apply_unsharp_mask(series, amount=amount, radius=radius)
            elif filter_type == "adaptive_sharpening":
                base_amount = filter_params.get("base_amount", 0.12)
                edge_boost = filter_params.get("edge_boost", 0.90)
                sigma = filter_params.get("sigma", 0.70)
                filtered = apply_adaptive_sharpening(
                    series,
                    base_amount=base_amount,
                    edge_boost=edge_boost,
                    sigma=sigma
                )
            elif filter_type == "gaussian_sharpening":
                sigma = filter_params.get("sigma", 0.8)
                alpha = filter_params.get("alpha", 0.5)
                filtered = apply_gaussian_sharpening(series, sigma=sigma, alpha=alpha)
            elif filter_type == "laplacian_sharpening":
                alpha = filter_params.get("alpha", 0.3)
                filtered = apply_laplacian_sharpening(series, alpha=alpha)
            elif filter_type == "multiscale_sharpening":
                sigmas = filter_params.get("sigmas", [0.5, 1.0, 2.0])
                amounts = filter_params.get("amounts", [0.25, 0.12, 0.06])
                filtered = apply_multiscale_sharpening(series, sigmas=sigmas, amounts=amounts)
            elif filter_type == "edge_smooth_ultrafast":
                blur_sigma_mm = filter_params.get("blur_sigma_mm", 1.0)
                edge_sigma_mm = filter_params.get("edge_sigma_mm", 0.4)
                filtered = edge_smooth_ultrafast(
                    series,
                    blur_sigma_mm=blur_sigma_mm,
                    edge_sigma_mm=edge_sigma_mm
                )
            elif filter_type == "enhance_local_contrast":
                radius_mm = filter_params.get("radius_mm", 10.0)
                filtered = enhance_local_contrast(series, radius_mm=radius_mm)
            elif filter_type == "enhance_resolution":
                scale_factor = filter_params.get("scale_factor", 1.5)
                filtered = enhance_resolution(series, scale_factor=scale_factor)
            else:
                # Default to no filtering if filter type is unknown
                filtered = series

            filtered_series.append(filtered)

        except Exception as e:
            print(f"Error applying {filter_type} filter to series {i}: {e}")
            # If filtering fails, append the original series
            filtered_series.append(series)

    return filtered_series


def save_filter_settings_to_json(settings: Dict):
    """Save filter settings to JSON file"""
    import logging
    logger = logging.getLogger(__name__)

    try:
        # Ensure directory exists
        FILTER_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)

        # Save to file
        with open(FILTER_CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(settings, f, indent=4)

        #logger.info(f"Filter settings saved to {FILTER_CONFIG_PATH}")
    except Exception as e:
        logger.error(f"Error saving filter settings: {e}")
        import traceback
        logger.error(traceback.format_exc())


def load_filter_settings_from_json() -> Dict:
    """Load filter settings from JSON file"""
    import logging
    logger = logging.getLogger(__name__)

    try:
        if FILTER_CONFIG_PATH.exists():
            with open(FILTER_CONFIG_PATH, "r", encoding="utf-8") as f:
                settings = json.load(f)
            #logger.info(f"Filter settings loaded from {FILTER_CONFIG_PATH}")
            return settings
        else:
            logger.warning(f"Filter settings file not found at {FILTER_CONFIG_PATH}, using defaults")
            # Return default filter settings
            return {
                "CT": {
                    "enabled": True,
                    "min_slices": 4,
                    "noise_reduction": {
                        "enabled": True,
                        "sigma": 0.25,
                        "mild_sigma": 0.30
                    },
                    "gaussian_smoothing": {
                        "enabled": True,
                        "sigma": 0.5,
                        "mild_sigma": 0.3
                    },
                    "multiscale_sharpening": {
                        "enabled": True,
                        "sigmas": [0.5, 1.0, 2.0],
                        "amounts": [0.25, 0.12, 0.06],
                        "mild_sigmas": [0.5, 1.0, 2.0, 4.0],
                        "mild_amounts": [0.20, 0.10, 0.05, 0.025]
                    },
                    "laplacian_sharpening": {
                        "enabled": True,
                        "alpha": 0.12,
                        "mild_alpha": 0.10
                    },
                    "adaptive_sharpening": {
                        "enabled": True,
                        "base_amount": 0.12,
                        "edge_boost": 0.90,
                        "sigma": 0.70,
                        "mild_base_amount": 0.10,
                        "mild_edge_boost": 0.80,
                        "mild_sigma": 0.80
                    },
                    "gaussian_high_pass": {
                        "enabled": True,
                        "sigma": 1.0,
                        "mild_sigma": 1.5
                    },
                    "gaussian_low_pass": {
                        "enabled": True,
                        "sigma": 2.0,
                        "mild_sigma": 3.0
                    },
                    "gaussian_band_pass": {
                        "enabled": False,
                        "low_sigma": 1.0,
                        "high_sigma": 0.5,
                        "mild_low_sigma": 1.5,
                        "mild_high_sigma": 0.8
                    }
                },
                "MR": {
                    "enabled": True,
                    "min_slices": 4,
                    "noise_reduction": {
                        "enabled": True,
                        "sigma": 0.25,
                        "mild_sigma": 0.30
                    },
                    "gaussian_smoothing": {
                        "enabled": True,
                        "sigma": 0.5,
                        "mild_sigma": 0.3
                    },
                    "multiscale_sharpening": {
                        "enabled": True,
                        "sigmas": [0.5, 1.0, 2.0],
                        "amounts": [0.25, 0.12, 0.06],
                        "mild_sigmas": [0.5, 1.0, 2.0, 4.0],
                        "mild_amounts": [0.20, 0.10, 0.05, 0.025]
                    },
                    "laplacian_sharpening": {
                        "enabled": True,
                        "alpha": 0.12,
                        "mild_alpha": 0.10
                    },
                    "adaptive_sharpening": {
                        "enabled": True,
                        "base_amount": 0.12,
                        "edge_boost": 0.90,
                        "sigma": 0.70,
                        "mild_base_amount": 0.10,
                        "mild_edge_boost": 0.80,
                        "mild_sigma": 0.80
                    },
                    "gaussian_high_pass": {
                        "enabled": True,
                        "sigma": 1.0,
                        "mild_sigma": 1.5
                    },
                    "gaussian_low_pass": {
                        "enabled": True,
                        "sigma": 2.0,
                        "mild_sigma": 3.0
                    },
                    "gaussian_band_pass": {
                        "enabled": False,
                        "low_sigma": 1.0,
                        "high_sigma": 0.5,
                        "mild_low_sigma": 1.5,
                        "mild_high_sigma": 0.8
                    }
                }
            }
    except Exception as e:
        print(f"Error loading filter settings: {e}")
        return {
            "CT": {
                "enabled": True,
                "min_slices": 4,
                "noise_reduction": {
                    "enabled": True,
                    "sigma": 0.25,
                    "mild_sigma": 0.30
                },
                "gaussian_smoothing": {
                    "enabled": True,
                    "sigma": 0.5,
                    "mild_sigma": 0.3
                },
                "multiscale_sharpening": {
                    "enabled": True,
                    "sigmas": [0.5, 1.0, 2.0],
                    "amounts": [0.25, 0.12, 0.06],
                    "mild_sigmas": [0.5, 1.0, 2.0, 4.0],
                    "mild_amounts": [0.20, 0.10, 0.05, 0.025]
                },
                "laplacian_sharpening": {
                    "enabled": True,
                    "alpha": 0.12,
                    "mild_alpha": 0.10
                },
                "adaptive_sharpening": {
                    "enabled": True,
                    "base_amount": 0.12,
                    "edge_boost": 0.90,
                    "sigma": 0.70,
                    "mild_base_amount": 0.10,
                    "mild_edge_boost": 0.80,
                    "mild_sigma": 0.80
                },
                "gaussian_high_pass": {
                    "enabled": True,
                    "sigma": 1.0,
                    "mild_sigma": 1.5
                },
                "gaussian_low_pass": {
                    "enabled": True,
                    "sigma": 2.0,
                    "mild_sigma": 3.0
                },
                "gaussian_band_pass": {
                    "enabled": False,
                    "low_sigma": 1.0,
                    "high_sigma": 0.5,
                    "mild_low_sigma": 1.5,
                    "mild_high_sigma": 0.8
                }
            },
            "MR": {
                "enabled": True,
                "min_slices": 4,
                "noise_reduction": {
                    "enabled": True,
                    "sigma": 0.25,
                    "mild_sigma": 0.30
                },
                "gaussian_smoothing": {
                    "enabled": True,
                    "sigma": 0.5,
                    "mild_sigma": 0.3
                },
                "multiscale_sharpening": {
                    "enabled": True,
                    "sigmas": [0.5, 1.0, 2.0],
                    "amounts": [0.25, 0.12, 0.06],
                    "mild_sigmas": [0.5, 1.0, 2.0, 4.0],
                    "mild_amounts": [0.20, 0.10, 0.05, 0.025]
                },
                "laplacian_sharpening": {
                    "enabled": True,
                    "alpha": 0.12,
                    "mild_alpha": 0.10
                },
                "adaptive_sharpening": {
                    "enabled": True,
                    "base_amount": 0.12,
                    "edge_boost": 0.90,
                    "sigma": 0.70,
                    "mild_base_amount": 0.10,
                    "mild_edge_boost": 0.80,
                    "mild_sigma": 0.80
                },
                "gaussian_high_pass": {
                    "enabled": True,
                    "sigma": 1.0,
                    "mild_sigma": 1.5
                },
                "gaussian_low_pass": {
                    "enabled": True,
                    "sigma": 2.0,
                    "mild_sigma": 3.0
                },
                "gaussian_band_pass": {
                    "enabled": False,
                    "low_sigma": 1.0,
                    "high_sigma": 0.5,
                    "mild_low_sigma": 1.5,
                    "mild_high_sigma": 0.8
                }
            }
        }
# v2.2.3.1.7: Removed apply_filter_with_modality_params() — dead code, no callers found.
#   Its functionality is fully covered by apply_filter_with_settings() above.
