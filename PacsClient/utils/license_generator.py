"""
License Generator Tool
ابزار تولید لایسنس برای مدیران سیستم
"""
import sys
from license_manager import LicenseManager


def main():
    """تولید کلید لایسنس برای یک سریال سیستم"""
    print("=" * 60)
    print("    ابزار تولید لایسنس AIPacs")
    print("=" * 60)
    print()
    
    manager = LicenseManager()
    
    # دریافت سریال سیستم از کاربر
    print("لطفاً سریال سیستم را وارد کنید:")
    print("(فرمت: ABCD-EFGH-IJKL-MNOP-QRST-UVWX-YZ12-3456)")
    hardware_id = input("> ").strip().replace('-', '').upper()
    
    if len(hardware_id) != 32:
        print("خطا: سریال سیستم باید 32 کاراکتر باشد!")
        return
    
    # دریافت تعداد روزهای اعتبار
    print("\nتعداد روزهای اعتبار لایسنس را وارد کنید:")
    print("(پیش‌فرض: 365 روز)")
    days_input = input("> ").strip()
    
    try:
        days = int(days_input) if days_input else 365
    except ValueError:
        print("خطا: تعداد روزها باید عدد باشد!")
        return
    
    # تولید لایسنس
    print("\nدر حال تولید لایسنس...")
    license_key = manager.generate_license_key(hardware_id, days)
    formatted_key = manager.format_license_key(license_key)
    
    print("\n" + "=" * 60)
    print("    لایسنس با موفقیت تولید شد")
    print("=" * 60)
    print(f"\nسریال سیستم: {manager.format_hardware_id(hardware_id)}")
    print(f"اعتبار: {days} روز")
    print(f"\nکلید لایسنس:\n{formatted_key}")
    print("\n" + "=" * 60)
    
    # اعتبارسنجی
    print("\nدر حال اعتبارسنجی...")
    is_valid, message = manager.validate_license(license_key, hardware_id)
    
    if is_valid:
        print(f"✓ {message}")
    else:
        print(f"✗ خطا: {message}")


if __name__ == "__main__":
    main()
