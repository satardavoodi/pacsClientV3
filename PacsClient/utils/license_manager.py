"""
License Manager Module
مدیریت لایسنس و احراز هویت برنامه
"""
import os
import json
import hashlib
import uuid
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, Tuple


class LicenseManager:
    """مدیریت لایسنس برنامه"""
    
    LICENSE_FILE = "license.dat"
    
    def __init__(self):
        """Initialize license manager"""
        self.app_data_dir = self._get_app_data_dir()
        self.license_path = self.app_data_dir / self.LICENSE_FILE
        
    def _get_app_data_dir(self) -> Path:
        """دریافت مسیر ذخیره‌سازی داده‌های برنامه"""
        if os.name == 'nt':  # Windows
            app_data = os.getenv('APPDATA')
            base_dir = Path(app_data) / "AIPacs"
        else:  # Linux/Mac
            home = Path.home()
            base_dir = home / ".aipacs"
        
        # ایجاد پوشه در صورت عدم وجود
        base_dir.mkdir(parents=True, exist_ok=True)
        return base_dir
    
    def get_hardware_id(self) -> str:
        """
        دریافت شناسه سخت‌افزاری سیستم
        این شناسه بر اساس MAC address و مشخصات سیستم ایجاد می‌شود
        """
        try:
            # دریافت MAC address
            mac = uuid.getnode()
            mac_str = ':'.join(('%012X' % mac)[i:i+2] for i in range(0, 12, 2))
            
            # دریافت نام کامپیوتر
            computer_name = os.environ.get('COMPUTERNAME', os.environ.get('HOSTNAME', 'unknown'))
            
            # ترکیب اطلاعات
            hardware_info = f"{mac_str}-{computer_name}"
            
            # ایجاد هش
            hardware_id = hashlib.sha256(hardware_info.encode()).hexdigest()[:32]
            
            return hardware_id.upper()
        except Exception as e:
            print(f"Error getting hardware ID: {e}")
            return "UNKNOWN-HARDWARE-ID"
    
    def format_hardware_id(self, hardware_id: str) -> str:
        """
        فرمت کردن شناسه سخت‌افزاری به فرمت قابل خواندن
        مثال: ABCD-EFGH-IJKL-MNOP-QRST-UVWX-YZ12-3456
        """
        # تقسیم به بخش‌های 4 کاراکتری
        parts = [hardware_id[i:i+4] for i in range(0, len(hardware_id), 4)]
        return '-'.join(parts)
    
    def generate_license_key(self, hardware_id: str, days: int = 365) -> str:
        """
        تولید کلید لایسنس برای یک سخت‌افزار مشخص
        این متد باید فقط توسط سرور یا ابزار مدیریت لایسنس استفاده شود
        
        Args:
            hardware_id: شناسه سخت‌افزاری
            days: تعداد روزهای اعتبار لایسنس
        
        Returns:
            کلید لایسنس
        """
        # تاریخ انقضا
        expiry_date = (datetime.now() + timedelta(days=days)).strftime("%Y%m%d")
        
        # کلید مخفی (این باید در محیط امن نگهداری شود)
        secret_key = "AIPACS-SECRET-KEY-2026-V1"  # در محیط production باید از environment variable استفاده شود
        
        # ایجاد داده برای هش
        data = f"{hardware_id}|{expiry_date}|{secret_key}"
        
        # ایجاد هش
        license_hash = hashlib.sha256(data.encode()).hexdigest()[:24].upper()
        
        # فرمت نهایی: EXPIRY-HASH
        license_key = f"{expiry_date}-{license_hash}"
        
        return license_key
    
    def format_license_key(self, license_key: str) -> str:
        """
        فرمت کردن کلید لایسنس به فرمت قابل خواندن
        مثال: 20261231-ABCD-EFGH-IJKL-MNOP-QRST-UVWX
        """
        if '-' not in license_key:
            return license_key
        
        parts = license_key.split('-', 1)
        if len(parts) != 2:
            return license_key
        
        date_part = parts[0]
        hash_part = parts[1]
        
        # تقسیم hash به بخش‌های 4 کاراکتری
        hash_parts = [hash_part[i:i+4] for i in range(0, len(hash_part), 4)]
        formatted_hash = '-'.join(hash_parts)
        
        return f"{date_part}-{formatted_hash}"
    
    def validate_license(self, license_key: str, hardware_id: Optional[str] = None) -> Tuple[bool, str]:
        """
        Validate license key
        
        Args:
            license_key: License key
            hardware_id: Hardware ID (if None, uses current system)
        
        Returns:
            Tuple[bool, str]: (Is valid?, Message)
        """
        try:
            if hardware_id is None:
                hardware_id = self.get_hardware_id()
            
            # Remove spaces and extra dashes
            license_key = license_key.replace(' ', '').replace('-', '')
            
            # Check format
            if len(license_key) < 32:
                return False, "Invalid license key format"
            
            # Extract parts
            expiry_str = license_key[:8]
            provided_hash = license_key[8:]
            
            # Check expiry date
            try:
                expiry_date = datetime.strptime(expiry_str, "%Y%m%d")
                if datetime.now() > expiry_date:
                    return False, "License has expired"
            except ValueError:
                return False, "Invalid license expiry date"
            
            # Secret key (must match generate_license_key method)
            secret_key = "AIPACS-SECRET-KEY-2026-V1"
            
            # Create hash for comparison
            data = f"{hardware_id}|{expiry_str}|{secret_key}"
            expected_hash = hashlib.sha256(data.encode()).hexdigest()[:24].upper()
            
            # Compare hashes
            if provided_hash.upper() != expected_hash:
                return False, "License key is not valid for this system"
            
            # Calculate remaining days
            days_remaining = (expiry_date - datetime.now()).days
            
            return True, f"License is valid. {days_remaining} days remaining"
            
        except Exception as e:
            return False, f"Error validating license: {str(e)}"
    
    def save_license(self, license_key: str) -> Tuple[bool, str]:
        """
        Save license to file
        
        Args:
            license_key: License key
        
        Returns:
            Tuple[bool, str]: (Success?, Message)
        """
        try:
            # Validate license
            is_valid, message = self.validate_license(license_key)
            if not is_valid:
                return False, message
            
            # Save to file
            license_data = {
                'license_key': license_key,
                'hardware_id': self.get_hardware_id(),
                'activated_date': datetime.now().isoformat(),
            }
            
            with open(self.license_path, 'w', encoding='utf-8') as f:
                json.dump(license_data, f, indent=2)
            
            return True, "License activated successfully"
            
        except Exception as e:
            return False, f"Error saving license: {str(e)}"
    
    def load_license(self) -> Optional[dict]:
        """
        بارگذاری لایسنس از فایل
        
        Returns:
            اطلاعات لایسنس یا None
        """
        try:
            if not self.license_path.exists():
                return None
            
            with open(self.license_path, 'r', encoding='utf-8') as f:
                return json.load(f)
                
        except Exception as e:
            print(f"Error loading license: {e}")
            return None
    
    def check_license(self) -> Tuple[bool, str]:
        """
        Check validity of saved license
        
        Returns:
            Tuple[bool, str]: (Is valid?, Message)
        """
        license_data = self.load_license()
        
        if license_data is None:
            return False, "No license found"
        
        license_key = license_data.get('license_key')
        if not license_key:
            return False, "Invalid license"
        
        # Validate
        return self.validate_license(license_key)
    
    def remove_license(self) -> bool:
        """
        حذف لایسنس
        
        Returns:
            موفق بود؟
        """
        try:
            if self.license_path.exists():
                self.license_path.unlink()
            return True
        except Exception as e:
            print(f"Error removing license: {e}")
            return False
