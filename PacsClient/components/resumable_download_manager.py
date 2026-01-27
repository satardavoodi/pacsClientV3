#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Resumable Download Manager for PACS Client
مدیر دانلود قابل ادامه برای کلاینت PACS

این ماژول دانلود منیجر resumable را با ساختار نرم‌افزار (سورس، سری، انستنس و دیتابیس) ادغام می‌کند.
"""

import os
import sys
import json
import base64
import gzip
import time
import logging
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, Any, Callable, List
from PySide6.QtCore import QObject, Signal, QTimer, QThread
from PySide6.QtWidgets import QMessageBox, QProgressDialog

# Add the PacsClient directory to the Python path
current_dir = Path(__file__).parent
pacs_client_dir = current_dir.parent
if str(pacs_client_dir) not in sys.path:
    sys.path.insert(0, str(pacs_client_dir))

from PacsClient.utils.database import (
    insert_patient, insert_study, insert_series, insert_instance,
    find_patient_pk, find_study_pk, find_series_pk, find_instance_pk
)
from PacsClient.pacs.patient_tab.utils.utils import check_series_study_exist
from PacsClient.utils.config import SOURCE_PATH, THUMBNAIL_PATH
from PacsClient.utils.socket_config import get_socket_config
from .resumable_dicom_socket_client import ResumableDicomSocketClient

logger = logging.getLogger(__name__)

class ResumableDownloadManager(QObject):
    """
    دانلود منیجر resumable با ادغام کامل با ساختار نرم‌افزار
    """
    
    # سیگنال‌های Qt
    download_started = Signal(str)  # study_uid
    download_progress = Signal(str, int, int)  # study_uid, current, total
    download_series_progress = Signal(str, int, int, int)  # study_uid, series_number, current, total
    download_completed = Signal(str, bool)  # study_uid, success
    download_error = Signal(str, str)  # study_uid, error_message
    download_paused = Signal(str)  # study_uid
    download_resumed = Signal(str)  # study_uid
    
    def __init__(self, host: str = None, port: int = None):
        super().__init__()
        config = get_socket_config()
        self.host = host if host is not None else config.get_socket_host()
        self.port = port if port is not None else config.get_socket_port()
        self.client = None
        self.socket_service = None  # Will use socket service instead of direct client
        self.active_downloads = {}  # study_uid -> download_info
        self.progress_callbacks = {}  # study_uid -> callback
        self._is_connected = False  # Track connection status
        
        # Initialize socket service
        self._init_socket_service()
    
    def _init_socket_service(self):
        """Initialize socket service for downloads"""
        try:
            logger.info("🔧 Initializing socket service for download manager")
            from ..components.socket_service import get_socket_service
            self.socket_service = get_socket_service()
            
            # Update socket service configuration if needed
            config = get_socket_config()
            default_host = config.get_socket_host()
            default_port = config.get_socket_port()
            if self.host != default_host or self.port != default_port:
                logger.info(f"🔄 Updating socket service config: {self.host}:{self.port}")
                self.socket_service.update_server(self.host, self.port, save_to_file=False)
            
            logger.info("✅ Socket service initialized for download manager")
        except Exception as e:
            logger.error(f"❌ Failed to initialize socket service: {e}")
            self.socket_service = None
        
    def connect_to_server(self) -> bool:
        """اتصال به سرور"""
        # Return True if already connected
        if self._is_connected:
            logger.debug("🔗 Already connected to server")
            return True
            
        try:
            # Try socket service first
            if self.socket_service:
                if self.socket_service.is_connected() or self.socket_service.connect():
                    logger.info(f"✅ Connected to server via socket service at {self.host}:{self.port}")
                    self._is_connected = True
                    return True
                else:
                    logger.warning("⚠️ Socket service connection failed, falling back to direct client")
            
            # Fallback to direct client
            if not self.client:
                self.client = ResumableDicomSocketClient(host=self.host, port=self.port)
            
            if self.client.is_connected() or self.client.connect():
                logger.info(f"✅ Connected to server via direct client at {self.host}:{self.port}")
                self._is_connected = True
                return True
            else:
                logger.error(f"❌ Failed to connect to server at {self.host}:{self.port}")
                self._is_connected = False
                return False
        except Exception as e:
            logger.error(f"❌ Connection error: {e}")
            self._is_connected = False
            return False
    
    def disconnect_from_server(self):
        """قطع اتصال از سرور"""
        try:
            if self.socket_service:
                self.socket_service.disconnect()
            if self.client:
                self.client.disconnect()
                self.client = None
            self._is_connected = False
            logger.info("🔌 Disconnected from server")
        except Exception as e:
            logger.error(f"❌ Disconnect error: {e}")
            self._is_connected = False
    
    def is_connected(self) -> bool:
        """Check if connected to server"""
        if not self._is_connected:
            return False
        
        # Double check with actual services
        if self.socket_service:
            return self.socket_service.is_connected()
        elif self.client:
            return self.client.is_connected()
        
        return False
    
    def get_progress_file_path(self, study_uid: str) -> Path:
        """مسیر فایل پیشرفت"""
        progress_dir = SOURCE_PATH / ".progress"
        progress_dir.mkdir(parents=True, exist_ok=True)
        return progress_dir / f"{study_uid}_progress.json"
    
    def save_progress(self, study_uid: str, progress_data: Dict[str, Any]):
        """ذخیره پیشرفت دانلود"""
        progress_file = self.get_progress_file_path(study_uid)
        try:
            with open(progress_file, 'w', encoding='utf-8') as f:
                json.dump(progress_data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"⚠️ Failed to save progress: {e}")
    
    def load_progress(self, study_uid: str) -> Optional[Dict[str, Any]]:
        """بارگذاری پیشرفت دانلود"""
        progress_file = self.get_progress_file_path(study_uid)
        if progress_file.exists():
            try:
                with open(progress_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"⚠️ Failed to load progress: {e}")
        return None
    
    def clear_progress(self, study_uid: str):
        """پاک کردن فایل پیشرفت"""
        progress_file = self.get_progress_file_path(study_uid)
        if progress_file.exists():
            try:
                progress_file.unlink()
                logger.info(f"🗑️ Progress file cleared: {progress_file}")
            except Exception as e:
                logger.error(f"⚠️ Failed to clear progress: {e}")
    
    def get_downloaded_instances(self, study_uid: str) -> set:
        """دریافت لیست instance های دانلود شده"""
        downloaded_instances = set()
        study_dir = SOURCE_PATH / study_uid
        
        if study_dir.exists():
            for series_dir in study_dir.iterdir():
                if series_dir.is_dir():
                    for file_path in series_dir.glob("*.dcm"):
                        # استخراج instance number از نام فایل
                        filename = file_path.name
                        if filename.startswith("Instance_") and filename.endswith(".dcm"):
                            try:
                                instance_num = int(filename.replace("Instance_", "").replace(".dcm", ""))
                                downloaded_instances.add(instance_num)
                            except ValueError:
                                continue
        return downloaded_instances
    
    def download_study_resumable(self, study_uid: str, batch_size: int = 5, 
                               compression: str = "gzip", resume: bool = True,
                               progress_callback: Optional[Callable] = None) -> bool:
        """
        دانلود study با قابلیت resume و ادغام کامل با دیتابیس
        """
        # Check if already connected, if not try to connect
        if not self.is_connected():
            logger.info("🔗 Not connected, attempting to connect...")
            if not self.connect_to_server():
                self.download_error.emit(study_uid, "Failed to connect to server")
                return False
        else:
            logger.debug("🔗 Using existing connection")
        
        logger.info(f"🔄 Starting resumable download for study: {study_uid}")
        logger.info(f"   Batch size: {batch_size}")
        logger.info(f"   Compression: {compression}")
        logger.info(f"   Resume: {resume}")
        logger.info(f"   Progress callback: {progress_callback is not None}")
        self.download_started.emit(study_uid)
        
        try:
            # Use socket service if available, otherwise fallback to direct client
            if self.socket_service:
                logger.info(f"🔌 Using socket service for download")
                # Use SOURCE_PATH structure instead of downloads
                download_dir = SOURCE_PATH / study_uid
                download_dir.mkdir(parents=True, exist_ok=True)
                logger.info(f"📁 Using SOURCE_PATH directory: {download_dir}")
                
                success = self.socket_service.download_study_resumable(
                    study_uid=study_uid,
                    output_dir=str(download_dir),
                    batch_size=batch_size,
                    compression=compression,
                    resume=resume,
                    progress_callback=progress_callback
                )
                
                logger.info(f"🔍 Socket service download result: {success}")
                
                if success:
                    self.download_completed.emit(study_uid, True)
                    logger.info(f"✅ Study download completed via socket service: {study_uid}")
                    return True
                else:
                    logger.warning("⚠️ Socket service download failed, falling back to direct client")
            else:
                logger.warning("⚠️ No socket service available, using direct client")
            
            # Fallback to direct client method
            study_info = self.client.get_study_info(study_uid) if self.client else None
            if not study_info:
                self.download_error.emit(study_uid, "Failed to get study info")
                return False
            
            logger.info(f"✅ Study info retrieved:")
            logger.info(f"   Patient: {study_info.get('patient_name', 'Unknown')}")
            logger.info(f"   Study Date: {study_info.get('study_date', 'Unknown')}")
            logger.info(f"   Total Instances: {study_info.get('total_instances', 0)}")
            
            # بارگذاری پیشرفت قبلی
            progress_data = None
            downloaded_instances = set()
            start_batch = 0
            
            if resume:
                progress_data = self.load_progress(study_uid)
                if progress_data:
                    logger.info(f"📋 Found previous progress:")
                    logger.info(f"   Downloaded: {progress_data.get('downloaded_count', 0)} instances")
                    logger.info(f"   Last batch: {progress_data.get('last_batch', 0)}")
                    
                    # دریافت instance های دانلود شده
                    downloaded_instances = self.get_downloaded_instances(study_uid)
                    logger.info(f"   Found {len(downloaded_instances)} existing instances")
                    
                    start_batch = progress_data.get('last_batch', 0)
                    logger.info(f"   🔄 Resuming from batch {start_batch + 1}")
                else:
                    logger.info(f"📋 No previous progress found, starting fresh")
            
            # ایجاد ساختار دیتابیس
            patient_pk = self._ensure_patient_in_db(study_info)
            study_pk = self._ensure_study_in_db(study_info, patient_pk)
            series_pks = self._ensure_series_in_db(study_info, study_pk)
            
            # دانلود به صورت batch
            total_instances = study_info.get('total_instances', 0)
            downloaded_count = len(downloaded_instances)
            failed_count = 0
            start_time = time.time()
            
            total_batches = (total_instances + batch_size - 1) // batch_size
            
            for batch_num in range(start_batch, total_batches):
                offset = batch_num * batch_size
                current_batch_size = min(batch_size, total_instances - offset)
                
                logger.info(f"\n📦 Processing batch {batch_num + 1}/{total_batches}")
                logger.info(f"   📊 Batch size: {current_batch_size} instances")
                logger.info(f"   📍 Offset: {offset}")
                
                # دانلود batch
                batch_data = self.client.get_study_dicom_files_batch(
                    study_uid, current_batch_size, offset, compression
                )
                
                if not batch_data:
                    logger.error(f"   ❌ Batch {batch_num + 1} failed")
                    failed_count += current_batch_size
                    continue
                
                instances = batch_data.get('instances', [])
                logger.info(f"   ✅ Batch {batch_num + 1} received {len(instances)} instances")
                
                # پردازش instances
                batch_downloaded = 0
                for instance_data in instances:
                    try:
                        if not instance_data.get("dicom_data"):
                            logger.warning(f"   ⚠️ No data for instance")
                            continue
                        
                        instance_number = instance_data.get('instance_number', 0)
                        
                        # بررسی اینکه instance قبلاً دانلود نشده باشد
                        if instance_number in downloaded_instances:
                            logger.info(f"   ⏭️ Instance {instance_number} already downloaded, skipping")
                            continue
                        
                        # پیدا کردن series مربوطه
                        series_number = instance_data.get('series_number', 1)
                        series_pk = series_pks.get(series_number)
                        
                        if not series_pk:
                            logger.warning(f"   ⚠️ Series {series_number} not found in database")
                            continue
                        
                        # ایجاد مسیر فایل
                        series_dir = check_series_study_exist(study_uid, f"Series_{series_number:03d}")
                        filename = f"Instance_{instance_number:04d}.dcm"
                        filepath = Path(series_dir) / filename
                        
                        # Decode و decompress داده
                        dicom_data = self._process_dicom_data(instance_data, compression)
                        
                        if not dicom_data:
                            logger.warning(f"   ⚠️ Failed to process data for instance {instance_number}")
                            continue
                        
                        # ذخیره فایل
                        with open(filepath, 'wb') as f:
                            f.write(dicom_data)
                        
                        # ذخیره در دیتابیس
                        sop_uid = instance_data.get('sop_instance_uid', f"{study_uid}_{instance_number}")
                        self._save_instance_to_db(
                            sop_uid, series_pk, str(filepath), instance_number,
                            instance_data.get('rows', 0), instance_data.get('columns', 0)
                        )
                        
                        downloaded_count += 1
                        batch_downloaded += 1
                        downloaded_instances.add(instance_number)
                        
                        logger.info(f"   ✅ Saved: {filename} ({len(dicom_data)} bytes)")
                        
                    except Exception as e:
                        logger.error(f"   ❌ Error processing instance: {e}")
                        failed_count += 1
                
                logger.info(f"   📊 Batch downloaded: {batch_downloaded} new instances")
                
                # ذخیره پیشرفت
                if resume:
                    progress_data = {
                        "study_uid": study_uid,
                        "downloaded_count": downloaded_count,
                        "last_batch": batch_num + 1,
                        "total_instances": total_instances,
                        "last_update": datetime.now().isoformat(),
                        "failed_count": failed_count
                    }
                    self.save_progress(study_uid, progress_data)
                
                # ارسال سیگنال پیشرفت
                progress_percent = (downloaded_count / total_instances) * 100
                self.download_progress.emit(study_uid, downloaded_count, total_instances)
                
                if progress_callback:
                    progress_callback(study_uid, downloaded_count, total_instances, progress_percent)
                
                # نمایش پیشرفت
                elapsed_time = time.time() - start_time
                logger.info(f"   📊 Progress: {downloaded_count}/{total_instances} ({progress_percent:.1f}%)")
                logger.info(f"   ⏱️ Elapsed time: {elapsed_time/60:.1f} minutes")
                
                # تخمین زمان باقی‌مانده
                if downloaded_count > 0:
                    remaining_instances = total_instances - downloaded_count
                    avg_time_per_instance = elapsed_time / downloaded_count
                    estimated_remaining_time = remaining_instances * avg_time_per_instance
                    logger.info(f"   ⏳ Estimated remaining time: {estimated_remaining_time/60:.1f} minutes")
            
            # پاک کردن فایل پیشرفت پس از تکمیل
            if resume and downloaded_count >= total_instances:
                self.clear_progress(study_uid)
                logger.info(f"🎉 Download completed! Progress file cleared.")
            
            # خلاصه نهایی
            total_time = time.time() - start_time
            success = downloaded_count > 0
            
            logger.info(f"\n📊 Download Summary:")
            logger.info(f"   ✅ Downloaded: {downloaded_count} instances")
            logger.info(f"   ❌ Failed: {failed_count} instances")
            logger.info(f"   ⏱️ Total Time: {total_time/60:.1f} minutes")
            
            if downloaded_count > 0:
                avg_speed = downloaded_count / (total_time / 60)  # instances/min
                logger.info(f"   🚀 Average Speed: {avg_speed:.2f} instances/min")
            
            self.download_completed.emit(study_uid, success)
            return success
            
        except Exception as e:
            logger.error(f"❌ Download error: {e}")
            self.download_error.emit(study_uid, str(e))
            return False
    
    def cleanup(self):
        """Cleanup resources"""
        try:
            # Clear active downloads
            self.active_downloads.clear()
            self.progress_callbacks.clear()
            
            # Disconnect from server
            self.disconnect_from_server()
            
            logger.info("🧹 Download manager cleaned up")
        except Exception as e:
            logger.error(f"❌ Cleanup error: {e}")


# Global download manager instance
_download_manager = None


def get_download_manager() -> ResumableDownloadManager:
    """
    Get global download manager instance with socket service integration
    
    Returns:
        ResumableDownloadManager: Global download manager instance
    """
    global _download_manager
    if _download_manager is None:
        # Get socket configuration for connection
        try:
            logger.info("🔧 Creating new ResumableDownloadManager")
            from ..utils.socket_config import get_socket_config
            config = get_socket_config()
            host = config.get_socket_host()
            port = config.get_socket_port()
            logger.info(f"   Host: {host}, Port: {port}")
            _download_manager = ResumableDownloadManager(host=host, port=port)
            logger.info("✅ ResumableDownloadManager created successfully")
        except Exception as e:
            logger.error(f"❌ Failed to get socket config, using defaults: {e}")
            _download_manager = ResumableDownloadManager()
    
    return _download_manager
    
    def _process_dicom_data(self, instance_data: Dict[str, Any], compression: str) -> Optional[bytes]:
        """پردازش داده DICOM (decode و decompress)"""
        try:
            dicom_data = instance_data.get("dicom_data")
            if not dicom_data:
                return None
            
            # Convert string back to bytes if needed
            if isinstance(dicom_data, str):
                dicom_data = dicom_data.encode('latin-1')
            
            # Decompress if needed
            if instance_data.get('is_compressed', False) and compression == "gzip":
                dicom_data = gzip.decompress(dicom_data)
            
            return dicom_data
            
        except Exception as e:
            logger.error(f"❌ Error processing DICOM data: {e}")
            return None
    
    def _ensure_patient_in_db(self, study_info: Dict[str, Any]) -> int:
        """اطمینان از وجود patient در دیتابیس"""
        patient_id = study_info.get('patient_id', 'Unknown')
        patient_name = study_info.get('patient_name', 'Unknown')
        
        # بررسی وجود patient
        patient_pk = find_patient_pk(patient_id)
        if patient_pk:
            return patient_pk
        
        # ایجاد patient جدید
        patient_pk = insert_patient(
            patient_id=patient_id,
            name=patient_name,
            birth_date=study_info.get('patient_birth_date'),
            sex=study_info.get('patient_sex'),
            age=study_info.get('patient_age'),
            patient_weight=study_info.get('patient_weight')
        )
        
        logger.info(f"✅ Created patient in database: {patient_name} (ID: {patient_id})")
        return patient_pk
    
    def _ensure_study_in_db(self, study_info: Dict[str, Any], patient_pk: int) -> int:
        """اطمینان از وجود study در دیتابیس"""
        study_uid = study_info.get('study_uid')
        
        # بررسی وجود study
        study_pk = find_study_pk(patient_pk)
        if study_pk:
            return study_pk
        
        # ایجاد study جدید
        study_pk = insert_study(
            study_uid=study_uid,
            patient_fk=patient_pk,
            study_date=study_info.get('study_date'),
            study_time=study_info.get('study_time'),
            study_description=study_info.get('study_description'),
            institution_name=study_info.get('institution_name'),
            modality=study_info.get('modality'),
            body_part=study_info.get('body_part'),
            number_of_series=study_info.get('total_series', 0),
            number_of_instances=study_info.get('total_instances', 0)
        )
        
        logger.info(f"✅ Created study in database: {study_uid}")
        return study_pk
    
    def _ensure_series_in_db(self, study_info: Dict[str, Any], study_pk: int) -> Dict[int, int]:
        """اطمینان از وجود series ها در دیتابیس"""
        series_pks = {}
        series_list = study_info.get('series', [])
        
        for series_info in series_list:
            series_uid = series_info.get('series_uid')
            series_number = series_info.get('series_number', 1)
            
            # بررسی وجود series
            series_pk = find_series_pk(series_uid)
            if series_pk:
                series_pks[series_number] = series_pk
                continue
            
            # ایجاد series جدید
            series_pk = insert_series(
                series_uid=series_uid,
                study_fk=study_pk,
                series_name=f"Series_{series_number:03d}",
                series_number=str(series_number),
                series_description=series_info.get('series_description'),
                modality=series_info.get('modality'),
                image_count=len(series_info.get('instances', [])),
                series_path=str(SOURCE_PATH / study_info.get('study_uid') / f"Series_{series_number:03d}")
            )
            
            series_pks[series_number] = series_pk
            logger.info(f"✅ Created series in database: Series_{series_number:03d}")
        
        return series_pks
    
    def _save_instance_to_db(self, sop_uid: str, series_pk: int, instance_path: str, 
                           instance_number: int, rows: int, columns: int):
        """ذخیره instance در دیتابیس"""
        try:
            # بررسی وجود instance
            instance_pk = find_instance_pk(sop_uid)
            if instance_pk:
                return instance_pk
            
            # ایجاد instance جدید
            instance_pk = insert_instance(
                sop_uid=sop_uid,
                series_fk=series_pk,
                instance_path=instance_path,
                instance_number=instance_number,
                rows=rows,
                columns=columns
            )
            
            return instance_pk
            
        except Exception as e:
            logger.error(f"❌ Error saving instance to database: {e}")
            return None
    
    def pause_download(self, study_uid: str):
        """متوقف کردن دانلود"""
        if study_uid in self.active_downloads:
            # در اینجا می‌توانید منطق pause را پیاده‌سازی کنید
            self.download_paused.emit(study_uid)
            logger.info(f"⏸️ Download paused for study: {study_uid}")
    
    def resume_download(self, study_uid: str, batch_size: int = 5, 
                       compression: str = "gzip") -> bool:
        """ادامه دانلود"""
        self.download_resumed.emit(study_uid)
        logger.info(f"▶️ Resuming download for study: {study_uid}")
        return self.download_study_resumable(study_uid, batch_size, compression, resume=True)
    
    def cancel_download(self, study_uid: str):
        """لغو دانلود"""
        if study_uid in self.active_downloads:
            # در اینجا می‌توانید منطق cancel را پیاده‌سازی کنید
            del self.active_downloads[study_uid]
            logger.info(f"⏹️ Download cancelled for study: {study_uid}")
    
    def get_download_status(self, study_uid: str) -> Dict[str, Any]:
        """دریافت وضعیت دانلود"""
        progress_data = self.load_progress(study_uid)
        if progress_data:
            return {
                "status": "in_progress",
                "downloaded_count": progress_data.get('downloaded_count', 0),
                "total_instances": progress_data.get('total_instances', 0),
                "last_batch": progress_data.get('last_batch', 0),
                "last_update": progress_data.get('last_update'),
                "failed_count": progress_data.get('failed_count', 0)
            }
        else:
            # بررسی وجود فایل‌ها
            downloaded_instances = self.get_downloaded_instances(study_uid)
            if downloaded_instances:
                return {
                    "status": "completed",
                    "downloaded_count": len(downloaded_instances),
                    "total_instances": len(downloaded_instances),
                    "last_batch": 0,
                    "last_update": None,
                    "failed_count": 0
                }
            else:
                return {
                    "status": "not_started",
                    "downloaded_count": 0,
                    "total_instances": 0,
                    "last_batch": 0,
                    "last_update": None,
                    "failed_count": 0
                }
