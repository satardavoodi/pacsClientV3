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
    
    # Get system serial from user
    print("Please enter the system serial:")
    print("(Format: ABCD-EFGH-IJKL-MNOP-QRST-UVWX-YZ12-3456)")
    hardware_id = input("> ").strip().replace('-', '').upper()
    
    if len(hardware_id) != 32:
        print("Error: System serial must be 32 characters!")
        return
    
    # دریافت تعداد روزهای اعتبار
    print("\nتعداد روزهای اعتبار لایسنس را وارد کنید:")
    print("(پیش‌فرض: 365 روز)")
    days_input = input("> ").strip()
    
    try:
        days = int(days_input) if days_input else 365
    except ValueError:
        print("Error: Number of days must be a number!")
        return
    
    # Generate license
    print("\nGenerating license...")
    license_key = manager.generate_license_key(hardware_id, days)
    formatted_key = manager.format_license_key(license_key)
    
    print("\n" + "=" * 60)
    print("    License generated successfully")
    print("=" * 60)
    print(f"\nSystem Serial: {manager.format_hardware_id(hardware_id)}")
    print(f"Validity: {days} days")
    print(f"\nLicense Key:\n{formatted_key}")
    print("\n" + "=" * 60)
    
    # Validation
    print("\nValidating...")
    is_valid, message = manager.validate_license(license_key, hardware_id)
    
    if is_valid:
        print(f"✓ {message}")
    else:
        print(f"✗ Error: {message}")


if __name__ == "__main__":
    main()
