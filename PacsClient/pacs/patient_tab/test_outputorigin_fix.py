"""
تست اصلاح OutputOrigin برای Curved MPR

این تست تأیید می‌کند که اصلاح OutputOrigin صحیح است.
"""

import numpy as np
import vtk
import sys
import os

# اضافه کردن مسیر به path
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(current_dir, 'viewers'))

from curved_mpr import CurvedMPRGenerator


def create_sphere_volume(center=(50, 50, 50), radius=20):
    """ساخت volume تست با یک sphere"""
    dims = (100, 100, 100)
    image_data = vtk.vtkImageData()
    image_data.SetDimensions(dims)
    image_data.SetSpacing(1.0, 1.0, 1.0)
    image_data.SetOrigin(0.0, 0.0, 0.0)
    image_data.AllocateScalars(vtk.VTK_UNSIGNED_SHORT, 1)
    
    scalars = image_data.GetPointData().GetScalars()
    
    # پر کردن با مقدار پایه
    for i in range(scalars.GetNumberOfTuples()):
        scalars.SetTuple1(i, 100)
    
    # ساخت sphere روشن
    for z in range(dims[2]):
        for y in range(dims[1]):
            for x in range(dims[0]):
                pos = np.array([x, y, z])
                dist = np.linalg.norm(pos - np.array(center))
                
                if dist <= radius:
                    idx = z * dims[0] * dims[1] + y * dims[0] + x
                    # مقدار بالاتر برای نقاط نزدیک‌تر به مرکز
                    value = int(3000 * (1.0 - dist / radius))
                    scalars.SetTuple1(idx, max(100, value))
    
    return image_data


def test_proper_3d_path():
    """
    تست 1: مسیر 3D صحیح که از sphere عبور می‌کند
    
    این باید کار کند و تصویر معتبر تولید کند.
    """
    print("\n" + "="*70)
    print("تست 1: مسیر 3D صحیح (با Z متفاوت)")
    print("="*70)
    
    volume = create_sphere_volume(center=(50, 50, 50), radius=20)
    
    # مسیر که از sphere عبور می‌کند، با Z متفاوت
    path_points = [
        (30.0, 40.0, 35.0),   # Z=35
        (40.0, 45.0, 42.0),   # Z=42
        (50.0, 50.0, 50.0),   # Z=50 (مرکز sphere)
        (60.0, 55.0, 58.0),   # Z=58
        (70.0, 60.0, 65.0),   # Z=65
    ]
    
    print("\nنقاط کنترل:")
    for i, pt in enumerate(path_points, 1):
        print(f"  {i}. ({pt[0]:.1f}, {pt[1]:.1f}, {pt[2]:.1f})")
    
    # بررسی محدوده Z
    z_coords = [p[2] for p in path_points]
    z_range = max(z_coords) - min(z_coords)
    print(f"\nمحدوده Z: {z_range:.1f}mm ✓ (خوب)")
    
    # تولید Curved MPR
    generator = CurvedMPRGenerator(volume)
    generator.set_centerline(path_points)
    
    curved_mpr = generator.generate_curved_mpr(
        slice_width=60,
        slice_height=60,
        num_slices=40
    )
    
    # بررسی نتیجه
    dims = curved_mpr.GetDimensions()
    scalar_range = curved_mpr.GetScalarRange()
    
    print(f"\n📊 نتیجه:")
    print(f"  Dimensions: {dims[0]} × {dims[1]} × {dims[2]}")
    print(f"  Scalar Range: [{scalar_range[0]:.0f}, {scalar_range[1]:.0f}]")
    
    # تست موفقیت
    success = scalar_range[1] > 1000  # باید مقادیر روشن sphere را ببیند
    
    if success:
        print(f"\n✅ موفق! CPR حاوی داده معتبر است")
        print(f"   مقدار max = {scalar_range[1]:.0f} (باید ~ 3000 باشد)")
        return True
    else:
        print(f"\n❌ شکست! CPR خالی یا بدون داده است")
        print(f"   مقدار max = {scalar_range[1]:.0f} (خیلی کم!)")
        return False


def test_coplanar_path():
    """
    تست 2: نقاط Coplanar (همه در یک Z)
    
    این احتمالاً شکست می‌خورد یا تصویر ضعیف تولید می‌کند.
    """
    print("\n" + "="*70)
    print("تست 2: نقاط Coplanar (همه Z یکسان) - انتظار مشکل")
    print("="*70)
    
    volume = create_sphere_volume(center=(50, 50, 50), radius=20)
    
    # همه نقاط در Z=50 (صفحه مرکز sphere)
    path_points = [
        (30.0, 40.0, 50.0),   # Z=50
        (40.0, 45.0, 50.0),   # Z=50
        (50.0, 50.0, 50.0),   # Z=50
        (60.0, 55.0, 50.0),   # Z=50
        (70.0, 60.0, 50.0),   # Z=50
    ]
    
    print("\nنقاط کنترل (همه Z=50):")
    for i, pt in enumerate(path_points, 1):
        print(f"  {i}. ({pt[0]:.1f}, {pt[1]:.1f}, {pt[2]:.1f})")
    
    # بررسی محدوده Z
    z_coords = [p[2] for p in path_points]
    z_range = max(z_coords) - min(z_coords)
    print(f"\nمحدوده Z: {z_range:.1f}mm ⚠️ (صفر! مشکلدار)")
    
    # تولید Curved MPR
    generator = CurvedMPRGenerator(volume)
    generator.set_centerline(path_points)
    
    curved_mpr = generator.generate_curved_mpr(
        slice_width=60,
        slice_height=60,
        num_slices=40
    )
    
    # بررسی نتیجه
    dims = curved_mpr.GetDimensions()
    scalar_range = curved_mpr.GetScalarRange()
    
    print(f"\n📊 نتیجه:")
    print(f"  Dimensions: {dims[0]} × {dims[1]} × {dims[2]}")
    print(f"  Scalar Range: [{scalar_range[0]:.0f}, {scalar_range[1]:.0f}]")
    
    # برای نقاط coplanar، انتظار داریم یا خالی باشد یا داده کمی داشته باشد
    has_data = scalar_range[1] > 500
    
    if has_data:
        print(f"\n⚠️ نتیجه غیرمنتظره: با وجود coplanar بودن، داده دارد!")
        print(f"   (این ممکن است برخی slice‌ها را بگیرد)")
    else:
        print(f"\n⚠️ طبق انتظار: CPR خالی یا داده کم است")
        print(f"   → راه‌حل: نقاط را در Z‌های مختلف انتخاب کنید!")
    
    return not has_data  # برای coplanar، انتظار داریم empty باشد


def test_reslice_basic():
    """
    تست 3: تست ساده vtkImageReslice برای اطمینان از درستی VTK
    """
    print("\n" + "="*70)
    print("تست 3: تست پایه vtkImageReslice")
    print("="*70)
    
    volume = create_sphere_volume(center=(50, 50, 50), radius=20)
    
    # یک reslice ساده در صفحه XY در Z=50
    reslice = vtk.vtkImageReslice()
    reslice.SetInputData(volume)
    reslice.SetOutputDimensionality(2)
    reslice.SetInterpolationModeToLinear()
    
    # جهت‌گیری identity (صفحه XY)
    reslice.SetResliceAxesDirectionCosines(
        1, 0, 0,  # X axis
        0, 1, 0,  # Y axis
        0, 0, 1   # Z axis (normal)
    )
    
    # مرکز در (50, 50, 50)
    reslice.SetResliceAxesOrigin(50, 50, 50)
    
    # Extent مرکز-محور
    reslice.SetOutputExtent(-30, 29, -30, 29, 0, 0)
    reslice.SetOutputSpacing(1.0, 1.0, 1.0)
    
    # ✅ اصلاح شده: Origin = (0, 0, 0) نه (-30, -30, 0)
    reslice.SetOutputOrigin(0.0, 0.0, 0.0)
    
    reslice.Update()
    
    output = reslice.GetOutput()
    scalar_range = output.GetScalarRange()
    
    print(f"\n📊 Slice در (50,50,50):")
    print(f"  Range: [{scalar_range[0]:.0f}, {scalar_range[1]:.0f}]")
    
    success = scalar_range[1] > 2000  # باید مرکز sphere را ببیند
    
    if success:
        print(f"\n✅ موفق! Reslice حاوی مرکز sphere است")
        return True
    else:
        print(f"\n❌ شکست! مشکل در reslicing پایه VTK")
        return False


def main():
    """اجرای همه تست‌ها"""
    print("="*70)
    print("🧪 تست اصلاح OutputOrigin برای Curved MPR")
    print("="*70)
    
    results = {}
    
    try:
        results['3D Path'] = test_proper_3d_path()
    except Exception as e:
        print(f"\n❌ خطا در تست 3D Path: {e}")
        results['3D Path'] = False
    
    try:
        results['Coplanar'] = test_coplanar_path()
    except Exception as e:
        print(f"\n❌ خطا در تست Coplanar: {e}")
        results['Coplanar'] = False
    
    try:
        results['Basic Reslice'] = test_reslice_basic()
    except Exception as e:
        print(f"\n❌ خطا در تست Basic Reslice: {e}")
        results['Basic Reslice'] = False
    
    # خلاصه نتایج
    print("\n" + "="*70)
    print("📋 خلاصه نتایج")
    print("="*70)
    
    for test_name, passed in results.items():
        status = "✅ موفق" if passed else "❌ شکست"
        print(f"  {test_name:20s}: {status}")
    
    print("\n" + "="*70)
    
    # نتیجه نهایی
    if results.get('3D Path') and results.get('Basic Reslice'):
        print("✅ اصلاحات درست کار می‌کنند!")
        print("   → CPR با مسیرهای 3D صحیح، تصویر معتبر تولید می‌کند")
        print("   → کاربران باید نقاط را در slice‌های مختلف انتخاب کنند")
    else:
        print("❌ هنوز مشکل وجود دارد!")
        print("   → بررسی دوباره اصلاحات لازم است")
    
    print("="*70)


if __name__ == "__main__":
    main()

