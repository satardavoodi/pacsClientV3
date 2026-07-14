# راهنمای کامل الگوریتم کمان تناظر (Correspondence Arc Algorithm)

این مستند راهنمای کامل استفاده از الگوریتم کمان تناظر برای پروژکشن دقیق ضایعات
بین نماهای CC و MLO در ماموگرافی است.

## 📋 فهرست مطالب

1. [معرفی](#معرفی)
2. [اصول فیزیکی](#اصول-فیزیکی)
3. [ماژول‌ها](#ماژول‌ها)
4. [نصب و راه‌اندازی](#نصب-و-راه‌اندازی)
5. [استفاده](#استفاده)
6. [تست و Validation](#تست-و-validation)
7. [Visualization](#visualization)
8. [مثال‌های کاربردی](#مثال‌های-کاربردی)

---

## معرفی

الگوریتم کمان تناظر (Correspondence Arc Algorithm) یک روش فیزیکی دقیق برای پروژکشن
ضایعات بین نماهای CC و MLO در ماموگرافی است. این الگوریتم به جای استفاده از
پروژکشن خطی ساده (straight-line projection)، از اصول فیزیک اشعه‌ایکس و قانون Kopans
استفاده می‌کند.

### مزایا نسبت به روش قبلی:

✓ **دقت بالاتر**: استفاده از کمان به جای خط مستقیم  
✓ **در نظر گرفتن زاویه pectoral muscle**: تطبیق با آناتومی واقعی  
✓ **Clipping به محدوده بافت سینه**: حذف نقاط خارج از contour  
✓ **جستجوی هوشمند**: استفاده از Density Correlation برای یافتن بهترین نقطه  

### به روزرسانی وضعیت پیاده سازی (July 2026)

نسخه فعلی در مسیر Runtime علاوه بر کمان هندسی، از **Probability Heatmap** روی کمان استفاده می کند
و رفتار نمایش را برای خروج از میدان دید (FOV) اصلاح کرده است.

موارد فعال در نسخه فعلی:

1. **تبدیل دقیق مختصات کلیک**
- ماژول جدید `coord_utils.py` مسیر استاندارد تبدیل را فراهم می کند:
    `Widget -> Display (VTK) -> World -> IJK`.
- روش اصلی: `DisplayToWorld` (دقیق تر برای Viewer دوبعدی).

2. **Probability Heatmap واقعی روی کمان**
- ماژول `arc_probability.py` احتمال هر نقطه روی کمان را از ترکیب چند Feature محاسبه می کند.
- نمایش Heatmap در `visualization.py::draw_arc_probability_heatmap` انجام می شود.

3. **FOV Clipping برای کمان**
- اگر کل کمان خارج تصویر باشد، کمان رسم نمی شود و پیام `Outside FOV` نمایش داده می شود.
- اگر فقط بخشی از کمان داخل تصویر باشد، زاویه کمان به بازه قابل مشاهده clip می شود.

---

## اصول فیزیکی

### قانون Kopans (Kopans' Rule)

در ماموگرافی، فاصله از نوک پستان (nipple) در فضای 3D سینه حفظ می‌شود:

```
d_CC ≈ d_MLO
```

که در آن:
- `d = √(X² + Y²)`: فاصله از nipple در صفحه XY

### پروژکشن‌های اشعه‌ایکس

#### نمای CC (Cranio-Caudal):
```
محور Z فشرده می‌شود → (X, Y) قابل مشاهده است
```

#### نمای MLO (Medio-Lateral Oblique):
```
پروژکشن در زاویه θ_pec:
H = Y·sin(θ) + Z·cos(θ)
→ (X, H) قابل مشاهده است
```

### کمان تناظر

با استفاده از قانون Kopans، نقاط ممکن برای ضایعه در نمای مقصد یک **کمان دایره‌ای**
با مشخصات زیر تشکیل می‌دهند:

- **مرکز**: موقعیت nipple در نمای مقصد
- **شعاع**: فاصله ضایعه از nipple در نمای منبع
- **محدوده زاویه‌ای**: محدود شده توسط زاویه pectoral muscle و آناتومی

---

## ماژول‌ها

### 1. `geometry.py`
**پایه‌ای‌ترین ماژول** - کلاس‌ها و توابع هندسی:
- `PixelSpacing`: تبدیل pixel ↔ mm
- `ImageGeometry`: مشخصات تصویر
- `NipplePosition`: موقعیت nipple
- `LesionLocation`: موقعیت ضایعه
- `MammogramGeometry`: هندسه کامل ماموگرام

### 2. `pectoral_detection.py`
**تشخیص خودکار زاویه pectoral muscle** در نمای MLO:
- استفاده از Hough Line Transform
- فیلترینگ براساس موقعیت و طول
- Fallback به زاویه پیش‌فرض (50°) در صورت عدم تشخیص

**توابع اصلی:**
```python
from pectoral_detection import detect_pectoral_angle

pectoral_line = detect_pectoral_angle(
    image=mlo_image,
    laterality='R',
    roi_height_fraction=0.5,
    roi_width_fraction=0.6,
    min_angle_deg=30,
    max_angle_deg=70,
)

angle = pectoral_line.angle_deg if pectoral_line else 50.0
```

### 3. `breast_contour.py`
**Segmentation محدوده بافت سینه**:
- استفاده از Otsu thresholding
- Morphological operations
- Contour smoothing

**توابع اصلی:**
```python
from breast_contour import segment_breast_contour, is_point_inside_contour

contour = segment_breast_contour(image)
valid = is_point_inside_contour(point, contour)
```

### 4. `correspondence_arc.py`
**هسته اصلی الگوریتم**:
- محاسبه کمان تناظر
- Clipping به contour سینه
- Refine با Density Correlation

**توابع اصلی:**
```python
from correspondence_arc import compute_correspondence_arc

arc = compute_correspondence_arc(
    source_lesion=cc_lesion,
    source_geom=cc_geom,
    target_geom=mlo_geom,
    source_view='CC',
    target_view='MLO',
    pectoral_angle_deg=50.0,
    breast_contour=mlo_contour,
    angular_resolution_deg=1.0,
    angle_margin_deg=30.0,
)

# دسترسی به نتایج
best_point = arc.best_point_px
confidence = arc.confidence
radius_mm = arc.radius_mm
```

### 5. `correlator.py`
**ادغام با سیستم 3D Cursor**:
- فراخوانی تمام ماژول‌های بالا
- مدیریت CC/MLO pairs
- استفاده از `_project_lesion_with_arc()` به جای `_project_lesion()`

### 6. `visualization.py`
**نمایش بصری نتایج**:
- رسم کمان روی تصویر
- نمایش زاویه‌ها با annotation
- باکس اطلاعات با فرمول‌ها و محاسبات
- Heatmap احتمالات روی کمان
- کنترل FOV (skip/clip) برای جلوگیری از رسم خارج از تصویر

**توابع مهم نسخه فعلی:**
```python
from modules.ai_imaging.ai_module_ui.cursor_3d.visualization import (
    draw_arc_probability_heatmap,
)
```

### 7. `coord_utils.py`
**تبدیل دقیق مختصات بین Qt/VTK/Image**:
- `widget_to_image_coords(...)`
- `get_pixel_array_from_viewer(...)`

این ماژول توسط pickerها استفاده می شود تا مختصات ذخیره شده با کلیک کاربر همخوانی بالاتری داشته باشد.

### 8. `arc_probability.py`
**محاسبه احتمال روی کمان**:
- خروجی اصلی: `ArcProbabilityResult`
- تابع اصلی: `compute_arc_probability(...)`

Featureهای فعلی:
- Density
- Texture (gradient)
- Geometric prior
- Histogram divergence
- Entropy
- Local contrast

**توابع اصلی:**
```python
from modules.ai_imaging.ai_module_ui.cursor_3d.arc_probability import compute_arc_probability
from modules.ai_imaging.ai_module_ui.cursor_3d.visualization import draw_arc_probability_heatmap

prob_result = compute_arc_probability(
    pixel_array=img,
    nipple_x_px=nx,
    nipple_y_px=ny,
    radius_px=r,
    start_angle_rad=a0,
    end_angle_rad=a1,
    pectoral_angle_deg=pect_angle,
)

draw_arc_probability_heatmap(
    vtk_widget=target_vtk_widget,
    prob_result=prob_result,
)
```

### 9. `test_demo.py`
**تست و Validation**:
- داده‌های synthetic برای آزمایش
- محاسبه خطای دقت
- Test suite جامع

---

## نصب و راه‌اندازی

### پیش‌نیازها:

```bash
pip install numpy opencv-python pydicom
```

### ساختار فایل‌ها:

```
modules/ai_imaging/ai_module_ui/cursor_3d/
├── geometry.py              # Base geometric primitives
├── pectoral_detection.py    # Automatic pectoral angle detection
├── breast_contour.py         # Breast tissue segmentation
├── correspondence_arc.py     # Core arc algorithm
├── correlator.py             # Integration with 3D cursor
├── visualization.py          # Drawing functions
├── test_demo.py              # Test suite and demo
└── README.md                 # This file
```

---

## استفاده

### مثال کامل - CC به MLO:

```python
from modules.ai_imaging.ai_module_ui.cursor_3d import (
    MammogramGeometry,
    LesionLocation,
    compute_correspondence_arc,
    detect_pectoral_angle,
    segment_breast_contour,
    draw_correspondence_arc_with_annotations,
)

# 1. آماده‌سازی داده‌ها
cc_geom = MammogramGeometry(...)  # از DICOM metadata
mlo_geom = MammogramGeometry(...)

cc_lesion = LesionLocation(...)  # از AI detection

# 2. تشخیص زاویه pectoral muscle
pectoral_line = detect_pectoral_angle(
    image=mlo_image,
    laterality='R',
)
pectoral_angle = pectoral_line.angle_deg if pectoral_line else 50.0

# 3. Segmentation contour سینه
mlo_contour = segment_breast_contour(mlo_image)

# 4. محاسبه کمان تناظر
arc = compute_correspondence_arc(
    source_lesion=cc_lesion,
    source_geom=cc_geom,
    target_geom=mlo_geom,
    source_view='CC',
    target_view='MLO',
    pectoral_angle_deg=pectoral_angle,
    breast_contour=mlo_contour,
)

# 5. استفاده از نتایج
if arc.best_point_px:
    projected_x, projected_y = arc.best_point_px
    print(f"Projected lesion at: ({projected_x:.1f}, {projected_y:.1f})")
    print(f"Confidence: {arc.confidence:.1%}")
    print(f"Arc radius: {arc.radius_mm:.1f} mm")

# 6. Visualization (optional)
from modules.ai_imaging.ai_module_ui.cursor_3d.visualization import (
    draw_correspondence_arc_with_annotations,
)

draw_correspondence_arc_with_annotations(
    match=cursor_match,
    view_data=mlo_view_data,
    laterality='R',
    show_angle_annotations=True,
    show_info_box=True,
)
```

---

## تست و Validation

### اجرای تست‌های خودکار:

```python
from modules.ai_imaging.ai_module_ui.cursor_3d.test_demo import (
    demo_correspondence_arc_visualization,
    run_comprehensive_test_suite,
)

# Demo کامل با نمایش نتایج
demo_correspondence_arc_visualization()

# یا Test Suite جامع
stats = run_comprehensive_test_suite(verbose=True)

print(f"Success Rate: {stats['success_rate']:.1%}")
print(f"Mean Error: {stats['mean_error_mm']:.2f} mm")
```

### تست دستی با داده‌های خاص:

```python
from modules.ai_imaging.ai_module_ui.cursor_3d.test_demo import (
    test_cc_to_mlo_projection,
    test_mlo_to_cc_projection,
    SyntheticLesion3D,
)

# تعریف ضایعه test
my_lesion = SyntheticLesion3D(
    x_mm=40.0,  # Medial-lateral
    y_mm=60.0,  # Posterior-anterior
    z_mm=30.0,  # Cranio-caudal
)

# تست CC → MLO
result = test_cc_to_mlo_projection(
    lesion_3d=my_lesion,
    pectoral_angle_deg=52.0,
    verbose=True,
)

if result['success']:
    print(f"✓ Test passed with error: {result['error_mm']:.2f} mm")
else:
    print(f"✗ Test failed")
```

---

## Visualization

### وضعیت فعلی Visualization در Runtime

- کمان هندسی (inner/nominal/outer) رسم می شود.
- Heatmap احتمال به صورت segment-based روی کمان رسم می شود.
- peak marker برای بیشترین احتمال نمایش داده می شود (در احتمال بالا).
- اگر کمان کاملا خارج تصویر باشد: کمان رسم نمی شود و پیام `Outside FOV` نمایش می یابد.
- اگر کمان بخشی خارج تصویر باشد: بازه زاویه ای قابل رسم clip می شود.

### رسم کمان با annotation های کامل:

الگوریتم visualization شامل چهار بخش اصلی است:

#### 1. رسم کمان (Arc Curve)
- کمان به صورت یک منحنی صاف آبی رنگ
- Thickness قابل تنظیم برای دیده شدن بهتر

#### 2. Annotation زاویه‌ها (Angular Annotations)
- خطوط شعاعی برای Start، Center، End angles
- رنگ‌های متمایز:
  - سبز: زاویه شروع
  - زرد: زاویه مرکز
  - قرمز: زاویه پایان

#### 3. باکس اطلاعات (Info Box)
نمایش اطلاعات زیر در یک باکس متنی:
- فرمول‌های فیزیکی (Kopans' Rule)
- شعاع کمان (mm و pixel)
- محدوده زاویه‌ای (Start, End, Span)
- تعداد نقاط کمان
- Confidence score
- اطلاعات پروژکشن MLO (H = Y·sin(θ) + Z·cos(θ))

#### 4. نشانگر نقطه بهینه (Best Point Marker)
- یک نشانگر طلایی روی بهترین نقطه پیش‌بینی شده

### مثال استفاده:

```python
from modules.ai_imaging.ai_module_ui.cursor_3d.visualization import (
    draw_correspondence_arc_with_annotations,
)

# با همه annotation ها
draw_correspondence_arc_with_annotations(
    match=cursor_match,
    view_data=target_view,
    laterality='R',
    show_angle_annotations=True,   # نمایش خطوط زاویه
    show_info_box=True,             # نمایش باکس اطلاعات
    show_formula=True,              # نمایش فرمول‌ها در باکس
)

# فقط کمان بدون annotation
draw_correspondence_arc_with_annotations(
    match=cursor_match,
    view_data=target_view,
    laterality='R',
    show_angle_annotations=False,
    show_info_box=False,
)
```

---

## مثال‌های کاربردی

## عیب یابی سریع (Runtime)

### 1) کمان بیرون تصویر رسم می شود
- انتظار فعلی: اگر کل کمان بیرون باشد، باید skip شود و `Outside FOV` ببینید.
- اگر این اتفاق نیفتاد، بررسی کنید ابعاد تصویر از metadata قابل خواندن باشد (`rows/columns`).

### 2) Heatmap دیده نمی شود
- مسیر اجرا باید `compute_arc_probability(...)` را با `start_angle_rad/end_angle_rad` صحیح فراخوانی کند.
- سپس `draw_arc_probability_heatmap(...)` روی همان target viewer صدا زده شود.
- وجود logهای `[3D-Cursor][HEATMAP]` در خروجی کمک می کند مسیر اجرا را تایید کنید.

### مثال 1: یافتن تطابق برای یک ضایعه در CC

```python
# فرض: یک ضایعه در CC view شناسایی شده است
# هدف: یافتن موقعیت آن در MLO view

from modules.ai_imaging.ai_module_ui.cursor_3d import (
    compute_correspondence_arc,
    detect_pectoral_angle,
    segment_breast_contour,
)

# 1. تشخیص پارامترهای MLO
pectoral_line = detect_pectoral_angle(mlo_image, 'R')
pectoral_angle = pectoral_line.angle_deg if pectoral_line else 50.0
mlo_contour = segment_breast_contour(mlo_image)

# 2. محاسبه کمان
arc = compute_correspondence_arc(
    source_lesion=cc_lesion,
    source_geom=cc_geometry,
    target_geom=mlo_geometry,
    source_view='CC',
    target_view='MLO',
    pectoral_angle_deg=pectoral_angle,
    breast_contour=mlo_contour,
)

# 3. استخراج نتیجه
if arc.best_point_px:
    print(f"✓ Lesion found at: {arc.best_point_px}")
    print(f"  Confidence: {arc.confidence:.1%}")
    
    # ایجاد bounding box برای ضایعه پیش‌بینی شده
    center_x, center_y = arc.best_point_px
    width = cc_lesion.width_px
    height = cc_lesion.height_px
    
    projected_box = [
        center_x - width/2,
        center_y - height/2,
        center_x + width/2,
        center_y + height/2,
    ]
else:
    print("✗ Lesion out of field or no valid arc")
```

### مثال 2: Batch Processing

```python
def process_all_cc_lesions(cc_lesions, cc_geom, mlo_geom, mlo_image):
    """پروژکشن تمام ضایعات CC به MLO"""
    
    # تشخیص یکباره پارامترهای MLO
    pectoral_line = detect_pectoral_angle(mlo_image, cc_geom.laterality)
    pectoral_angle = pectoral_line.angle_deg if pectoral_line else 50.0
    mlo_contour = segment_breast_contour(mlo_image)
    
    results = []
    
    for lesion in cc_lesions:
        arc = compute_correspondence_arc(
            source_lesion=lesion,
            source_geom=cc_geom,
            target_geom=mlo_geom,
            source_view='CC',
            target_view='MLO',
            pectoral_angle_deg=pectoral_angle,
            breast_contour=mlo_contour,
        )
        
        results.append({
            'source_lesion': lesion,
            'arc': arc,
            'projected_point': arc.best_point_px,
            'confidence': arc.confidence,
        })
    
    return results
```

### مثال 3: مقایسه با Ground Truth

```python
from modules.ai_imaging.ai_module_ui.cursor_3d.test_demo import (
    SyntheticLesion3D,
    test_cc_to_mlo_projection,
)

# تعریف ضایعه با موقعیت 3D معلوم
ground_truth_lesion = SyntheticLesion3D(
    x_mm=35.0,
    y_mm=55.0,
    z_mm=28.0,
)

# تست الگوریتم
result = test_cc_to_mlo_projection(
    lesion_3d=ground_truth_lesion,
    pectoral_angle_deg=52.0,
    verbose=True,
)

# بررسی دقت
if result['error_mm'] < 5.0:
    print("✓ Excellent accuracy (< 5mm error)")
elif result['error_mm'] < 10.0:
    print("✓ Good accuracy (< 10mm error)")
else:
    print("⚠ Review parameters - error too large")
```

---

## تنظیمات پیشرفته

### تنظیم پارامترهای پروژکشن:

```python
arc = compute_correspondence_arc(
    source_lesion=lesion,
    source_geom=source_geom,
    target_geom=target_geom,
    source_view='CC',
    target_view='MLO',
    pectoral_angle_deg=50.0,
    breast_contour=contour,
    angular_resolution_deg=0.5,     # دقت بالاتر (default: 1.0)
    angle_margin_deg=45.0,           # محدوده زاویه‌ای بزرگتر (default: 30.0)
    density_window_px=5,             # پنجره بزرگتر برای correlation (default: 3)
    min_confidence=0.3,              # آستانه پایین‌تر (default: 0.5)
)
```

---

## ابزارهای اندازه‌گیری (Ruler Tools)

### انواع Ruler های موجود

سیستم 3D Cursor سه نوع ruler برای اندازه‌گیری فاصله‌ها فراهم می‌کند:

#### 1. Ruler پیش‌فرض (Nipple → Lesion) 🔷

**مشخصات:**
- رنگ: آبی روشن `(0.0, 0.6, 1.0)`
- خط: چین‌دار (dashed pattern)
- نشانگر: دایره کوچک در دو سر
- برچسب: فاصله با پیشوند view (مثلاً "CC: 45.2 mm")

**کاربرد:**
- نمایش فاصله ضایعه از نوک پستان
- تایید صحت محاسبات قانون Kopans
- مقایسه عمق در هر دو نما

**استفاده:**
```python
from modules.ai_imaging.ai_module_ui.cursor_3d.visualization import (
    draw_rulers_for_results,
)

# رسم ruler های آبی از nipple به تمام ضایعات
draw_rulers_for_results(
    result=cursor_result,
    views_by_key=views_dict,
)
```

---

#### 2. Ruler بین ضایعات (Lesion ↔ Lesion) 🟠

**مشخصات:**
- رنگ: نارنجی `(1.0, 0.6, 0.0)`
- خط: ممتد (solid line)
- نشانگر: الماس (diamond/cone) در دو سر
- برچسب: فاصله با سمبل ↔

**کاربرد:**
- اندازه‌گیری فاصله بین دو یافته مختلف
- ارزیابی توزیع فضایی ضایعات
- تعیین فاصله بین توده‌های متعدد

**استفاده:**
```python
from modules.ai_imaging.ai_module_ui.cursor_3d.visualization import (
    draw_lesion_to_lesion_rulers,
)

# رسم ruler های نارنجی بین تمام ضایعات
draw_lesion_to_lesion_rulers(
    result=cursor_result,
    views_by_key=views_dict,
    draw_on_paired=True,      # رسم برای ضایعات paired
    draw_on_projected=False,  # نادیده گرفتن ضایعات projected
)
```

**توضیح پارامترها:**
- `draw_on_paired=True`: ruler بین ضایعاتی که در هر دو نما (CC و MLO) دیده می‌شوند
- `draw_on_projected=True`: ruler شامل ضایعات پروژکشن شده هم می‌شود

---

#### 3. Ruler سفارشی (Custom Measurement) 🎨

**مشخصات:**
- رنگ: قابل تنظیم (پیش‌فرض نارنجی)
- خط: ممتد با ضخامت قابل تنظیم
- نشانگر: کره در دو سر
- برچسب: سفارشی + فاصله

**کاربرد:**
- اندازه‌گیری فاصله بین هر دو نقطه دلخواه
- اندازه‌گیری قطر یک ضایعه
- فاصله از لبه یا مرزهای خاص

**استفاده:**
```python
from modules.ai_imaging.ai_module_ui.cursor_3d.visualization import (
    draw_custom_ruler,
)

# رسم ruler سبز بین دو نقطه
distance_mm = draw_custom_ruler(
    vtk_widget=viewer.vtk_widget,
    point1_px=(100, 200),
    point2_px=(350, 450),
    pixel_spacing=geometry.image.pixel_spacing,
    label="قطر توده",
    color=(0.0, 1.0, 0.0),  # سبز
    line_width=3.5,
)

print(f"فاصله اندازه‌گیری شده: {distance_mm:.1f} mm")
```

**پارامترهای قابل تنظیم:**
- `point1_px`, `point2_px`: مختصات پیکسلی دو نقطه
- `pixel_spacing`: برای تبدیل پیکسل به میلی‌متر
- `label`: برچسب سفارشی (اختیاری)
- `color`: رنگ به صورت tuple (R, G, B) در بازه 0-1
- `line_width`: ضخامت خط (پیش‌فرض 3.0)

---

### مثال‌های کاربردی Ruler

#### مثال 1: نمایش جامع با همه ruler ها

```python
from modules.ai_imaging.ai_module_ui.cursor_3d import (
    compute_3d_cursor,
)
from modules.ai_imaging.ai_module_ui.cursor_3d.visualization import (
    draw_3d_cursor_results,
    draw_rulers_for_results,
    draw_lesion_to_lesion_rulers,
)

# محاسبه نتایج 3D cursor
result = compute_3d_cursor(views_by_key, boxes_by_key)

# 1. رسم box های ضایعات و cursor ها
draw_3d_cursor_results(result, views_by_key, draw_rulers=False)

# 2. ruler های آبی (nipple → lesion)
draw_rulers_for_results(result, views_by_key)

# 3. ruler های نارنجی (lesion ↔ lesion)
draw_lesion_to_lesion_rulers(
    result,
    views_by_key,
    draw_on_paired=True,
    draw_on_projected=True,
)

print("✓ تمام ruler ها رسم شدند")
```

#### مثال 2: اندازه‌گیری‌های سفارشی با رنگ‌های مختلف

```python
from modules.ai_imaging.ai_module_ui.cursor_3d.visualization import (
    draw_custom_ruler,
)

# تعریف رنگ‌ها
COLORS = {
    'قرمز': (1.0, 0.0, 0.0),
    'سبز': (0.0, 1.0, 0.0),
    'آبی': (0.0, 0.0, 1.0),
    'زرد': (1.0, 1.0, 0.0),
    'ارغوانی': (1.0, 0.0, 1.0),
}

# اندازه‌گیری چند فاصله
measurements = []

# 1. قطر افقی توده
d1 = draw_custom_ruler(
    vtk_widget, (120, 180), (210, 185),
    pixel_spacing, label="قطر افقی", color=COLORS['قرمز']
)
measurements.append(('قطر افقی', d1))

# 2. قطر عمودی توده
d2 = draw_custom_ruler(
    vtk_widget, (165, 140), (168, 220),
    pixel_spacing, label="قطر عمودی", color=COLORS['سبز']
)
measurements.append(('قطر عمودی', d2))

# 3. فاصله از لبه
d3 = draw_custom_ruler(
    vtk_widget, (165, 180), (50, 180),
    pixel_spacing, label="فاصله از لبه", color=COLORS['آبی']
)
measurements.append(('فاصله از لبه', d3))

# نمایش نتایج
print("\n📏 نتایج اندازه‌گیری:")
for name, distance in measurements:
    print(f"  {name}: {distance:.1f} mm")
```

#### مثال 3: ruler فقط برای ضایعات paired

```python
# رسم ruler فقط بین ضایعاتی که در هر دو نما مشاهده می‌شوند
draw_lesion_to_lesion_rulers(
    result=cursor_result,
    views_by_key=views_dict,
    draw_on_paired=True,      # ✓ فعال
    draw_on_projected=False,  # ✗ غیرفعال
)

print("✓ Ruler ها فقط برای ضایعات paired رسم شدند")
print("  ضایعات projected نادیده گرفته شدند")
```

---

### پالت رنگ و سبک‌های Ruler

```python
# رنگ‌های از پیش تعریف شده در visualization.py
COLOR_RULER = (0.0, 0.6, 1.0)          # آبی - nipple ruler
COLOR_RULER_TEXT = (0.8, 0.95, 1.0)    # آبی روشن - text labels
COLOR_LESION_RULER = (1.0, 0.6, 0.0)   # نارنجی - lesion ruler
COLOR_LESION_RULER_TEXT = (1.0, 0.9, 0.6)  # نارنجی روشن - text labels
```

**جدول مقایسه ruler ها:**

| ویژگی | Nipple Ruler | Lesion Ruler | Custom Ruler |
|-------|--------------|--------------|--------------|
| رنگ پیش‌فرض | آبی (0.0, 0.6, 1.0) | نارنجی (1.0, 0.6, 0.0) | قابل تنظیم |
| نوع خط | چین‌دار (dashed) | ممتد (solid) | ممتد |
| ضخامت خط | 2.0 | 3.0 | قابل تنظیم |
| نشانگر | دایره (sphere) | الماس (cone) | کره (sphere) |
| برچسب | "CC: 45.2 mm" | "CC ↔ 32.5 mm" | سفارشی |
| نقطه شروع | Nipple | مرکز ضایعه 1 | نقطه دلخواه 1 |
| نقطه پایان | مرکز ضایعه | مرکز ضایعه 2 | نقطه دلخواه 2 |
| خروجی | بدون مقدار | بدون مقدار | فاصله (mm) |

---

### نکات مهم و پیکربندی

#### 1. مدیریت Actor ها

همه ruler ها به صورت VTK actor ذخیره می‌شوند:

```python
# در vtk_widget, actor ها ذخیره می‌شوند برای پاکسازی
if not hasattr(vtk_widget, '_projected_actors'):
    vtk_widget._projected_actors = []
vtk_widget._projected_actors.append(ruler_actor)
```

برای پاکسازی:
```python
from modules.ai_imaging.ai_module_ui.cursor_3d.visualization import (
    _clear_projected_actors,
)

_clear_projected_actors(vtk_widget)
```

#### 2. تبدیل مختصات

تمام ruler ها از سیستم تبدیل مختصات یکسان استفاده می‌کنند:

```python
# Pixel → World coordinates
world_pos = image_viewer.ijk_to_world(
    pixel_x, 
    pixel_y, 
    None,      # z (slice) نادیده گرفته می‌شود
    y_flip=True  # تطبیق با سیستم مختصات DICOM
)
```

#### 3. محاسبه فاصله

فاصله در میلی‌متر محاسبه می‌شود:

```python
# فاصله اقلیدسی در پیکسل
dx_px = point2_x - point1_x
dy_px = point2_y - point1_y
distance_px = math.sqrt(dx_px**2 + dy_px**2)

# تبدیل به میلی‌متر با استفاده از pixel spacing
pixel_spacing_avg = (pixel_spacing.col_mm + pixel_spacing.row_mm) / 2.0
distance_mm = distance_px * pixel_spacing_avg
```

#### 4. Text Labels و Camera Following

همه برچسب‌ها از `vtkFollower` استفاده می‌کنند:

```python
text_actor = vtk.vtkFollower()
text_actor.SetMapper(text_mapper)
text_actor.SetScale(4.5, 4.5, 4.5)
text_actor.SetPosition(mid_x, mid_y + 5.0, mid_z)

# اتصال به دوربین برای چرخش همیشه رو به بیننده
camera = renderer.GetActiveCamera()
if camera:
    text_actor.SetCamera(camera)
```

---

## Troubleshooting

### مشکلات متداول و راه‌حل

#### 1. خطای "No valid arc" یا confidence پایین

**علت:**
- زاویه pectoral اشتباه تشخیص داده شده
- Contour سینه نادرست است
- ضایعه خارج از محدوده قابل رویت است

**راه‌حل:**
```python
# تنظیم دستی زاویه pectoral
arc = compute_correspondence_arc(
    ...,
    pectoral_angle_deg=55.0,  # به جای تشخیص خودکار
    angle_margin_deg=45.0,     # افزایش محدوده جستجو
    min_confidence=0.3,        # کاهش آستانه confidence
)
```

#### 2. Ruler ها نمایش داده نمی‌شوند

**علت:**
- VTK widget معتبر نیست
- Renderer ندارد
- مشکل در تبدیل مختصات

**راه‌حل:**
```python
# بررسی VTK widget
if hasattr(vtk_widget, 'image_viewer'):
    image_viewer = vtk_widget.image_viewer
    if hasattr(image_viewer, 'renderer'):
        # Renderer موجود است
        draw_rulers_for_results(result, views_by_key)
    else:
        print("⚠ Renderer not found")
else:
    print("⚠ Invalid VTK widget")
```

#### 3. فاصله‌های اشتباه در Ruler

**علت:**
- PixelSpacing DICOM نادرست یا گم شده
- اشتباه در تبدیل مختصات

**راه‌حل:**
```python
# بررسی pixel spacing
print(f"Pixel Spacing: {pixel_spacing.row_mm} × {pixel_spacing.col_mm} mm")

# در صورت لزوم تنظیم دستی
from modules.ai_imaging.ai_module_ui.cursor_3d.geometry import PixelSpacing

pixel_spacing = PixelSpacing(row_mm=0.07, col_mm=0.07)
```

#### 4. Custom Ruler رنگ نادرست دارد

**علت:**
- مقادیر RGB خارج از بازه [0, 1]
- Tuple به درستی تعریف نشده

**راه‌حل:**
```python
# رنگ صحیح (مقادیر 0.0 تا 1.0)
color_correct = (1.0, 0.5, 0.0)  # ✓ نارنجی

# رنگ اشتباه
color_wrong = (255, 128, 0)      # ✗ باید تقسیم بر 255 شود

# تبدیل از 0-255 به 0-1
color_fixed = (255/255, 128/255, 0/255)  # ✓
```

---

## مراجع و منابع

### مقالات علمی:

1. **Kopans, D. B.** (1992). "The positive predictive value of mammography."
   *American Journal of Roentgenology*, 158(3), 521-526.

2. **Highnam, R., & Brady, M.** (1999). "Mammographic Image Analysis."
   *Springer Science & Business Media*.

3. **Pisano, E. D., et al.** (2008). "Diagnostic Accuracy of Digital versus
   Film Mammography: Exploratory Analysis of Selected Population Subgroups."
   *Radiology*, 246(2), 376-383.

### راهنماهای تکنیکی:

- **DICOM Standard**: https://www.dicomstandard.org/
- **VTK Documentation**: https://vtk.org/doc/nightly/html/
- **OpenCV Hough Transform**: https://docs.opencv.org/

---

## لایسنس و مشارکت

این کد بخشی از پروژه AI-PACS است و برای استفاده داخلی توسعه داده شده است.

**ویرایش اخیر**: 2024  
**نسخه**: 2.0 (با Ruler Tools)
    source_lesion=lesion,
    source_geom=cc_geom,
    target_geom=mlo_geom,
    source_view='CC',
    target_view='MLO',
    pectoral_angle_deg=50.0,
    breast_contour=contour,
    
    # پارامترهای قابل تنظیم:
    angular_resolution_deg=1.0,     # وضوح زاویه‌ای (کمتر = دقیق‌تر ولی کندتر)
    angle_margin_deg=30.0,          # Margin برای محدوده زاویه‌ای
)
```

### تنظیم پارامترهای تشخیص Pectoral:

```python
pectoral_line = detect_pectoral_angle(
    image=mlo_image,
    laterality='R',
    
    # پارامترهای قابل تنظیم:
    roi_height_fraction=0.5,        # ارتفاع ROI (0-1)
    roi_width_fraction=0.6,         # عرض ROI (0-1)
    min_angle_deg=30,               # حداقل زاویه قابل قبول
    max_angle_deg=70,               # حداکثر زاویه قابل قبول
    min_line_length=100,            # حداقل طول خط (pixels)
)
```

### تنظیم پارامترهای Segmentation:

```python
contour = segment_breast_contour(
    image=image,
    
    # پارامترهای قابل تنظیم:
    threshold_value=None,           # None = استفاده از Otsu
    min_area_fraction=0.05,         # حداقل مساحت component (0-1)
)
```

---

## Performance Optimization

### Tips برای افزایش سرعت:

1. **کش کردن نتایج تشخیص**:
   ```python
   # تشخیص یکبار - استفاده چندبار
   pectoral_angle = detect_pectoral_angle(mlo_image, 'R').angle_deg
   mlo_contour = segment_breast_contour(mlo_image)
   
   # استفاده برای تمام ضایعات
   for lesion in lesions:
       arc = compute_correspondence_arc(..., pectoral_angle_deg=pectoral_angle, ...)
   ```

2. **کاهش وضوح زاویه‌ای برای سرعت بیشتر**:
   ```python
   arc = compute_correspondence_arc(..., angular_resolution_deg=2.0)  # 2 درجه به جای 1
   ```

3. **محدود کردن ROI در تشخیص Pectoral**:
   ```python
   pectoral = detect_pectoral_angle(..., roi_height_fraction=0.4, roi_width_fraction=0.5)
   ```

---

## خطایابی (Troubleshooting)

### مشکل: کمان خارج از تصویر است

**علت**: شعاع کمان خیلی بزرگ است یا nipple position نادرست است.

**راه‌حل**:
```python
# بررسی nipple position
print(f"Nipple: ({geometry.nipple.x_px}, {geometry.nipple.y_px})")
print(f"Image size: {geometry.image.width_px} × {geometry.image.height_px}")

# بررسی شعاع
print(f"Arc radius: {arc.radius_mm} mm = {arc.radius_px} px")
```

### مشکل: تشخیص Pectoral ناموفق

**علت**: تصویر MLO واضح نیست یا زاویه خارج از محدوده است.

**راه‌حل**:
```python
# استفاده از fallback manual
if pectoral_line is None:
    pectoral_angle = 50.0  # زاویه پیش‌فرض
else:
    pectoral_angle = pectoral_line.angle_deg
    
# یا تنظیم محدوده زاویه
pectoral_line = detect_pectoral_angle(
    ...,
    min_angle_deg=25,  # محدوده وسیع‌تر
    max_angle_deg=75,
)
```

### مشکل: Confidence پایین

**علت**: ضایعه خیلی نزدیک به nipple است یا کمان خارج از contour است.

**راه‌حل**:
```python
# بررسی پیام خطا
print(arc.message)

# بررسی نقاط معتبر
print(f"Valid arc points: {len(arc.arc_points_px)}")
print(f"Confidence: {arc.confidence}")

# افزایش margin زاویه‌ای
arc = compute_correspondence_arc(..., angle_margin_deg=45.0)
```

---

## مراجع و منابع

### مقالات علمی:
1. Kopans D.B. - "Breast Imaging" (Textbook)
2. Diffey J. et al. - "The accuracy of lesion localization in mammography"

### کدهای مرتبط در پروژه:
- `modules/ai_imaging/ai_module_ui/cursor_3d/geometry.py`
- `modules/ai_imaging/ai_module_ui/cursor_3d/correlator.py`
- `modules/ai_imaging/ai_module_ui/overrides/vtk_widget.py`

---

## تماس و پشتیبانی

برای سؤالات، گزارش باگ یا پیشنهادات:
- ایجاد Issue در repository
- مراجعه به مستندات API در docstrings
- اجرای `demo_correspondence_arc_visualization()` برای مثال‌های عملی

---

## تاریخچه تغییرات

### نسخه 1.0 (2024)
- پیاده‌سازی اولیه الگوریتم کمان تناظر
- تشخیص خودکار زاویه pectoral muscle
- Segmentation contour سینه
- Visualization کامل با annotation ها
- Test suite جامع با داده‌های synthetic

---

**نوشته شده با ❤️ برای بهبود دقت تشخیص سرطان سینه**
