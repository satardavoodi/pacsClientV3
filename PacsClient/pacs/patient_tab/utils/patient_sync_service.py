"""
Patient Data Synchronization Service
=====================================
این سرویس همه داده‌های بیمار (attachments، audio، و غیره) را با سرور همگام‌سازی می‌کند
و report status را روی "تایید شده توسط پزشک" (physician_approved) قرار می‌دهد.
"""

import os
import logging
from pathlib import Path
from typing import Dict, Any, Optional, List
import threading
from PySide6.QtCore import QObject, Signal

from modules.network.upload_download_attchments import upload_attachments_for_study
from PacsClient.utils.db_manager import get_attachments_uploaded

logger = logging.getLogger(__name__)


def _list_attachment_files(study_uid: str):
    """[ATTACH-TRACE] Read-only snapshot of the on-disk attachment filenames for
    a study (non-hidden). Used to bracket the sync window so a vanishing
    approved voice can be pinned to the exact step. Returns None on error."""
    try:
        from PacsClient.utils.config import ATTACHMENT_PATH
        d = ATTACHMENT_PATH / study_uid
        return sorted(p.name for p in d.iterdir()
                      if p.is_file() and not p.name.startswith('.'))
    except Exception:
        return None


def reconcile_attachments_from_server(study_uid: str, *, verbose: bool = False) -> Dict[str, Any]:
    """Pull server-side attachments that are missing locally — WITHOUT ever
    deleting local files.

    SAFE replacement for the previous "delete the whole local attachment folder,
    then re-download" reconcile. That approach permanently lost locally-saved
    (and not-yet-uploaded) attachments whenever the re-download failed or the
    batch only partially uploaded. ``download_attachments_for_study`` runs with
    ``overwrite=False`` so existing local files are preserved and only files
    present on the server but absent locally are fetched (bidirectional pull).
    Any failure is logged, never fatal, and never removes local data.
    """
    if not study_uid:
        return {}
    try:
        from modules.network.upload_download_attchments import download_attachments_for_study
        _before = _list_attachment_files(study_uid)
        summary = download_attachments_for_study(study_uid, overwrite=False, verbose=verbose)
        _after = _list_attachment_files(study_uid)
        logger.info(
            "[SYNC] reconcile (non-destructive) study=%s pulled=%s skipped=%s deduped=%s failed=%s before=%s after=%s",
            study_uid, summary.get("saved"), summary.get("skipped"), summary.get("deduped"),
            summary.get("failed"), _before, _after,
        )
        # Defensive audit: a non-destructive reconcile must NEVER reduce the local
        # file set. If after < before, a local-only (e.g. unsynced voice) file was
        # lost here — pin it loudly instead of failing silently.
        if _before and _after is not None and len(_after) < len(_before):
            lost = sorted(set(_before) - set(_after))
            logger.error(
                "[ATTACH-AUDIT] reconcile REDUCED local attachments study=%s lost=%s before=%s after=%s",
                study_uid, lost, _before, _after,
            )
        return summary
    except Exception as exc:
        # Server unreachable / transient error: keep ALL local files intact.
        logger.warning(
            "[SYNC] reconcile skipped for study=%s (local files kept intact): %s",
            study_uid, exc,
        )
        return {}


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
            
            logger.info("[ATTACH-TRACE] sync_start study=%s files=%s",
                        study_uid, _list_attachment_files(study_uid))

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
            
            # Update report status. The workstation user is the reading
            # physician, so a sync marks the report Physician Approved
            # (physician_approved) — NOT secretary_approved (the secretary's
            # own, separate action) and NOT awaiting_secretary_approval. The
            # exact value is the single shared constant SYNC_REPORT_STATUS so
            # this site and the toolbar's post-sync local update never drift.
            try:
                from modules.network.socket_report_status_service import (
                    get_report_status_service, SYNC_REPORT_STATUS,
                )
                report_service = get_report_status_service()
                status_response = report_service.update_report_status(
                    study_uid=study_uid,
                    new_status=SYNC_REPORT_STATUS,
                    user_id=None,
                    comment="Auto-synced by client"
                )
                if status_response:
                    result['status_updated'] = True
                else:
                    result['errors'].append("Failed to update report status")
            except Exception as e:
                result['errors'].append(f"Error updating report status: {str(e)}")
            
            # Bidirectional pull: fetch any server-side attachments that are
            # missing locally. NON-DESTRUCTIVE — local files (including
            # not-yet-synced ones) are never deleted here, so a server hiccup,
            # a partial-batch upload, or a failed re-download can never lose an
            # approved attachment. (The previous implementation deleted the
            # whole local attachment folder and re-downloaded, which lost any
            # file that had not yet reached the server — the root cause of
            # "the attachment is gone after sync".)
            if result['attachments_uploaded'] > 0:
                reconcile_attachments_from_server(study_uid, verbose=verbose)
            
            logger.info("[ATTACH-TRACE] sync_end study=%s files=%s",
                        study_uid, _list_attachment_files(study_uid))

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

