"""
Image Filtering Module for Medical Image Enhancement
====================================================
فیلترها به دو دسته اصلی تقسیم می‌شوند:
۱. فیلترهای هموارسازی (Smoothing) برای کاهش نویز
۲. فیلترهای تیزکننده (Sharpening) برای افزایش وضوح

تمامی پارامترها بر اساس واحد میلی‌متر تنظیم شده‌اند و نسبت به spacing تصویر تطبیق می‌یابند.
"""

import SimpleITK as sitk
import numpy as np
import time
from pathlib import Path
import json

from PacsClient.pacs.workstation_ui.settings_ui.filter_config import FilterConfigWidget
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
        تصویر ورودی SimpleITK
    sigma_xy : float, default=0.8
        مقدار سیگمای فیلتر گاوسی در صفحات XY (میلی‌متر)
        • مقدار بیشتر: هموارسازی بیشتر، جزئیات کمتر
        • مقدار کمتر: هموارسازی کمتر، جزئیات بیشتر
        • محدوده پیشنهادی: 0.3 تا 2.0 میلی‌متر
    sigma_z : float or None, default=None
        مقدار سیگمای فیلتر گاوسی در جهت Z (میلی‌متر)
        • اگر None باشد، برابر sigma_xy در نظر گرفته می‌شود
        • برای تصاویر با برش‌های ضخیم (>2mm) مقدار کمتر پیشنهاد می‌شود
        • اگر 0 باشد یا تصویر 2D باشد، در جهت Z اعمال نمی‌شود
        
    Returns
    -------
    sitk.Image
        تصویر هموار شده با حفظ نوع داده اصلی
        
    Notes
    -----
    - فیلتر بازگشتی برای تصاویر بزرگ سریع‌تر از فیلتر گاوسی استاندارد است
    - مقدار sigma بر اساس میلی‌متر است و به صورت خودکار به پیکسل تبدیل می‌شود
    - برای تصاویر 2D، پارامتر sigma_z نادیده گرفته می‌شود
    """
    # تبدیل به float32 برای دقت محاسباتی
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

    return sitk.Cast(out, img.GetPixelID())


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
    
    # ایجاد نسخه محو شده
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
    
    # گاوسی با سیگمای کوچک (حفظ جزئیات)
    gauss_small = sitk.SmoothingRecursiveGaussian(imgf, sigma=sigma)
    
    # گاوسی با سیگمای بزرگ (هموارسازی بیشتر)
    gauss_large = sitk.SmoothingRecursiveGaussian(imgf, sigma=sigma * 2.0)
    
    # تفاضل دو گاوسی (استخراج جزئیات فرکانس متوسط)
    details = sitk.Subtract(gauss_small, gauss_large)
    
    # اضافه کردن جزئیات تقویت شده به تصویر اصلی
    sharpened = sitk.Add(imgf, sitk.Multiply(details, alpha))
    
    return sitk.Cast(sharpened, orig_type)


def apply_laplacian_sharpening(img: sitk.Image, alpha: float = 0.3) -> sitk.Image:
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
    # ذخیره نوع داده اصلی
    orig_type = img.GetPixelID()
    imgf = sitk.Cast(img, sitk.sitkFloat32)
    
    # محاسبه لاپلاسین-گاوسی با سیگمای 0.5mm
    laplacian = sitk.LaplacianRecursiveGaussian(imgf, sigma=0.5)
    
    # اعمال لاپلاسین منفی برای تیز کردن
    # لاپلاسین منفی در مرکز مثبت است که لبه‌ها را تقویت می‌کند
    sharpened = sitk.Subtract(imgf, sitk.Multiply(laplacian, alpha))
    
    return sitk.Cast(sharpened, orig_type)


def apply_adaptive_sharpening(
    img: sitk.Image, 
    base_amount: float = 0.3, 
    edge_boost: float = 1.5, 
    sigma: float = 0.6
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
    # ذخیره نوع داده اصلی
    orig_type = img.GetPixelID()
    imgf = sitk.Cast(img, sitk.sitkFloat32)
    
    # محاسبه گرادیان برای تشخیص لبه‌ها
    gradient = sitk.GradientMagnitudeRecursiveGaussian(imgf, sigma=sigma)
    
    # نرمالایز کردن گرادیان به محدوده [0, 1]
    gradient_norm = sitk.RescaleIntensity(gradient, 0.0, 1.0)
    
    # ایجاد نقشه وزنی: لبه‌ها وزن بیشتر
    edge_weight = sitk.Add(base_amount, sitk.Multiply(gradient_norm, edge_boost))
    
    # محاسبه جزئیات با Unsharp Masking
    blurred = sitk.SmoothingRecursiveGaussian(imgf, sigma=sigma)
    details = sitk.Subtract(imgf, blurred)
    
    # اعمال تیز کردن با وزن‌های تطبیقی
    sharpened = sitk.Add(imgf, sitk.Multiply(details, edge_weight))
    
    return sitk.Cast(sharpened, orig_type)


def apply_multiscale_sharpening(
    img: sitk.Image, 
    sigmas: list[float] = [0.8, 1.5, 2.5],
    amounts: list[float] = [0.4, 0.2, 0.1]
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
    # ذخیره نوع داده اصلی
    orig_type = img.GetPixelID()
    imgf = sitk.Cast(img, sitk.sitkFloat32)
    
    # شروع با تصویر اصلی
    sharpened = imgf
    
    # اعمال تیز کردن در هر مقیاس
    for sigma, amount in zip(sigmas, amounts):
        # محاسبه جزئیات در این مقیاس
        blurred = sitk.SmoothingRecursiveGaussian(sharpened, sigma=sigma)
        details = sitk.Subtract(sharpened, blurred)
        
        # اضافه کردن جزئیات تقویت شده
        sharpened = sitk.Add(sharpened, sitk.Multiply(details, amount))
    
    return sitk.Cast(sharpened, orig_type)

# def apply_filters(
#     itk_image: sitk.Image,
#     metadata: dict,
#     filter_settings_path: Path = FILTER_CONFIG_PATH
# ) -> sitk.Image:
#     """
#     Unified medical image filtering pipeline.
#     CT and MR are processed identically using MR-grade filters.
#     """

#     # ------------------------------------------------------------------
#     # Default filter configuration (MR is the reference, CT = MR)
#     # ------------------------------------------------------------------
#     DEFAULT_FILTERS = {
#         "MR": {
#             "enabled": True,
#             "min_slices": 4,

#             "noise_reduction": {
#                 "sigma": 0.25,
#                 "mild_sigma": 0.30
#             },

#             "multiscale_sharpening": {
#                 "enabled": True,
#                 "sigmas": [0.5, 1.0, 2.0],
#                 "amounts": [0.25, 0.12, 0.06],
#                 "mild_sigmas": [0.5, 1.0, 2.0, 4.0],
#                 "mild_amounts": [0.20, 0.10, 0.05, 0.025]
#             },

#             "laplacian_sharpening": {
#                 "enabled": True,
#                 "alpha": 0.12,
#                 "mild_alpha": 0.10
#             },

#             "adaptive_sharpening": {
#                 "enabled": True,
#                 "base_amount": 0.12,
#                 "edge_boost": 0.90,
#                 "sigma": 0.70,
#                 "mild_base_amount": 0.10,
#                 "mild_edge_boost": 0.80,
#                 "mild_sigma": 0.80
#             }
#         }
#     }

#     # CT behaves EXACTLY like MR
#     DEFAULT_FILTERS["CT"] = DEFAULT_FILTERS["MR"]

#     # ------------------------------------------------------------------
#     # Timing start
#     # ------------------------------------------------------------------
#     t0 = time.time()

#     modality = metadata["series"]["modality"].upper()
#     series_name = metadata["series"].get("series_name", "Unknown")

#     print(
#         f"series: {series_name} | "
#         f"modality: {modality} | "
#         f"spacing: {itk_image.GetSpacing()}"
#     )

#     # ------------------------------------------------------------------
#     # Load external filter overrides (optional)
#     # ------------------------------------------------------------------
#     filter_settings = {}
#     try:
#         if filter_settings_path.exists():
#             with open(filter_settings_path, "r", encoding="utf-8") as f:
#                 filter_settings = json.load(f)
#     except Exception as e:
#         print(f"   ⚠️ Failed to load filter settings: {e}")

#     modality_settings = DEFAULT_FILTERS.get(modality)
#     if modality_settings is None:
#         print(f"   ℹ️ No filters defined for modality '{modality}'")
#         return itk_image

#     # merge external overrides
#     if modality in filter_settings:
#         for k, v in filter_settings[modality].items():
#             if isinstance(v, dict) and isinstance(modality_settings.get(k), dict):
#                 modality_settings[k].update(v)
#             else:
#                 modality_settings[k] = v

#     if not modality_settings.get("enabled", True):
#         print(f"   ℹ️ Filters disabled for {modality}")
#         return itk_image

#     # ------------------------------------------------------------------
#     # Sanity checks
#     # ------------------------------------------------------------------
#     nx, ny, nz = itk_image.GetSize()
#     min_slices = modality_settings.get("min_slices", 4)

#     if nz < min_slices:
#         print(f"   ⚠️ Not enough slices ({nz} < {min_slices}), skipping filters")
#         return itk_image

#     spacing = itk_image.GetSpacing()
#     max_spacing = max(spacing)
#     mild_mode = max_spacing > 1.5

#     if mild_mode:
#         print(f"   ⚠️ Large spacing detected ({max_spacing:.2f} mm) → mild mode")

#     print(f"   🔧 Applying MR-grade filters to {modality} ({nx}×{ny}×{nz})")

#     # ------------------------------------------------------------------
#     # Noise reduction
#     # ------------------------------------------------------------------
#     noise_cfg = modality_settings["noise_reduction"]
#     sigma = noise_cfg["mild_sigma"] if mild_mode else noise_cfg["sigma"]

#     itk_image = sitk.SmoothingRecursiveGaussian(itk_image, sigma=sigma)
#     print(f"   ├── Noise reduction (sigma={sigma} mm)")

#     # ------------------------------------------------------------------
#     # Multiscale sharpening
#     # ------------------------------------------------------------------
#     ms_cfg = modality_settings["multiscale_sharpening"]
#     if ms_cfg.get("enabled", True):
#         sigmas = ms_cfg["mild_sigmas"] if mild_mode else ms_cfg["sigmas"]
#         amounts = ms_cfg["mild_amounts"] if mild_mode else ms_cfg["amounts"]

#         itk_image = apply_multiscale_sharpening(
#             itk_image,
#             sigmas=sigmas,
#             amounts=amounts
#         )
#         print(f"   ├── Multiscale sharpening ({len(sigmas)} scales)")

#     # ------------------------------------------------------------------
#     # Laplacian sharpening
#     # ------------------------------------------------------------------
#     lap_cfg = modality_settings["laplacian_sharpening"]
#     if lap_cfg.get("enabled", True):
#         alpha = lap_cfg["mild_alpha"] if mild_mode else lap_cfg["alpha"]
#         itk_image = apply_laplacian_sharpening(itk_image, alpha=alpha)
#         print(f"   ├── Laplacian sharpening (alpha={alpha})")

#     # ------------------------------------------------------------------
#     # Adaptive sharpening
#     # ------------------------------------------------------------------
#     ad_cfg = modality_settings["adaptive_sharpening"]
#     if ad_cfg.get("enabled", True):
#         base_amount = ad_cfg["mild_base_amount"] if mild_mode else ad_cfg["base_amount"]
#         edge_boost = ad_cfg["mild_edge_boost"] if mild_mode else ad_cfg["edge_boost"]
#         sigma_val = ad_cfg["mild_sigma"] if mild_mode else ad_cfg["sigma"]

#         itk_image = apply_adaptive_sharpening(
#             itk_image,
#             base_amount=base_amount,
#             edge_boost=edge_boost,
#             sigma=sigma_val
#         )
#         print(
#             f"   └── Adaptive sharpening "
#             f"(base={base_amount}, boost={edge_boost}, sigma={sigma_val})"
#         )

#     # ------------------------------------------------------------------
#     # Timing end
#     # ------------------------------------------------------------------
#     dt = time.time() - t0
#     print(f"   ✅ Filters applied successfully")
#     print(f"   ⏱️ Total filter time: {dt:.3f}s")

#     return itk_image

def get_modality_specific_params(modality: str, filter_type: str) -> dict:
    """
    Get modality-specific parameters for image filters.

    Parameters
    ----------
    modality : str
        Imaging modality (CT, MR, etc.)
    filter_type : str
        Type of filter to configure

    Returns
    -------
    dict
        Dictionary of filter parameters for the given modality and filter type
    """
    # Default parameters
    params = {
        "smoothing": {"sigma": 0.4},
        "unsharp_mask": {"amount": 0.5, "radius": 1.0},
        "gaussian_sharpening": {"sigma": 0.8, "alpha": 0.5},
        "laplacian_sharpening": {"alpha": 0.3},
        "adaptive_sharpening": {"base_amount": 0.3, "edge_boost": 1.5, "sigma": 0.6},
        "edge_smooth_ultrafast": {"blur_sigma_mm": 1.0, "edge_sigma_mm": 0.4}
    }

    # Modality-specific overrides
    modality_params = {
        "CT": {
            "smoothing": {"sigma": 0.3},
            "unsharp_mask": {"amount": 0.4, "radius": 0.8},
            "gaussian_sharpening": {"sigma": 0.6, "alpha": 0.4},
            "laplacian_sharpening": {"alpha": 0.25},
            "adaptive_sharpening": {"base_amount": 0.25, "edge_boost": 1.2, "sigma": 0.5},
            "edge_smooth_ultrafast": {"blur_sigma_mm": 0.8, "edge_sigma_mm": 0.3}
        },
        "MR": {
            "smoothing": {"sigma": 0.5},
            "unsharp_mask": {"amount": 0.6, "radius": 1.2},
            "gaussian_sharpening": {"sigma": 1.0, "alpha": 0.6},
            "laplacian_sharpening": {"alpha": 0.35},
            "adaptive_sharpening": {"base_amount": 0.35, "edge_boost": 1.8, "sigma": 0.7},
            "edge_smooth_ultrafast": {"blur_sigma_mm": 1.2, "edge_sigma_mm": 0.5}
        },
        "CR": {
            "smoothing": {"sigma": 0.2},
            "unsharp_mask": {"amount": 0.3, "radius": 0.6},
            "gaussian_sharpening": {"sigma": 0.5, "alpha": 0.3},
            "laplacian_sharpening": {"alpha": 0.2},
            "adaptive_sharpening": {"base_amount": 0.2, "edge_boost": 1.0, "sigma": 0.4},
            "edge_smooth_ultrafast": {"blur_sigma_mm": 0.6, "edge_sigma_mm": 0.25}
        },
        "DX": {
            "smoothing": {"sigma": 0.15},
            "unsharp_mask": {"amount": 0.25, "radius": 0.5},
            "gaussian_sharpening": {"sigma": 0.4, "alpha": 0.25},
            "laplacian_sharpening": {"alpha": 0.15},
            "adaptive_sharpening": {"base_amount": 0.15, "edge_boost": 0.8, "sigma": 0.3},
            "edge_smooth_ultrafast": {"blur_sigma_mm": 0.5, "edge_sigma_mm": 0.2}
        }
    }

    # Override defaults with modality-specific parameters if available
    if modality in modality_params and filter_type in modality_params[modality]:
        params[filter_type].update(modality_params[modality][filter_type])

    return params[filter_type]


def apply_filters(
    itk_image: sitk.Image,
    metadata: dict,
    filter_settings_path: Path = FILTER_CONFIG_PATH
) -> sitk.Image:
    """
    Unified medical image filtering pipeline.
    MR filters are applied normally, CT images get only noise reduction.
    """

    # ------------------------------------------------------------------
    # Default filter configuration
    # ------------------------------------------------------------------
    DEFAULT_FILTERS = {
        "MR": {
            "enabled": True,
            "min_slices": 4,

            "noise_reduction": {
                "sigma": 0.25,  
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
            }
        },
        
        "CT": {
            "enabled": True, 
            "min_slices": 4,
            "noise_reduction": {
                "sigma": 0.25,
                "mild_sigma": 0.3 
            },
        }
    }

    # ------------------------------------------------------------------
    # Timing start
    # ------------------------------------------------------------------
    t0 = time.time()

    modality = metadata["series"]["modality"].upper()
    series_name = metadata["series"].get("series_name", "Unknown")

    print(
        f"series: {series_name} | "
        f"modality: {modality} | "
        f"spacing: {itk_image.GetSpacing()}"
    )

    # ------------------------------------------------------------------
    # Load external filter overrides (optional)
    # ------------------------------------------------------------------
    filter_settings = {}
    try:
        if filter_settings_path.exists():
            with open(filter_settings_path, "r", encoding="utf-8") as f:
                filter_settings = json.load(f)
    except Exception as e:
        print(f"   ⚠️ Failed to load filter settings: {e}")

    modality_settings = DEFAULT_FILTERS.get(modality)
    if modality_settings is None:
        print(f"   ℹ️ No filters defined for modality '{modality}'")
        return itk_image

    # merge external overrides
    if modality in filter_settings:
        for k, v in filter_settings[modality].items():
            if isinstance(v, dict) and isinstance(modality_settings.get(k), dict):
                modality_settings[k].update(v)
            else:
                modality_settings[k] = v

    # بررسی می‌کنیم آیا فیلترها برای این مودالیته فعال هستند
    if not modality_settings.get("enabled", True):
        print(f"   ℹ️ Filters disabled for {modality} - returning original image")
        return itk_image

    # ------------------------------------------------------------------
    # Sanity checks (برای MR و CT اعمال می‌شود)
    # ------------------------------------------------------------------
    nx, ny, nz = itk_image.GetSize()
    min_slices = modality_settings.get("min_slices", 4)

    if nz < min_slices:
        print(f"   ⚠️ Not enough slices ({nz} < {min_slices}), skipping filters")
        return itk_image

    # ------------------------------------------------------------------
    # Noise reduction (برای هر دو مودالیته MR و CT)
    # ------------------------------------------------------------------
    if "noise_reduction" in modality_settings:
        noise_cfg = modality_settings["noise_reduction"]
        
        # تشخیص حالت mild برای MR
        if modality == "MR":
            spacing = itk_image.GetSpacing()
            max_spacing = max(spacing)
            mild_mode = max_spacing > 1.5
            
            if mild_mode:
                print(f"   ⚠️ Large spacing detected ({max_spacing:.2f} mm) → mild mode")
                sigma = noise_cfg.get("mild_sigma", noise_cfg.get("sigma", 0.4))
            else:
                sigma = noise_cfg.get("sigma", 0.4)
        else:
            # برای CT و دیگر مودالیته‌ها از sigma استاندارد استفاده می‌کنیم
            sigma = noise_cfg.get("sigma", 0.4)
        
        itk_image = sitk.SmoothingRecursiveGaussian(itk_image, sigma=sigma)
        print(f"   ├── Noise reduction (sigma={sigma} mm)")
    else:
        print(f"   ⚠️ No noise reduction configuration for {modality}")

    # ------------------------------------------------------------------
    # سایر فیلترها (فقط برای MR)
    # ------------------------------------------------------------------
    if modality == "MR":
        print(f"   🔧 Applying filters to {modality} ({nx}×{ny}×{nz})")
        
        spacing = itk_image.GetSpacing()
        max_spacing = max(spacing)
        mild_mode = max_spacing > 1.5

        # ------------------------------------------------------------------
        # Multiscale sharpening (فقط برای MR)
        # ------------------------------------------------------------------
        ms_cfg = modality_settings.get("multiscale_sharpening", {})
        if ms_cfg.get("enabled", True):
            sigmas = ms_cfg["mild_sigmas"] if mild_mode else ms_cfg["sigmas"]
            amounts = ms_cfg["mild_amounts"] if mild_mode else ms_cfg["amounts"]

            itk_image = apply_multiscale_sharpening(
                itk_image,
                sigmas=sigmas,
                amounts=amounts
            )
            print(f"   ├── Multiscale sharpening ({len(sigmas)} scales)")

        # ------------------------------------------------------------------
        # Laplacian sharpening (فقط برای MR)
        # ------------------------------------------------------------------
        lap_cfg = modality_settings.get("laplacian_sharpening", {})
        if lap_cfg.get("enabled", True):
            alpha = lap_cfg["mild_alpha"] if mild_mode else lap_cfg["alpha"]
            itk_image = apply_laplacian_sharpening(itk_image, alpha=alpha)
            print(f"   ├── Laplacian sharpening (alpha={alpha})")

        # ------------------------------------------------------------------
        # Adaptive sharpening (فقط برای MR)
        # ------------------------------------------------------------------
        ad_cfg = modality_settings.get("adaptive_sharpening", {})
        if ad_cfg.get("enabled", True):
            base_amount = ad_cfg["mild_base_amount"] if mild_mode else ad_cfg["base_amount"]
            edge_boost = ad_cfg["mild_edge_boost"] if mild_mode else ad_cfg["edge_boost"]
            sigma_val = ad_cfg["mild_sigma"] if mild_mode else ad_cfg["sigma"]

            itk_image = apply_adaptive_sharpening(
                itk_image,
                base_amount=base_amount,
                edge_boost=edge_boost,
                sigma=sigma_val
            )
            print(
                f"   └── Adaptive sharpening "
                f"(base={base_amount}, boost={edge_boost}, sigma={sigma_val})"
            )

        # ------------------------------------------------------------------
        # Timing end برای MR
        # ------------------------------------------------------------------
        dt = time.time() - t0
        print(f"   ✅ All filters applied successfully to MR")
        print(f"   ⏱️ Total filter time: {dt:.3f}s")
    
    elif modality == "CT":
        # فقط noise reduction برای CT اعمال شده است
        dt = time.time() - t0
        print(f"   ✅ Only noise reduction applied to CT (no other filters)")
        print(f"   ⏱️ Total filter time: {dt:.3f}s")
    
    else:
        print(f"   ℹ️ Basic noise reduction applied to {modality} - no additional filters")

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


def apply_filter_with_modality_params(
    itk_image: sitk.Image,
    metadata: dict,
    filter_func_name: str,
    custom_params: dict = None
) -> sitk.Image:
    """
    Apply a filter with modality-specific parameters.

    Parameters
    ----------
    itk_image : sitk.Image
        Input image
    metadata : dict
        Metadata containing modality information
    filter_func_name : str
        Name of the filter function to apply
    custom_params : dict, optional
        Custom parameters to override modality defaults

    Returns
    -------
    sitk.Image
        Filtered image
    """
    # Get modality from metadata
    modality = metadata.get("series", {}).get("modality", "MR").upper()

    # Get modality-specific parameters
    params = get_modality_specific_params(modality, filter_func_name)

    # Override with custom parameters if provided
    if custom_params:
        params.update(custom_params)

    # Apply the appropriate filter
    if filter_func_name == "smoothing":
        return smoothing(itk_image)
    elif filter_func_name == "unsharp_mask":
        return apply_unsharp_mask(itk_image, amount=params["amount"], radius=params["radius"])
    elif filter_func_name == "gaussian_sharpening":
        return apply_gaussian_sharpening(itk_image, sigma=params["sigma"], alpha=params["alpha"])
    elif filter_func_name == "laplacian_sharpening":
        return apply_laplacian_sharpening(itk_image, alpha=params["alpha"])
    elif filter_func_name == "adaptive_sharpening":
        return apply_adaptive_sharpening(
            itk_image,
            base_amount=params["base_amount"],
            edge_boost=params["edge_boost"],
            sigma=params["sigma"]
        )
    elif filter_func_name == "edge_smooth_ultrafast":
        return edge_smooth_ultrafast(
            itk_image,
            blur_sigma_mm=params["blur_sigma_mm"],
            edge_sigma_mm=params["edge_sigma_mm"]
        )
    else:
        raise ValueError(f"Unknown filter function: {filter_func_name}")