"""
اسکریپت تبدیل فایل‌های DICOM به فرمت MHD
"""

import SimpleITK as sitk
import os
import sys

def convert_dicom_to_mhd(dicom_directory, output_filename):
    """
    تبدیل یک سری فایل DICOM به فرمت MHD
    
    Parameters:
    -----------
    dicom_directory : str
        مسیر پوشه حاوی فایل‌های DICOM
    output_filename : str
        نام فایل خروجی (بدون پسوند، مثلاً 'output')
    """
    
    print(f"در حال خواندن فایل‌های DICOM از: {dicom_directory}")
    
    # خواندن سری DICOM
    reader = sitk.ImageSeriesReader()
    dicom_names = reader.GetGDCMSeriesFileNames(dicom_directory)
    
    if len(dicom_names) == 0:
        print("❌ خطا: هیچ فایل DICOM در این پوشه پیدا نشد!")
        return False
    
    print(f"✅ تعداد {len(dicom_names)} فایل DICOM پیدا شد")
    
    reader.SetFileNames(dicom_names)
    image = reader.Execute()
    
    # ذخیره به فرمت MHD
    output_path = f"{output_filename}.mhd"
    sitk.WriteImage(image, output_path)
    
    print(f"✅ تبدیل با موفقیت انجام شد!")
    print(f"   فایل خروجی: {output_path}")
    print(f"   اندازه تصویر: {image.GetSize()}")
    print(f"   فاصله پیکسل‌ها: {image.GetSpacing()}")
    
    return True

def convert_single_dicom_to_mhd(dicom_file, output_filename):
    """
    تبدیل یک فایل DICOM به فرمت MHD
    
    Parameters:
    -----------
    dicom_file : str
        مسیر فایل DICOM
    output_filename : str
        نام فایل خروجی (بدون پسوند)
    """
    
    print(f"در حال خواندن فایل DICOM: {dicom_file}")
    
    # خواندن فایل DICOM
    image = sitk.ReadImage(dicom_file)
    
    # ذخیره به فرمت MHD
    output_path = f"{output_filename}.mhd"
    sitk.WriteImage(image, output_path)
    
    print(f"✅ تبدیل با موفقیت انجام شد!")
    print(f"   فایل خروجی: {output_path}")
    print(f"   اندازه تصویر: {image.GetSize()}")
    
    return True

if __name__ == "__main__":
    print("=" * 60)
    print("🔄 ابزار تبدیل DICOM به MHD")
    print("=" * 60)
    print()
    
    # نمونه استفاده
    print("نحوه استفاده:")
    print("-" * 60)
    print("برای تبدیل یک پوشه DICOM:")
    print("  python convert_dicom_to_mhd.py <dicom_folder> <output_name>")
    print()
    print("برای تبدیل یک فایل DICOM:")
    print("  python convert_dicom_to_mhd.py <dicom_file.dcm> <output_name>")
    print("-" * 60)
    print()
    
    # بررسی آرگومان‌های ورودی
    if len(sys.argv) < 3:
        print("⚠️ لطفاً مسیر فایل/پوشه DICOM و نام خروجی را مشخص کنید")
        print()
        
        # حالت تعاملی
        dicom_path = input("📁 مسیر پوشه یا فایل DICOM را وارد کنید: ").strip().strip('"')
        output_name = input("📝 نام فایل خروجی را وارد کنید (بدون پسوند): ").strip()
    else:
        dicom_path = sys.argv[1]
        output_name = sys.argv[2]
    
    # بررسی مسیر ورودی
    if not os.path.exists(dicom_path):
        print(f"❌ خطا: مسیر '{dicom_path}' یافت نشد!")
        sys.exit(1)
    
    # تبدیل بسته به نوع ورودی
    try:
        if os.path.isdir(dicom_path):
            convert_dicom_to_mhd(dicom_path, output_name)
        else:
            convert_single_dicom_to_mhd(dicom_path, output_name)
    except Exception as e:
        print(f"❌ خطا در تبدیل: {str(e)}")
        sys.exit(1)

