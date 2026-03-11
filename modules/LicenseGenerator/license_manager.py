"""
License Manager Module
License and authentication management
"""
import os
import json
import hashlib
import uuid
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, Tuple


class LicenseManager:
    """Application license manager"""
    
    LICENSE_FILE = "license.dat"
    
    def __init__(self):
        """Initialize license manager"""
        self.app_data_dir = self._get_app_data_dir()
        self.license_path = self.app_data_dir / self.LICENSE_FILE
        
    def _get_app_data_dir(self) -> Path:
        """Get application data storage path"""
        if os.name == 'nt':  # Windows
            app_data = os.getenv('APPDATA')
            base_dir = Path(app_data) / "AIPacs"
        else:  # Linux/Mac
            home = Path.home()
            base_dir = home / ".aipacs"
        
        # Create folder if it doesn't exist
        base_dir.mkdir(parents=True, exist_ok=True)
        return base_dir
    
    def get_hardware_id(self) -> str:
        """
        Get system hardware ID
        This ID is based on MAC address and system specifications
        """
        try:
            # Get MAC address
            mac = uuid.getnode()
            mac_str = ':'.join(('%012X' % mac)[i:i+2] for i in range(0, 12, 2))
            
            # Get computer name
            computer_name = os.environ.get('COMPUTERNAME', os.environ.get('HOSTNAME', 'unknown'))
            
            # Combine information
            hardware_info = f"{mac_str}-{computer_name}"
            
            # Create hash
            hardware_id = hashlib.sha256(hardware_info.encode()).hexdigest()[:32]
            
            return hardware_id.upper()
        except Exception as e:
            print(f"Error getting hardware ID: {e}")
            return "UNKNOWN-HARDWARE-ID"
    
    def format_hardware_id(self, hardware_id: str) -> str:
        """
        Format hardware ID to readable format
        Example: ABCD-EFGH-IJKL-MNOP-QRST-UVWX-YZ12-3456
        """
        # Split into 4-character parts
        parts = [hardware_id[i:i+4] for i in range(0, len(hardware_id), 4)]
        return '-'.join(parts)
    
    def generate_license_key(self, hardware_id: str, days: int = 365) -> str:
        """
        Generate license key for specific hardware
        This method should only be used by server or license management tool
        
        Args:
            hardware_id: Hardware ID
            days: Number of days license is valid
        
        Returns:
            License key
        """
        # Expiry date
        expiry_date = (datetime.now() + timedelta(days=days)).strftime("%Y%m%d")
        
        # Secret key (should be kept in secure environment)
        secret_key = "AIPACS-SECRET-KEY-2026-V1"  # In production, use environment variable
        
        # Create data for hash
        data = f"{hardware_id}|{expiry_date}|{secret_key}"
        
        # Create hash
        license_hash = hashlib.sha256(data.encode()).hexdigest()[:24].upper()
        
        # Final format: EXPIRY-HASH
        license_key = f"{expiry_date}-{license_hash}"
        
        return license_key
    
    def format_license_key(self, license_key: str) -> str:
        """
        Format license key to readable format
        Example: 20261231-ABCD-EFGH-IJKL-MNOP-QRST-UVWX
        """
        if '-' not in license_key:
            return license_key
        
        parts = license_key.split('-', 1)
        if len(parts) != 2:
            return license_key
        
        date_part = parts[0]
        hash_part = parts[1]
        
        # Split hash into 4-character parts
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
        Validate and save a license key to disk.

        Args:
            license_key: The license key to store.

        Returns:
            Tuple[bool, str]: (success?, message)
        """
        is_valid, message = self.validate_license(license_key)
        if not is_valid:
            return False, message

        try:
            data = {
                "license_key": license_key.replace(' ', '').replace('-', ''),
                "hardware_id": self.get_hardware_id(),
                "activated_at": datetime.now().isoformat(),
            }
            self.license_path.write_text(json.dumps(data), encoding="utf-8")
            return True, message
        except Exception as e:
            return False, f"Error saving license: {str(e)}"

    def check_license(self) -> Tuple[bool, str]:
        """
        Load the stored license from disk and validate it.

        Returns:
            Tuple[bool, str]: (is_valid?, message)
        """
        if not self.license_path.exists():
            return False, "No license found. Please activate."

        try:
            data = json.loads(self.license_path.read_text(encoding="utf-8"))
            license_key = data.get("license_key", "")
            if not license_key:
                return False, "Invalid license file"
            return self.validate_license(license_key)
        except (json.JSONDecodeError, KeyError):
            return False, "Corrupt license file"
        except Exception as e:
            return False, f"Error checking license: {str(e)}"
