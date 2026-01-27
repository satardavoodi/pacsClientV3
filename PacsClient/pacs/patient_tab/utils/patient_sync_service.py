"""
Patient Data Synchronization Service
=====================================
این سرویس همه داده‌های بیمار (attachments، audio، و غیره) را با سرور همگام‌سازی می‌کند
و report status را روی "منتظر تایید منشی" قرار می‌دهد.
"""

import os
from pathlib import Path
from typing import Dict, Any, Optional, List
import threading
from PySide6.QtCore import QObject, Signal

from PacsClient.utils.upload_download_attchments import upload_attachments_for_study
from PacsClient.utils.db_manager import get_attachments_uploaded


class PatientSyncService(QObject):
    """
    سرویس همگام‌سازی داده‌های بیمار با سرور
    """
    
    # Signals
    sync_started = Signal(str)  # study_uid
    sync_progress = Signal(str, int, int)  # study_uid, current, total
    sync_completed = Signal(str, dict)  # study_uid, result
    sync_failed = Signal(str, str)  # study_uid, error_message
    
    def __init__(self):
        super().__init__()
        self._sync_threads = {}  # Keep track of running sync threads
    
    def sync_patient_data(
        self, 
        study_uid: str,
        attachment_folder_path: Optional[str] = None,
        verbose: bool = True
    ):
        """
        همگام‌سازی تمام داده‌های بیمار با سرور
        
        Args:
            study_uid: UID مطالعه
            attachment_folder_path: مسیر پوشه attachments (اگر None باشد از ATTACHMENT_PATH استفاده می‌شود)
            verbose: نمایش لاگ‌ها
        """
        # Emit sync started
        self.sync_started.emit(study_uid)
        
        # Run sync in background thread to avoid blocking UI
        thread = threading.Thread(
            target=self._sync_worker,
            args=(study_uid, attachment_folder_path, verbose),
            daemon=True
        )
        self._sync_threads[study_uid] = thread
        thread.start()
    
    def _sync_worker(
        self,
        study_uid: str,
        attachment_folder_path: Optional[str],
        verbose: bool
    ):
        """
        Worker thread برای همگام‌سازی (اجرا در background)
        """
        try:
            result = {
                "study_uid": study_uid,
                "attachments_uploaded": 0,
                "attachments_failed": 0,
                "status_updated": False,
                "errors": []
            }
            
            attachment_files = self._find_attachment_files(study_uid, attachment_folder_path)
            
            if attachment_files:
                # دریافت لیست فایل‌های آپلود‌شده
                uploaded_files_str = get_attachments_uploaded(study_uid)
                
                # ✅ تعداد کل فایل‌های پیدا شده
                total_files = len(attachment_files)
                
                if verbose:
                    print(f"[SYNC] Found {total_files} attachment files for study {study_uid}")
                    print(f"[SYNC] Already uploaded: {uploaded_files_str}")
                
                # آپلود همه فایل‌ها یکجا (تابع upload_attachments_for_study خودش فیلتر می‌کند)
                try:
                    self.sync_progress.emit(study_uid, 0, total_files)
                    
                    upload_result = upload_attachments_for_study(
                        study_uid=study_uid,
                        attachments_uploaded=uploaded_files_str,  # ✅ لیست فایل‌های آپلود‌شده
                        verbose=verbose
                    )
                    
                    if verbose:
                        print(f"[SYNC] Upload result: {upload_result}")
                    
                    if upload_result:
                        result['attachments_uploaded'] = upload_result.get('success', 0)
                        result['attachments_failed'] = upload_result.get('failed', 0)
                        
                        # ✅ بررسی خطاها
                        for item in upload_result.get('results', []):
                            if item.get('status') == 'error':
                                result['errors'].append(
                                    f"Failed to upload {Path(item['file']).name}: {item.get('error', 'Unknown error')}"
                                )
                    
                    # ✅ گزارش پیشرفت کامل
                    self.sync_progress.emit(study_uid, total_files, total_files)
                    
                except Exception as e:
                    result['attachments_failed'] = total_files
                    result['errors'].append(f"Error uploading attachments: {str(e)}")
            
            # Update report status
            try:
                from PacsClient.components.socket_report_status_service import get_report_status_service
                report_service = get_report_status_service()
                status_response = report_service.update_report_status(
                    study_uid=study_uid,
                    new_status="awaiting_secretary_approval",
                    user_id=None,
                    comment="Auto-synced by client"
                )
                if status_response:
                    result['status_updated'] = True
                else:
                    result['errors'].append("Failed to update report status")
            except Exception as e:
                result['errors'].append(f"Error updating report status: {str(e)}")
            
            # Re-sync local attachments with server
            if result['attachments_uploaded'] > 0:
                try:
                    from PacsClient.utils.config import ATTACHMENT_PATH
                    from PacsClient.utils import download_attachments_for_study
                    import shutil
                    
                    local_attachment_path = ATTACHMENT_PATH / study_uid
                    if local_attachment_path.exists():
                        shutil.rmtree(local_attachment_path)
                    download_attachments_for_study(study_uid, verbose=False)
                except Exception:
                    pass
            
            self.sync_completed.emit(study_uid, result)
            
        except Exception as e:
            self.sync_failed.emit(study_uid, f"Sync failed: {str(e)}")
        
        finally:
            # Clean up thread reference
            if study_uid in self._sync_threads:
                del self._sync_threads[study_uid]
    
    def _find_attachment_files(
        self,
        study_uid: str,
        attachment_folder_path: Optional[str] = None
    ) -> List[str]:
        """
        پیدا کردن تمام فایل‌های attachment برای یک study
        
        Args:
            study_uid: UID مطالعه
            attachment_folder_path: مسیر پوشه attachments (اگر None باشد از ATTACHMENT_PATH استفاده می‌شود)
        
        Returns:
            لیست مسیرهای فایل‌های attachment
        """
        from PacsClient.utils.config import ATTACHMENT_PATH
        
        if attachment_folder_path is None:
            # Use default attachment path
            attachment_folder_path = ATTACHMENT_PATH / study_uid
        else:
            attachment_folder_path = Path(attachment_folder_path)
        
        # Check if folder exists
        if not attachment_folder_path.exists() or not attachment_folder_path.is_dir():
            return []
        
        # Find all files (excluding hidden files and system files)
        attachment_files = []
        for file_path in attachment_folder_path.rglob('*'):
            if file_path.is_file() and not file_path.name.startswith('.'):
                attachment_files.append(str(file_path))
        
        return attachment_files


# Singleton instance
_sync_service_instance = None


def get_patient_sync_service() -> PatientSyncService:
    """
    دریافت instance singleton از PatientSyncService
    
    Returns:
        PatientSyncService instance
    """
    global _sync_service_instance
    if _sync_service_instance is None:
        _sync_service_instance = PatientSyncService()
    return _sync_service_instance

