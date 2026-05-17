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
import logging
from datetime import datetime
from pathlib import Path
import re

logger = logging.getLogger(__name__)

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

class DicomDownloader:
    def __init__(self, host='localhost', port=50051):
        self.host = host
        self.port = port
        self.channel = None
        self.stub = None
    
    def connect(self):
        """Establish connection to gRPC server"""
        try:
            # Configure gRPC options for larger messages
            options = [
                ('grpc.max_receive_message_length', 50 * 1024 * 1024),  # 50 MB
                ('grpc.max_send_message_length', 50 * 1024 * 1024),     # 50 MB
            ]
            
            self.channel = grpc.insecure_channel(f'{self.host}:{self.port}', options=options)
            self.stub = dicom_service_pb2_grpc.DicomServiceStub(self.channel)
            
            # Test connection
            request = dicom_service_pb2.SeriesQueryRequest(limit=1)
            response = self.stub.QuerySeriesThumbnails(request)
            logger.info("Connected to gRPC server at %s:%s", self.host, self.port)
            return True
            
        except Exception as e:
            logger.warning("Failed to connect to gRPC server: %s", e)
            return False
    
    def download_study_dicom_files(self, study_uid, output_dir="./dicom_files", instance_limit=5):
        """Download DICOM files for a study (limited for demo)"""
        if not self.stub:
            logger.warning("Not connected to server")
            return False
        
        logger.info("Requesting DICOM files for study: %s", study_uid)
        logger.info("Instance limit: %s (demo mode)", instance_limit)
        
        try:
            # Create request with compression
            request = dicom_service_pb2.StudyDicomRequest(
                study_instance_uid=study_uid,
                instance_limit=instance_limit,
                compression="gzip"  # Use compression for better performance
            )
            
            # Get files
            response = self.stub.GetStudyDicomFiles(request)
            
            if not response.instances:
                logger.info("No DICOM files found for this study")
                return False
            
            logger.info("Study Information:")
            logger.info("Patient: %s (ID: %s)", response.patient_name, response.patient_id)
            logger.info("Study Date: %s", response.study_date)
            logger.info("Description: %s", response.study_description)
            logger.info("Total Instances: %s", response.total_instances)
            logger.info("Files Found: %s", response.files_found)
            
            # Create output directory
            Path(output_dir).mkdir(parents=True, exist_ok=True)
            
            downloaded_count = 0
            total_size = 0
            
            for instance in response.instances:
                if instance.dicom_data:
                    # Decompress if needed
                    dicom_data = instance.dicom_data
                    if instance.is_compressed:
                        dicom_data = gzip.decompress(dicom_data)
                    
                    # Create filename
                    filename = f"Series_{instance.series_number}_Instance_{instance.instance_number}.dcm"
                    filename = re.sub(r'[<>:"/\\|?*]', '_', filename)
                    filepath = Path(output_dir) / filename
                    
                    # Save DICOM file
                    with open(filepath, 'wb') as f:
                        f.write(dicom_data)
                    
                    file_size = len(dicom_data)
                    total_size += file_size
                    downloaded_count += 1
                    
                    logger.debug("Saved: %s (%d bytes)", filename, file_size)
                    
                    # Save metadata
                    metadata = {
                        "sop_instance_uid": instance.sop_instance_uid,
                        "series_description": instance.series_description,
                        "modality": instance.modality,
                        "instance_number": instance.instance_number,
                        "series_number": instance.series_number,
                        "file_size": file_size
                    }
                    
                    metadata_file = filepath.with_suffix('.json')
                    with open(metadata_file, 'w') as f:
                        json.dump(metadata, f, indent=2)
            
            logger.info("Downloaded %d DICOM files", downloaded_count)
            logger.info("Total Size: %.2f MB", total_size / (1024 * 1024))
            logger.info("Location: %s", output_dir)
            
            return True
            
        except Exception as e:
            logger.warning("Error downloading DICOM files: %s", e)
            return False

    def download_study_dicom_files_streaming(self, study_uid, output_dir="./dicom_files", instance_limit=5):
        """Download DICOM files using streaming for better memory efficiency"""
        if not self.stub:
            logger.warning("Not connected to server")
            return False
        
        logger.info("Requesting DICOM files for study: %s (Streaming mode)", study_uid)
        logger.info("Instance limit: %s (demo mode)", instance_limit)
        
        try:
            # Create request
            request = dicom_service_pb2.StudyDicomRequest(
                study_instance_uid=study_uid,
                instance_limit=instance_limit,
                compression="gzip"  # Use compression for better performance
            )
            
            # Create output directory
            Path(output_dir).mkdir(parents=True, exist_ok=True)
            
            downloaded_count = 0
            total_size = 0
            
            # Stream files one by one
            for instance_response in self.stub.StreamStudyDicomFiles(request):
                if instance_response.dicom_data:
                    # Decompress if needed
                    dicom_data = instance_response.dicom_data
                    if instance_response.is_compressed:
                        dicom_data = gzip.decompress(dicom_data)
                    
                    # Create filename
                    filename = f"Series_{instance_response.series_number}_Instance_{instance_response.instance_number}.dcm"
                    filename = re.sub(r'[<>:"/\\|?*]', '_', filename)
                    filepath = Path(output_dir) / filename
                    
                    # Save DICOM file
                    with open(filepath, 'wb') as f:
                        f.write(dicom_data)
                    
                    file_size = len(dicom_data)
                    total_size += file_size
                    downloaded_count += 1
                    
                    logger.debug("Saved: %s (%d bytes)", filename, file_size)
                    
                    # Save metadata
                    metadata = {
                        "sop_instance_uid": instance_response.sop_instance_uid,
                        "series_description": instance_response.series_description,
                        "modality": instance_response.modality,
                        "instance_number": instance_response.instance_number,
                        "series_number": instance_response.series_number,
                        "file_size": file_size,
                        "patient_name": instance_response.patient_name,
                        "study_date": instance_response.study_date
                    }
                    
                    metadata_file = filepath.with_suffix('.json')
                    with open(metadata_file, 'w') as f:
                        json.dump(metadata, f, indent=2)
                else:
                    logger.debug("No data for instance %s", instance_response.instance_number)
            
            logger.info("Downloaded %d DICOM files using streaming", downloaded_count)
            logger.info("Total Size: %.2f MB", total_size / (1024 * 1024))
            logger.info("Location: %s", output_dir)
            
            return True
            
        except Exception as e:
            logger.warning("Error downloading DICOM files (streaming): %s", e)
            return False

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
        logger.warning("Could not load config: %s", e)
        return '192.168.1.10', 50051


def _emit_cli(message: str):
    """Emit user-facing CLI text without relying on direct print calls."""
    sys.stdout.write(f"{message}\n")

def main():
    if len(sys.argv) < 2:
        _emit_cli("Usage: python dicom_downloader_client.py <StudyInstanceUID> [output_dir] [instance_limit] [--streaming]")
        _emit_cli("  --streaming: Use streaming mode for large files (recommended)")
        return
    
    study_uid = sys.argv[1]
    output_dir = sys.argv[2] if len(sys.argv) > 2 else "./dicom_files"
    instance_limit = 100
    use_streaming = False
    
    # Parse arguments
    for i, arg in enumerate(sys.argv[3:], 3):
        if arg == "--streaming":
            use_streaming = True
        elif arg.isdigit():
            instance_limit = int(arg)
    
    host, port = load_config()
    downloader = DicomDownloader(host, port)
    
    if downloader.connect():
        if use_streaming:
            downloader.download_study_dicom_files_streaming(study_uid, output_dir, instance_limit)
        else:
            _emit_cli(" Tip: Use --streaming flag for very large files")
            downloader.download_study_dicom_files(study_uid, output_dir, instance_limit)

if __name__ == "__main__":
    main()
