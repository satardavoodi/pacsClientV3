# -*- coding: utf-8 -*-

import logging
import os
import grpc

from . import dicom_service_pb2
from . import dicom_service_pb2_grpc

logger = logging.getLogger(__name__)


class DicomGrpcClient:
    """
    gRPC client for DICOM services with timeout support for slow networks.

    Key features:
    - Configurable timeout for all RPC calls (default: 30s)
    - Automatic reconnection on channel failure
    - Graceful fallback on timeout

    Note: insecure_channel is used because the server runs on a private LAN
    behind a firewall. TLS can be added via grpc.secure_channel when needed.
    """

    DEFAULT_TIMEOUT = 30.0

    def __init__(self, host='localhost', port=50051, timeout: float = None):
        self.server_address = f"{host}:{port}"
        self.timeout = timeout or self.DEFAULT_TIMEOUT
        logger.info(f"gRPC client init: {self.server_address} (timeout={self.timeout}s)")
        self.channel = None
        self.stub = None
        self._connect()

    def _connect(self):
        """Establish gRPC channel with keepalive options."""
        try:
            # Close stale channel before reconnecting
            if self.channel is not None:
                try:
                    self.channel.close()
                except Exception:
                    pass

            options = [
                ('grpc.keepalive_time_ms', 60000),
                ('grpc.keepalive_timeout_ms', 10000),
                ('grpc.keepalive_permit_without_calls', False),
                ('grpc.http2.min_time_between_pings_ms', 10000),
                ('grpc.max_receive_message_length', 100 * 1024 * 1024),  # 100MB
            ]
            self.channel = grpc.insecure_channel(self.server_address, options=options)
            self.stub = dicom_service_pb2_grpc.DicomServiceStub(self.channel)
            logger.info(f"Connected to gRPC server at {self.server_address}")
        except Exception as e:
            logger.error(f"Error connecting to gRPC server: {e}")
            self.channel = None
            self.stub = None

    def _ensure_stub(self) -> bool:
        """Reconnect if channel/stub is missing. Returns True if stub is usable."""
        if self.stub is not None:
            return True
        logger.warning("gRPC stub unavailable — attempting reconnect")
        self._connect()
        return self.stub is not None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_study_thumbnails_with_timeout(self, study_uid: str, timeout: float = None) -> dict:
        """
        Get study thumbnails (metadata only, no image data).
        Optimized for the download manager.
        """
        if not self._ensure_stub():
            return None

        call_timeout = timeout or self.timeout
        try:
            request = dicom_service_pb2.StudyThumbnailsRequest(
                study_instance_uid=study_uid,
                include_image_data=False,
                include_base64=False,
            )
            response = self.stub.GetStudyThumbnails(request, timeout=call_timeout)

            series_list = []
            for series in response.series_thumbnails:
                series_list.append({
                    'series_uid': series.series_uid,
                    'series_number': series.series_number,
                    'series_description': series.series_description,
                    'modality': series.modality,
                    'image_count': series.image_count,
                    'protocol_name': getattr(series, 'protocol_name', ''),
                    'body_part_examined': getattr(series, 'body_part_examined', ''),
                })

            return {
                'series_list': series_list,
                'patient_name': response.patient_name,
                'patient_id': response.patient_id,
                'study_date': response.study_date,
            }

        except grpc.RpcError as e:
            self._log_rpc_error(e, "get_study_thumbnails_with_timeout", call_timeout, study_uid)
            return None
        except Exception as e:
            logger.error(f"Error getting study thumbnails: {e}")
            return None

    def get_thumbnails(self, patient_id, study_uid, timeout: float = None):
        """Get study thumbnails including image data."""
        if not self._ensure_stub():
            return None

        call_timeout = timeout or self.timeout
        try:
            request = dicom_service_pb2.StudyThumbnailsRequest(
                study_instance_uid=study_uid,
                include_image_data=True,
            )
            response = self.stub.GetStudyThumbnails(request, timeout=call_timeout)

            result = {
                'patient_name': response.patient_name,
                'patient_id': response.patient_id,
                'study_date': response.study_date,
                'study_uid': response.study_instance_uid,
                'thumbnails': [],
            }

            for series in response.series_thumbnails:
                result['thumbnails'].append({
                    'series_uid': series.series_uid,
                    'series_number': series.series_number,
                    'series_description': series.series_description,
                    'modality': series.modality,
                    'image_count': series.image_count,
                    'thumbnail_path': series.thumbnail_path,
                    'thumbnail_data': series.thumbnail_data,
                })

            return result

        except grpc.RpcError as e:
            self._log_rpc_error(e, "get_thumbnails", call_timeout, study_uid)
            return None
        except Exception as e:
            logger.error(f"Error getting thumbnails: {e}")
            return None

    def get_dicom_images(self, patient_id, study_uid, series_uid, save_dir):
        """Download DICOM images via streaming RPC."""
        if not self._ensure_stub():
            return {'images': [], 'error': 'Not connected to server'}

        try:
            request = dicom_service_pb2.DicomImageRequest(
                patient_id=patient_id,
                study_uid=study_uid,
                series_uid=series_uid,
            )
            series_dir = os.path.join(save_dir, study_uid, series_uid)
            os.makedirs(series_dir, exist_ok=True)

            logger.info(f"Requesting images for series {series_uid} → {series_dir}")

            received_files = []
            error = None

            try:
                for response in self.stub.GetDicomImages(request, timeout=self.timeout):
                    file_path = os.path.join(series_dir, response.file_name)
                    with open(file_path, 'wb') as f:
                        f.write(response.image_data)

                    received_files.append({
                        'sop_instance_uid': response.sop_instance_uid,
                        'instance_number': response.instance_number,
                        'file_path': file_path,
                        'file_name': response.file_name,
                    })

                logger.info(f"Received {len(received_files)} images for series {series_uid}")

            except grpc.RpcError as e:
                error = f"gRPC error: {e.code()}, {e.details()}"
                logger.error(error)

            return {'images': received_files, 'error': error}

        except Exception as e:
            logger.error(f"Error in get_dicom_images: {e}", exc_info=True)
            return {'images': [], 'error': str(e)}

    def close(self):
        """Close the gRPC channel."""
        if self.channel:
            self.channel.close()
            self.channel = None
            self.stub = None
            logger.info("gRPC channel closed")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _log_rpc_error(e, method: str, timeout: float, uid: str = ""):
        """Centralized gRPC error logging."""
        if e.code() == grpc.StatusCode.DEADLINE_EXCEEDED:
            logger.warning(f"gRPC timeout ({timeout}s) in {method} for {uid[:40]}")
        elif e.code() == grpc.StatusCode.UNAVAILABLE:
            logger.error(f"gRPC server unavailable in {method}: {e.details()}")
        else:
            logger.error(f"gRPC error in {method}: {e.code()}, {e.details()}")