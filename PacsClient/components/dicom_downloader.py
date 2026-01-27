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
from datetime import datetime
from pathlib import Path
import re
from PacsClient.pacs.patient_tab.utils import check_series_study_exist

# Add grpc_generated to path
grpc_generated_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'grpc_generated')
if grpc_generated_dir not in sys.path:
    sys.path.insert(0, grpc_generated_dir)

from . import dicom_service_pb2
from . import dicom_service_pb2_grpc


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
                ('grpc.max_send_message_length', 50 * 1024 * 1024),  # 50 MB
            ]

            self.channel = grpc.insecure_channel(f'{self.host}:{self.port}', options=options)
            self.stub = dicom_service_pb2_grpc.DicomServiceStub(self.channel)

            # Test connection
            request = dicom_service_pb2.SeriesQueryRequest(limit=1)
            response = self.stub.QuerySeriesThumbnails(request)
            return True

        except Exception as e:
            print(f" Failed to connect to gRPC server: {e}")
            return False

    def download_study_dicom_files(self, study_uid, output_dir="./dicom_files", instance_limit=0):
        """Download DICOM files for a study (limited for demo)"""
        if not self.stub:
            return False

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
                print(" No DICOM files found for this study")
                return False

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

            return True

        except Exception as e:
            print(f" Error downloading DICOM files: {e}")
            return False

    def download_study_dicom_files_streaming(self, study_uid, output_dir="./dicom_files", instance_limit=0, progress_callback=None):
        """Download DICOM files using streaming for better memory efficiency"""
        if not self.stub:
            return False

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

            # Progress tracking per series
            series_progress = {}  # series_number -> {'total': count, 'downloaded': count}
            series_total_counts = {}  # Will be populated as we discover series
            series_file_counts = {}  # Track how many files we've seen per series

            # Performance optimization: batch file operations
            batch_files = []
            batch_size = 10  # Process files in batches

            # First pass: count total instances per series for accurate progress

            # Stream files one by one
            current_series = None
            for instance_response in self.stub.StreamStudyDicomFiles(request):
                if instance_response.dicom_data:
                    # Decompress if needed
                    dicom_data = instance_response.dicom_data
                    if instance_response.is_compressed:
                        dicom_data = gzip.decompress(instance_response.dicom_data)

                    series_number = instance_response.series_number

                    # Check if we've moved to a new series - complete the previous one
                    if current_series is not None and current_series != series_number:
                        # Previous series is complete - flush any pending batch files first
                        if batch_files:
                            print(f"🔄 Flushing {len(batch_files)} pending files before completing series {current_series}")
                            downloaded_count, total_size = self._process_batch_files(
                                batch_files, downloaded_count, total_size
                            )
                            batch_files = []  # Clear batch

                        if current_series in series_progress and not series_progress[current_series].get('completed', False):
                            series_progress[current_series]['completed'] = True
                            if progress_callback:
                                progress_callback('series_complete', current_series, 100)

                    current_series = series_number

                    # Initialize series progress tracking
                    if series_number not in series_progress:
                        series_progress[series_number] = {'downloaded': 0, 'last_progress': 0}
                        series_file_counts[series_number] = 0
                        # Notify callback that series download started
                        if progress_callback:
                            progress_callback('series_started', series_number, 0)

                    # Count total files in this series
                    series_file_counts[series_number] += 1

                    # series_path = check_series_study_exist(study_uid, f"Series_{instance_response.series_number}")
                    series_path = check_series_study_exist(study_uid, f"{series_number}")

                    # Create filename
                    filename = f"Instance_{instance_response.instance_number}.dcm"
                    filename = re.sub(r'[<>:"/\\|?*]', '_', filename)
                    filepath = Path(series_path) / filename

                    # Add to batch for processing
                    batch_files.append((filepath, dicom_data))

                    # Process batch when it reaches the batch size
                    if len(batch_files) >= batch_size:
                        downloaded_count, total_size = self._process_batch_files(
                            batch_files, downloaded_count, total_size
                        )
                        batch_files = []  # Clear batch

                    file_size = len(dicom_data)
                    total_size += file_size
                    downloaded_count += 1

                    # Update series progress
                    series_progress[series_number]['downloaded'] += 1

                    # Calculate accurate progress based on actual file counts
                    files_downloaded = series_progress[series_number]['downloaded']

                    # Use the current downloaded count as an estimate for total files
                    # This is not perfect but gives us a reasonable progress indication
                    if files_downloaded == 1:
                        # First file - show 10% progress
                        progress_percent = 10
                    else:
                        # Estimate progress based on download pattern
                        # Cap at 90% until we're sure the series is complete
                        estimated_progress = min(90, int((files_downloaded / (files_downloaded + 2)) * 100))
                        progress_percent = max(10, estimated_progress)

                    # Only update if progress changed significantly (reduce UI updates)
                    last_progress = series_progress[series_number]['last_progress']
                    if progress_percent != last_progress:  # Update when progress actually changes
                        series_progress[series_number]['last_progress'] = progress_percent
                        if progress_callback:
                            progress_callback('series_progress', series_number, progress_percent)


                    # We'll mark series as complete when the stream ends for that series
                    # This check will be done in the main loop when we detect series change

                    # # Save metadata
                    # metadata = {
                    #     "sop_instance_uid": instance_response.sop_instance_uid,
                    #     "series_description": instance_response.series_description,
                    #     "modality": instance_response.modality,
                    #     "instance_number": instance_response.instance_number,
                    #     "series_number": instance_response.series_number,
                    #     "file_size": file_size,
                    #     "patient_name": instance_response.patient_name,
                    #     "study_date": instance_response.study_date
                    # }
                    #
                    # metadata_file = filepath.with_suffix('.json')
                    # with open(metadata_file, 'w') as f:
                    #     json.dump(metadata, f, indent=2)
                else:
                    print(f"    No data for instance {instance_response.instance_number}")

            # Process remaining files in the last batch
            if batch_files:
                downloaded_count, total_size = self._process_batch_files(
                    batch_files, downloaded_count, total_size
                )

            # Complete the last series - flush any remaining batch files first
            if current_series is not None and current_series in series_progress:
                # Flush remaining batch files for the last series
                if batch_files:
                    print(f"🔄 Flushing {len(batch_files)} remaining files for final series {current_series}")
                    downloaded_count, total_size = self._process_batch_files(
                        batch_files, downloaded_count, total_size
                    )
                    batch_files = []  # Clear batch

                if not series_progress[current_series].get('completed', False):
                    series_progress[current_series]['completed'] = True
                    if progress_callback:
                        progress_callback('series_complete', current_series, 100)

            # Mark any remaining incomplete series as complete (fallback)
            if progress_callback:
                for series_number in series_progress:
                    if not series_progress[series_number].get('completed', False):
                        progress_callback('series_complete', series_number, 100)

            return True

        except Exception as e:
            print(f" Error downloading DICOM files (streaming): {e}")
            return False

    def _process_batch_files(self, batch_files, downloaded_count, total_size):
        """
        Process a batch of files efficiently
        """
        try:
            for filepath, dicom_data in batch_files:
                # Save DICOM file
                with open(filepath, 'wb') as f:
                    f.write(dicom_data)

                file_size = len(dicom_data)
                total_size += file_size
                downloaded_count += 1

        except Exception as e:
            print(f" Error processing batch files: {e}")

        return downloaded_count, total_size