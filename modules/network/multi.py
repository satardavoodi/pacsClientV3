#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DICOM Files Downloader Client
کلاینت دانلود فایلهای DICOM یک study
"""
import grpc
import json
import os
import sys
import argparse
import gzip
import time
import threading
from datetime import datetime
from pathlib import Path
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
# Add grpc_generated to path
grpc_generated_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'grpc_generated')
if grpc_generated_dir not in sys.path:
    sys.path.insert(0, grpc_generated_dir)
if __package__:
    from . import dicom_service_pb2, dicom_service_pb2_grpc
else:
    project_root = Path(__file__).resolve().parents[2]
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))
    from modules.network import dicom_service_pb2, dicom_service_pb2_grpc

# pydicom imports and encoding helpers
try:
    import pydicom
    from pydicom.charset import python_encoding
    import warnings
    from contextlib import contextmanager
    
    # ثبت نگاشت کُدک برای ISO 2022 IR 159 (JIS X 0213)
    try:
        ''.encode('iso2022_jp_3')
        python_encoding.setdefault('ISO 2022 IR 159', 'iso2022_jp_3')
    except LookupError:
        python_encoding.setdefault('ISO 2022 IR 159', 'iso2022_jp_ext')
    
    @contextmanager
    def _suppress_pydicom_unknown_encoding():
        """فقط هشدار «Unknown encoding …» را بی‌اثر می‌کنیم تا dcmread بیفتد"""
        with warnings.catch_warnings():
            warnings.filterwarnings(
                "ignore",
                message=r"Unknown encoding .* - using default encoding instead",
                category=UserWarning
            )
            yield
    
    def _safe_dcmread(path, **kwargs):
        """یک dcmread امن که هشدار charset را موقتاً خاموش می‌کند"""
        with _suppress_pydicom_unknown_encoding():
            return pydicom.dcmread(path, force=True, **kwargs)
except ImportError:
    print("⚠️ pydicom not available")

class PerformanceTracker:
    """کلاس برای اندازه‌گیری عملکرد دانلود"""
    def __init__(self):
        self.start_time = None
        self.end_time = None
        self.files_downloaded = 0
        self.total_bytes = 0
        self.errors_count = 0
        self.compression_saved = 0 # bytes saved by compression
        self.lock = threading.Lock()
    def start(self):
        """شروع اندازه‌گیری"""
        self.start_time = time.time()
    def end(self):
        """پایان اندازه‌گیری"""
        self.end_time = time.time()
    def add_file(self, file_size, compressed_size=None):
        """اضافه کردن آمار فایل دانلود شده"""
        with self.lock:
            self.files_downloaded += 1
            self.total_bytes += file_size
            if compressed_size and compressed_size < file_size:
                self.compression_saved += (file_size - compressed_size)
    def add_error(self):
        """اضافه کردن خطا"""
        with self.lock:
            self.errors_count += 1
    def get_stats(self):
        """دریافت آمار کامل"""
        duration = (self.end_time or time.time()) - (self.start_time or time.time())
        if duration <= 0:
            duration = 0.001 # جلوگیری از تقسیم بر صفر
        download_rate = (self.total_bytes / (1024 * 1024)) / duration # MB/s
        files_per_second = self.files_downloaded / duration
        return {
            'duration': duration,
            'files_downloaded': self.files_downloaded,
            'total_mb': self.total_bytes / (1024 * 1024),
            'download_rate_mbps': download_rate,
            'files_per_second': files_per_second,
            'errors_count': self.errors_count,
            'compression_saved_mb': self.compression_saved / (1024 * 1024)
        }
class DicomDownloader:
    def __init__(self, host='localhost', port=50051):
        self.host = host
        self.port = port
        self.channel = None
        self.stub = None
    def _save_dicom_with_proper_encoding(self, dicom_data, filepath):
        """ذخیره فایل DICOM با رفع مشکل encoding"""
        try:
            import pydicom
            from pydicom.dataset import FileMetaDataset
            import tempfile
            # ذخیره موقت فایل خام
            with tempfile.NamedTemporaryFile(delete=False) as temp_file:
                temp_file.write(dicom_data)
                temp_path = temp_file.name
            try:
                # خواندن فایل DICOM
                ds = _safe_dcmread(temp_path)
                # رفع مشکل text encoding
                for elem in ds.iterall():
                    if elem.VR in ["SH", "LO", "PN", "CS", "DA", "DT", "TM", "UI", "ST", "LT", "UT", "AE", "AS"]:
                        value = elem.value
                        if value is None:
                            elem.value = ""
                        elif isinstance(value, (list, tuple)):
                            elem.value = "\\".join(str(v) for v in value)
                        else:
                            elem.value = str(value)
                # File Meta Information درست
                file_meta = FileMetaDataset()
                file_meta.MediaStorageSOPClassUID = getattr(ds, 'SOPClassUID', pydicom.uid.SecondaryCaptureImageStorage)
                file_meta.MediaStorageSOPInstanceUID = getattr(ds, 'SOPInstanceUID', pydicom.uid.generate_uid())
                file_meta.TransferSyntaxUID = pydicom.uid.ExplicitVRLittleEndian
                file_meta.ImplementationClassUID = "1.2.826.0.1.3680043.8.498.1"
                ds.file_meta = file_meta
                ds.is_little_endian = True
                ds.is_implicit_VR = False
                # ذخیره نهایی
                ds.save_as(filepath)
            finally:
                # پاک کردن فایل موقت
                os.unlink(temp_path)
            return True
        except Exception as e:
            print(f"⚠ خطا در رفع encoding، ذخیره خام: {e}")
            # اگر رفع نشد، فایل خام را ذخیره کن
            with open(filepath, 'wb') as f:
                f.write(dicom_data)
            return False
    def connect(self):
        """Establish connection to gRPC server"""
        try:
            # Configure gRPC options for larger messages (matching server)
            options = [
                ('grpc.max_receive_message_length', 100 * 1024 * 1024), # 100 MB
                ('grpc.max_send_message_length', 100 * 1024 * 1024), # 100 MB
                ('grpc.keepalive_time_ms', 60000),  # Reduced frequency to avoid server rejection
                ('grpc.keepalive_timeout_ms', 10000),
                ('grpc.keepalive_permit_without_calls', False),  # Disable keepalive without active calls
                ('grpc.http2.max_pings_without_data', 0),
                ('grpc.http2.min_time_between_pings_ms', 10000),
                ('grpc.http2.min_ping_interval_without_data_ms', 300000)
            ]
            self.channel = grpc.insecure_channel(f'{self.host}:{self.port}', options=options)
            self.stub = dicom_service_pb2_grpc.DicomServiceStub(self.channel)
            # Test connection
            request = dicom_service_pb2.SeriesQueryRequest(limit=1)
            response = self.stub.QuerySeriesThumbnails(request)
            print(f" Connected to gRPC server at {self.host}:{self.port}")
            return True
        except Exception as e:
            print(f" Failed to connect to gRPC server: {e}")
            return False
    def download_study_dicom_files(self, study_uid, output_dir="./dicom_files", instance_limit=5):
        """Download DICOM files for a study with performance tracking"""
        if not self.stub:
            print("❌ Not connected to server")
            return False
        print(f"📥 Requesting DICOM files for study: {study_uid}")
        print(f" Instance limit: {instance_limit}")
        # شروع performance tracking
        tracker = PerformanceTracker()
        tracker.start()
        try:
            # Create request with compression
            request = dicom_service_pb2.StudyDicomRequest(
                study_instance_uid=study_uid,
                instance_limit=instance_limit,
                compression="gzip" # Use compression for better performance
            )
            # Get files
            response = self.stub.GetStudyDicomFiles(request)
            if not response.instances:
                print("⚠ No DICOM files found for this study")
                tracker.end()
                return False
            print(f"📊 Study Information:")
            print(f" 👤 Patient: {response.patient_name} (ID: {response.patient_id})")
            print(f" 📅 Study Date: {response.study_date}")
            print(f" 📝 Description: {response.study_description}")
            print(f" 🔢 Total Instances: {response.total_instances}")
            print(f" ✅ Files Found: {response.files_found}")
            # Create output directory
            Path(output_dir).mkdir(parents=True, exist_ok=True)
            downloaded_count = 0
            total_size = 0
            compressed_total = 0
            for instance in response.instances:
                # بررسی نوع محتوا برای تشخیص خطاها
                if instance.content_type.startswith("error/"):
                    print(f" ⚠ خطا در instance {instance.instance_number}: {instance.content_type}")
                    tracker.add_error()
                    continue
                if instance.dicom_data and instance.content_type == "application/dicom":
                    # Track compressed size for performance measurement
                    compressed_size = len(instance.dicom_data)
                    compressed_total += compressed_size
                    # Decompress if needed
                    dicom_data = instance.dicom_data
                    if instance.is_compressed:
                        dicom_data = gzip.decompress(dicom_data)
                    # بررسی صحت داده‌های decompress شده
                    if not dicom_data:
                        print(f" ⚠ خطا در decompress فایل instance {instance.instance_number}")
                        tracker.add_error()
                        continue
                    # بهبود نام‌گذاری فایل برای SimpleITK
                    series_num = instance.series_number or "1"
                    instance_num = instance.instance_number or "1"
                    # تبدیل به عدد برای نام‌گذاری بهتر
                    try:
                        series_int = int(series_num) if series_num.isdigit() else 1
                        instance_int = int(instance_num) if instance_num.isdigit() else downloaded_count + 1
                    except:
                        series_int = 1
                        instance_int = downloaded_count + 1
                    # نام‌گذاری سازگار با SimpleITK
                    filename = f"IM_{instance_int:06d}.dcm"
                    filename = re.sub(r'[<>:"/\\|?*]', '_', filename)
                    # ایجاد ساختار پوشه‌بندی بر اساس سری
                    series_dir = Path(output_dir) / f"Series_{series_int:03d}"
                    series_dir.mkdir(parents=True, exist_ok=True)
                    filepath = series_dir / filename
                    # ذخیره فایل DICOM با رفع مشکل encoding
                    encoding_fixed = self._save_dicom_with_proper_encoding(dicom_data, filepath)
                    file_size = len(dicom_data)
                    total_size += file_size
                    downloaded_count += 1
                    # اضافه کردن به tracker
                    tracker.add_file(file_size, compressed_size)
                    status_icon = "✅" if encoding_fixed else "⚠"
                    compression_ratio = compressed_size / file_size if file_size > 0 else 1
                    print(f" {status_icon} Saved: {filename} ({file_size} bytes, {compression_ratio:.2f} ratio)")
                    # Save metadata with validation
                    metadata = {
                        "sop_instance_uid": instance.sop_instance_uid or "unknown",
                        "series_description": instance.series_description or "N/A",
                        "modality": instance.modality or "N/A",
                        "instance_number": instance.instance_number or "unknown",
                        "series_number": instance.series_number or "unknown",
                        "file_size": file_size,
                        "content_type": instance.content_type,
                        "is_compressed": instance.is_compressed
                    }
                    metadata_file = filepath.with_suffix('.json')
                    with open(metadata_file, 'w') as f:
                        json.dump(metadata, f, indent=2)
                else:
                    # فایل بدون داده یا نامعتبر
                    print(f" ❌ فایل نامعتبر یا خالی: instance {instance.instance_number}")
                    tracker.add_error()
            # پایان tracking و نمایش آمار
            tracker.end()
            stats = tracker.get_stats()
            print(f"\n🎯 Download Summary:")
            print(f" 📁 Downloaded: {downloaded_count} DICOM files")
            print(f" 💾 Total Size: {stats['total_mb']:.2f} MB")
            print(f" ⚡ Speed: {stats['download_rate_mbps']:.2f} MB/s")
            print(f" 📈 Files/sec: {stats['files_per_second']:.1f}")
            print(f" 🗜 Compression Saved: {stats['compression_saved_mb']:.2f} MB")
            print(f" ⏱ Duration: {stats['duration']:.2f} seconds")
            if stats['errors_count'] > 0:
                print(f" ❌ Errors: {stats['errors_count']}")
            print(f" 📂 Location: {output_dir}")
            return True
        except Exception as e:
            print(f" Error downloading DICOM files: {e}")
            return False
    def download_study_dicom_files_streaming(self, study_uid, output_dir="./dicom_files", instance_limit=5):
        """Download DICOM files using streaming for better memory efficiency with performance tracking"""
        if not self.stub:
            print("❌ Not connected to server")
            return False
        print(f"🌊 Requesting DICOM files for study: {study_uid} (Streaming mode)")
        print(f" Instance limit: {instance_limit}")
        # شروع performance tracking
        tracker = PerformanceTracker()
        tracker.start()
        try:
            # Create request
            request = dicom_service_pb2.StudyDicomRequest(
                study_instance_uid=study_uid,
                instance_limit=instance_limit,
                compression="gzip" # Use compression for better performance
            )
            # Create output directory
            Path(output_dir).mkdir(parents=True, exist_ok=True)
            downloaded_count = 0
            total_size = 0
            compressed_total = 0
            print("🔄 Starting streaming download...")
            # Stream files one by one
            for instance_response in self.stub.StreamStudyDicomFiles(request):
                # بررسی نوع محتوا برای تشخیص خطاها
                if instance_response.content_type.startswith("error/"):
                    print(f" ⚠ Stream خطا در instance {instance_response.instance_number}: {instance_response.content_type}")
                    tracker.add_error()
                    continue
                if instance_response.dicom_data and instance_response.content_type == "application/dicom":
                    # Track compressed size for performance measurement
                    compressed_size = len(instance_response.dicom_data)
                    compressed_total += compressed_size
                    # Decompress if needed
                    dicom_data = instance_response.dicom_data
                    if instance_response.is_compressed:
                        dicom_data = gzip.decompress(dicom_data)
                    # بررسی صحت داده‌های decompress شده
                    if not dicom_data:
                        print(f" ⚠ خطا در decompress فایل instance {instance_response.instance_number}")
                        tracker.add_error()
                        continue
                    # بهبود نام‌گذاری فایل برای SimpleITK
                    series_num = instance_response.series_number or "1"
                    instance_num = instance_response.instance_number or "1"
                    # تبدیل به عدد برای نام‌گذاری بهتر
                    try:
                        series_int = int(series_num) if series_num.isdigit() else 1
                        instance_int = int(instance_num) if instance_num.isdigit() else downloaded_count + 1
                    except:
                        series_int = 1
                        instance_int = downloaded_count + 1
                    # نام‌گذاری سازگار با SimpleITK
                    filename = f"IM_{instance_int:06d}.dcm"
                    filename = re.sub(r'[<>:"/\\|?*]', '_', filename)
                    # ایجاد ساختار پوشه‌بندی بر اساس سری
                    series_dir = Path(output_dir) / f"Series_{series_int:03d}"
                    series_dir.mkdir(parents=True, exist_ok=True)
                    filepath = series_dir / filename
                    # ذخیره فایل DICOM با رفع مشکل encoding
                    encoding_fixed = self._save_dicom_with_proper_encoding(dicom_data, filepath)
                    file_size = len(dicom_data)
                    total_size += file_size
                    downloaded_count += 1
                    # اضافه کردن به tracker
                    tracker.add_file(file_size, compressed_size)
                    status_icon = "✅" if encoding_fixed else "⚠"
                    compression_ratio = compressed_size / file_size if file_size > 0 else 1
                    print(f" {status_icon} Stream Saved: {filename} ({file_size} bytes, {compression_ratio:.2f} ratio)")
                    # Save metadata with validation
                    metadata = {
                        "sop_instance_uid": instance_response.sop_instance_uid or "unknown",
                        "series_description": instance_response.series_description or "N/A",
                        "modality": instance_response.modality or "N/A",
                        "instance_number": instance_response.instance_number or "unknown",
                        "series_number": instance_response.series_number or "unknown",
                        "file_size": file_size,
                        "patient_name": instance_response.patient_name or "N/A",
                        "study_date": instance_response.study_date or "N/A",
                        "content_type": instance_response.content_type,
                        "is_compressed": instance_response.is_compressed
                    }
                    metadata_file = filepath.with_suffix('.json')
                    with open(metadata_file, 'w') as f:
                        json.dump(metadata, f, indent=2)
                else:
                    print(f" ❌ Stream فایل نامعتبر یا خالی: instance {instance_response.instance_number}")
                    tracker.add_error()
            # پایان tracking و نمایش آمار
            tracker.end()
            stats = tracker.get_stats()
            print(f"\n🎯 Streaming Download Summary:")
            print(f" 📁 Downloaded: {downloaded_count} DICOM files")
            print(f" 💾 Total Size: {stats['total_mb']:.2f} MB")
            print(f" ⚡ Speed: {stats['download_rate_mbps']:.2f} MB/s")
            print(f" 📈 Files/sec: {stats['files_per_second']:.1f}")
            print(f" 🗜 Compression Saved: {stats['compression_saved_mb']:.2f} MB")
            print(f" ⏱ Duration: {stats['duration']:.2f} seconds")
            if stats['errors_count'] > 0:
                print(f" ❌ Errors: {stats['errors_count']}")
            print(f" 📂 Location: {output_dir}")
            return True
        except Exception as e:
            print(f" Error downloading DICOM files (streaming): {e}")
            return False
    def download_multiple_studies_concurrent(self, study_uids, output_base_dir="./dicom_files", instance_limit=5, max_concurrent=3):
        """Download multiple studies concurrently for better performance"""
        if not self.stub:
            print("❌ Not connected to server")
            return False
        print(f"🚀 Starting concurrent download of {len(study_uids)} studies")
        print(f" Max concurrent downloads: {max_concurrent}")
        print(f" Instance limit per study: {instance_limit}")
        overall_tracker = PerformanceTracker()
        overall_tracker.start()
        def download_single_study(study_uid):
            """Helper function to download a single study"""
            try:
                study_output_dir = Path(output_base_dir) / f"Study_{study_uid}"
                success = self.download_study_dicom_files_streaming(
                    study_uid,
                    str(study_output_dir),
                    instance_limit
                )
                return study_uid, success, None
            except Exception as e:
                return study_uid, False, str(e)
        successful_downloads = 0
        failed_downloads = 0
        # Use ThreadPoolExecutor for concurrent downloads
        with ThreadPoolExecutor(max_workers=max_concurrent) as executor:
            # Submit all download tasks
            future_to_study = {
                executor.submit(download_single_study, study_uid): study_uid
                for study_uid in study_uids
            }
            # Process completed downloads
            for future in as_completed(future_to_study):
                study_uid = future_to_study[future]
                try:
                    study_uid_result, success, error = future.result()
                    if success:
                        print(f"✅ Study {study_uid} completed successfully")
                        successful_downloads += 1
                    else:
                        print(f"❌ Study {study_uid} failed: {error or 'Unknown error'}")
                        failed_downloads += 1
                except Exception as e:
                    print(f"❌ Study {study_uid} failed with exception: {e}")
                    failed_downloads += 1
        overall_tracker.end()
        overall_stats = overall_tracker.get_stats()
        print(f"\n🎯 Concurrent Download Summary:")
        print(f" 📊 Total Studies: {len(study_uids)}")
        print(f" ✅ Successful: {successful_downloads}")
        print(f" ❌ Failed: {failed_downloads}")
        print(f" ⏱ Total Duration: {overall_stats['duration']:.2f} seconds")
        print(f" 📂 Base Location: {output_base_dir}")
        return successful_downloads > 0
def load_config():
    """Load gRPC configuration"""
    config_path = os.path.join('config', 'config.json')
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)
        grpc_port = config.get('grpc_port', 50051)
        grpc_host = config.get('grpc_host', 'localhost')
        return grpc_host, grpc_port
    except Exception as e:
        print(f" Could not load config: {e}")
        return '192.168.1.10', 50051
def main():
    if len(sys.argv) < 2:
        print("Usage: python dicom_downloader_client.py <StudyInstanceUID(s)> [output_dir] [instance_limit] [options]")
        print("Options:")
        print(" --streaming: Use streaming mode for large files (recommended)")
        print(" --concurrent: Download multiple studies concurrently (use with multiple UIDs)")
        print(" --max-concurrent N: Maximum concurrent downloads (default: 3)")
        print("Examples:")
        print(" python dicom_downloader_client.py STUDY_UID_1 --streaming")
        print(" python dicom_downloader_client.py STUDY_UID_1,STUDY_UID_2,STUDY_UID_3 --concurrent --max-concurrent 2")
        return
    study_uids_str = sys.argv[1]
    study_uids = [uid.strip() for uid in study_uids_str.split(',') if uid.strip()]
    output_dir = sys.argv[2] if len(sys.argv) > 2 else "./dicom_files"
    instance_limit = 100
    use_streaming = False
    use_concurrent = False
    max_concurrent = 3
    # Parse arguments
    i = 3
    while i < len(sys.argv):
        arg = sys.argv[i]
        if arg == "--streaming":
            use_streaming = True
        elif arg == "--concurrent":
            use_concurrent = True
        elif arg == "--max-concurrent" and i + 1 < len(sys.argv):
            max_concurrent = int(sys.argv[i + 1])
            i += 1 # Skip next argument
        elif arg.isdigit():
            instance_limit = int(arg)
        i += 1
    # Auto-enable concurrent for multiple studies
    if len(study_uids) > 1:
        use_concurrent = True
        print(f"🔄 Multiple studies detected, enabling concurrent mode")
    host, port = load_config()
    downloader = DicomDownloader(host, port)
    if downloader.connect():
        print(f"🔗 Connected to gRPC server at {host}:{port}")
        if use_concurrent and len(study_uids) > 1:
            # Concurrent download for multiple studies
            downloader.download_multiple_studies_concurrent(
                study_uids, output_dir, instance_limit, max_concurrent
            )
        elif len(study_uids) == 1:
            # Single study download
            study_uid = study_uids[0]
            if use_streaming:
                downloader.download_study_dicom_files_streaming(study_uid, output_dir, instance_limit)
            else:
                print("💡 Tip: Use --streaming flag for better performance on large files")
                downloader.download_study_dicom_files(study_uid, output_dir, instance_limit)
        else:
            print("❌ No valid study UIDs provided")
    else:
        print("❌ Failed to connect to server")
if __name__ == "__main__":
    main()
