"""
مثال استفاده از Ruler های جدید در سیستم 3D Cursor ماموگرافی

این فایل نمونه‌هایی از استفاده از انواع مختلف ruler را نشان می‌دهد:
1. Ruler پیش‌فرض از nipple به lesion (موجود قبلی)
2. Ruler جدید بین دو ضایعه (lesion-to-lesion)
3. Ruler سفارشی بین هر دو نقطه دلخواه
"""

from typing import Dict

from .correlator import compute_3d_cursor, ViewData
from .visualization import (
    draw_3d_cursor_results,
    draw_rulers_for_results,
    draw_lesion_to_lesion_rulers,
    draw_custom_ruler,
)


def example_1_default_rulers(
    views_by_key: Dict[str, ViewData],
    boxes_by_key: Dict[str, list],
):
    """
    مثال 1: استفاده از ruler پیش‌فرض (nipple به lesion)
    
    این همان ruler قبلی است که فاصله از نوک پستان تا مرکز هر ضایعه را نشان می‌دهد.
    """
    # محاسبه نتایج 3D cursor
    result = compute_3d_cursor(views_by_key, boxes_by_key)
    
    # رسم نتایج شامل ruler های پیش‌فرض
    draw_3d_cursor_results(
        result=result,
        views_by_key=views_by_key,
        draw_rulers=True,  # ruler های آبی رنگ از nipple به lesion
    )
    
    print("✓ Ruler های پیش‌فرض (nipple → lesion) رسم شدند")
    print("  - رنگ: آبی")
    print("  - خط: چین‌دار (dashed)")
    print("  - نشانگر: دایره در دو سر")


def example_2_lesion_to_lesion_rulers(
    views_by_key: Dict[str, ViewData],
    boxes_by_key: Dict[str, list],
):
    """
    مثال 2: استفاده از ruler بین دو ضایعه
    
    این ruler جدید فاصله بین دو ضایعه مختلف در یک تصویر را نشان می‌دهد.
    مفید برای:
        - مقایسه اندازه و موقعیت چندین یافته
        - ارزیابی توزیع ضایعات
        - تعیین فاصله بین توده‌های متعدد
    """
    # محاسبه نتایج 3D cursor
    result = compute_3d_cursor(views_by_key, boxes_by_key)
    
    # رسم ruler های بین ضایعات
    draw_lesion_to_lesion_rulers(
        result=result,
        views_by_key=views_by_key,
        draw_on_paired=True,      # رسم برای ضایعات paired
        draw_on_projected=False,  # عدم رسم برای ضایعات projected
    )
    
    print("✓ Ruler های lesion-to-lesion رسم شدند")
    print("  - رنگ: نارنجی")
    print("  - خط: ممتد (solid)")
    print("  - نشانگر: الماس در دو سر")
    print("  - برچسب: فاصله با سمبل ↔")


def example_3_custom_measurement(
    vtk_widget,
    pixel_spacing,
):
    """
    مثال 3: اندازه‌گیری سفارشی بین دو نقطه دلخواه
    
    این تابع امکان اندازه‌گیری فاصله بین هر دو نقطه را می‌دهد.
    کاربردها:
        - اندازه‌گیری قطر یک ضایعه
        - فاصله از لبه پستان
        - هر اندازه‌گیری دلخواه دیگر
    """
    # مثال: اندازه‌گیری بین دو نقطه
    point_A = (150, 200)  # مختصات پیکسلی نقطه A
    point_B = (300, 450)  # مختصات پیکسلی نقطه B
    
    distance = draw_custom_ruler(
        vtk_widget=vtk_widget,
        point1_px=point_A,
        point2_px=point_B,
        pixel_spacing=pixel_spacing,
        label="اندازه‌گیری سفارشی",
        color=(0.0, 1.0, 0.0),  # سبز
        line_width=3.0,
    )
    
    print(f"✓ Ruler سفارشی رسم شد")
    print(f"  - فاصله اندازه‌گیری شده: {distance:.1f} mm")
    print(f"  - رنگ: سبز (قابل تغییر)")
    print(f"  - نشانگر: کره در دو سر")
    
    return distance


def example_4_multiple_measurements(
    vtk_widget,
    pixel_spacing,
    lesion_centers: list,  # [(x1, y1), (x2, y2), (x3, y3), ...]
):
    """
    مثال 4: اندازه‌گیری‌های متعدد با رنگ‌های مختلف
    
    نشان می‌دهد چگونه می‌توان چندین ruler با رنگ‌های مختلف رسم کرد.
    """
    colors = [
        (1.0, 0.0, 0.0),  # قرمز
        (0.0, 1.0, 0.0),  # سبز
        (0.0, 0.0, 1.0),  # آبی
        (1.0, 1.0, 0.0),  # زرد
        (1.0, 0.0, 1.0),  # ارغوانی
    ]
    
    measurements = []
    
    # رسم ruler بین هر دو ضایعه متوالی
    for i in range(len(lesion_centers) - 1):
        color = colors[i % len(colors)]
        
        distance = draw_custom_ruler(
            vtk_widget=vtk_widget,
            point1_px=lesion_centers[i],
            point2_px=lesion_centers[i + 1],
            pixel_spacing=pixel_spacing,
            label=f"اندازه‌گیری {i+1}",
            color=color,
            line_width=2.5,
        )
        
        measurements.append(distance)
    
    print(f"✓ {len(measurements)} ruler رسم شد")
    print(f"  - فاصله کل: {sum(measurements):.1f} mm")
    print(f"  - میانگین: {sum(measurements)/len(measurements):.1f} mm")
    
    return measurements


def example_5_comprehensive_visualization(
    views_by_key: Dict[str, ViewData],
    boxes_by_key: Dict[str, list],
):
    """
    مثال 5: نمایش جامع با همه انواع ruler
    
    ترکیب همه ruler ها برای تجزیه و تحلیل کامل:
        - Ruler های nipple-to-lesion (آبی)
        - Ruler های lesion-to-lesion (نارنجی)
        - Arc های correspondence (سیان)
    """
    # محاسبه نتایج
    result = compute_3d_cursor(views_by_key, boxes_by_key)
    
    # 1. رسم نتایج پایه (box ها و cursor ها)
    draw_3d_cursor_results(
        result=result,
        views_by_key=views_by_key,
        draw_rulers=False,  # فعلاً ruler نمی‌زنیم
    )
    
    # 2. رسم ruler های nipple-to-lesion
    draw_rulers_for_results(
        result=result,
        views_by_key=views_by_key,
    )
    
    # 3. رسم ruler های lesion-to-lesion
    draw_lesion_to_lesion_rulers(
        result=result,
        views_by_key=views_by_key,
        draw_on_paired=True,
        draw_on_projected=True,  # شامل projected ها هم
    )
    
    print("✓ نمایش جامع کامل شد")
    print("  - Ruler های آبی: فاصله از nipple")
    print("  - Ruler های نارنجی: فاصله بین ضایعات")
    print("  - Arc های correspondence: محدوده تطابق")


# ═══════════════════════════════════════════════════════════════════════════
# راهنمای سریع استفاده
# ═══════════════════════════════════════════════════════════════════════════

"""
╔════════════════════════════════════════════════════════════════════════════╗
║                    راهنمای سریع استفاده از Ruler ها                      ║
╚════════════════════════════════════════════════════════════════════════════╝

┌─ نوع 1: Ruler پیش‌فرض (Nipple → Lesion) ─────────────────────────────────┐
│                                                                            │
│  draw_rulers_for_results(result, views_by_key)                            │
│                                                                            │
│  ویژگی‌ها:                                                                │
│    • رنگ: آبی (0.0, 0.6, 1.0)                                             │
│    • خط: چین‌دار (dashed)                                                 │
│    • نشانگر: دایره کوچک                                                   │
│    • برچسب: "CC: 45.2 mm" یا "MLO: 45.2 mm"                              │
│                                                                            │
└────────────────────────────────────────────────────────────────────────────┘

┌─ نوع 2: Ruler بین ضایعات (Lesion ↔ Lesion) ──────────────────────────────┐
│                                                                            │
│  draw_lesion_to_lesion_rulers(                                             │
│      result=result,                                                        │
│      views_by_key=views_by_key,                                            │
│      draw_on_paired=True,                                                  │
│      draw_on_projected=False,                                              │
│  )                                                                         │
│                                                                            │
│  ویژگی‌ها:                                                                │
│    • رنگ: نارنجی (1.0, 0.6, 0.0)                                          │
│    • خط: ممتد (solid)                                                     │
│    • نشانگر: الماس (cone با 4 ضلع)                                        │
│    • برچسب: "CC ↔ 32.5 mm"                                                │
│                                                                            │
└────────────────────────────────────────────────────────────────────────────┘

┌─ نوع 3: Ruler سفارشی (Custom Measurement) ────────────────────────────────┐
│                                                                            │
│  distance = draw_custom_ruler(                                             │
│      vtk_widget=widget,                                                    │
│      point1_px=(100, 200),                                                 │
│      point2_px=(300, 400),                                                 │
│      pixel_spacing=geometry.image.pixel_spacing,                           │
│      label="اندازه‌گیری خاص",                                             │
│      color=(0.0, 1.0, 0.0),  # سبز                                        │
│      line_width=3.0,                                                       │
│  )                                                                         │
│                                                                            │
│  ویژگی‌ها:                                                                │
│    • رنگ: قابل تنظیم (پیش‌فرض نارنجی)                                     │
│    • خط: ممتد                                                             │
│    • نشانگر: کره                                                          │
│    • برچسب: قابل تنظیم + فاصله                                            │
│    • برگشت: مقدار فاصله به میلی‌متر                                       │
│                                                                            │
└────────────────────────────────────────────────────────────────────────────┘

════════════════════════════════════════════════════════════════════════════

📌 نکات مهم:

1. تمام ruler ها از VTK actor استفاده می‌کنند
2. مختصات پیکسلی به world coordinates تبدیل می‌شوند
3. فاصله‌ها با استفاده از pixel spacing به mm تبدیل می‌شوند
4. همه actor ها در _projected_actors ذخیره می‌شوند برای پاکسازی
5. text labels از vtkFollower استفاده می‌کنند (همیشه رو به دوربین)

════════════════════════════════════════════════════════════════════════════

🎨 پالت رنگ:

COLOR_RULER           = (0.0, 0.6, 1.0)   # آبی روشن - nipple ruler
COLOR_RULER_TEXT      = (0.8, 0.95, 1.0)  # آبی خیلی روشن - text
COLOR_LESION_RULER    = (1.0, 0.6, 0.0)   # نارنجی - lesion ruler
COLOR_LESION_RULER_TEXT = (1.0, 0.9, 0.6) # نارنجی روشن - text

برای ruler سفارشی می‌توانید هر رنگی را با tuple (R, G, B) تعیین کنید.

════════════════════════════════════════════════════════════════════════════
"""
