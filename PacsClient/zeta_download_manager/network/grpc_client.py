"""
gRPC Metadata Client - Thumbnail and metadata retrieval (Port 50051)

Handles fast metadata and thumbnail downloads via gRPC protocol.
"""

import logging
import grpc
from typing import Dict, Any, Optional

from ..core.models import StudyMetadata, SeriesInfo, PatientInfo
from ..core.exceptions import NetworkError
from ..core.constants import DEFAULT_SOCKET_HOST, DEFAULT_GRPC_PORT, CONNECTION_TIMEOUT

logger = logging.getLogger(__name__)


class GrpcMetadataClient:
    """
    gRPC-based thumbnail and metadata retrieval
    
    Features:
    - Fast metadata fetching
    - Thumbnail download (JPEG)
    - Timeout management
    - HTTP/2 keepalive
    """
    
    def __init__(
        self,
        host: str = None,
        port: int = None,
        timeout: float = None
    ):
        """
        Initialize gRPC client
        
        Args:
            host: Server host
            port: gRPC port
            timeout: Request timeout
        """
        self.host = host or DEFAULT_SOCKET_HOST
        self.port = port or DEFAULT_GRPC_PORT
        self.timeout = timeout or CONNECTION_TIMEOUT
        self.server_address = f"{self.host}:{self.port}"
        
        self.channel = None
        self.stub = None
        
        self._connect()
    
    def _connect(self) -> None:
        """Establish gRPC channel"""
        try:
            # Enhanced channel options for better reliability
            options = [
                ('grpc.keepalive_time_ms', 60000),      # 60s keepalive (less frequent to avoid server rejection)
                ('grpc.keepalive_timeout_ms', 10000),    # 10s timeout
                ('grpc.keepalive_permit_without_calls', False),  # Disable keepalive without active calls
                ('grpc.http2.min_time_between_pings_ms', 30000),  # Min 30s between pings
                ('grpc.http2.max_pings_without_data', 0),        # Allow unlimited ping frames
                ('grpc.max_receive_message_length', 100 * 1024 * 1024),  # 100MB
                ('grpc.max_send_message_length', 100 * 1024 * 1024),     # 100MB
                ('grpc.service_config', '{"loadBalancingPolicy":"round_robin"}'),
                ('grpc.enable_retries', True),
                ('grpc.per_rpc_retry_buffer_size_bytes', 1024 * 1024),  # 1MB retry buffer
            ]

            # Add connection timeout option
            from grpc import ChannelConnectivity
            self.channel = grpc.insecure_channel(self.server_address, options=options)

            # Wait for channel to be ready with timeout
            try:
                self.channel.subscribe(self._channel_state_change, try_to_connect=True)
                import time
                start_time = time.time()
                
                # Check if get_state method exists before using it
                if hasattr(self.channel, 'get_state'):
                    while self.channel.get_state(False) != ChannelConnectivity.READY:
                        if time.time() - start_time > 10:  # 10 second connection timeout
                            logger.warning(f"⚠️ gRPC connection took longer than 10s to establish")
                            break
                        time.sleep(0.1)
                else:
                    # If get_state is not available, just wait a bit for connection
                    time.sleep(0.5)
            except Exception as conn_wait_err:
                logger.warning(f"⚠️ Could not wait for channel ready: {conn_wait_err}")

            # Import protobuf stubs (from PacsClient.components)
            try:
                from PacsClient.components import dicom_service_pb2_grpc
                self.stub = dicom_service_pb2_grpc.DicomServiceStub(self.channel)

                logger.info(f"✅ gRPC channel established to {self.server_address}")

            except ImportError as e:
                logger.error(f"❌ Could not import gRPC stubs: {e}")
                self.stub = None

        except Exception as e:
            logger.error(f"❌ gRPC connection failed: {e}")
            self.channel = None
            self.stub = None
    
    def _channel_state_change(self, connectivity):
        """Callback for channel state changes"""
        logger.debug(f"📡 gRPC channel state changed to: {connectivity}")

    def fetch_study_metadata_sync(self, study_uid: str) -> Optional[StudyMetadata]:
        """
        Synchronous version of fetch_study_metadata for use in non-async contexts.
        
        Fetch complete study metadata including thumbnails

        Args:
            study_uid: Study Instance UID

        Returns:
            StudyMetadata or None on error
        """
        if not self.stub:
            logger.error("❌ gRPC stub not initialized")
            return None

        # Retry logic for robustness
        max_retries = 3
        retry_delay = 2.0  # seconds

        for attempt in range(max_retries):
            try:
                # Check channel connectivity before making call
                if self.channel:
                    try:
                        import grpc
                        from grpc import ChannelConnectivity

                        # Check if get_state method exists before using it
                        if hasattr(self.channel, 'get_state'):
                            state = self.channel.get_state(False)
                            if state != ChannelConnectivity.READY:
                                logger.warning(f"⚠️ gRPC channel not READY (state: {state}), reconnecting...")
                                self._connect()
                        else:
                            # If get_state is not available, skip state checking
                            pass
                    except Exception as e:
                        logger.warning(f"⚠️ Could not check channel state: {e}")

                # Import protobuf messages
                from PacsClient.components import dicom_service_pb2

                # Create request
                request = dicom_service_pb2.StudyThumbnailsRequest(
                    study_instance_uid=study_uid,
                    include_image_data=True,
                    include_base64=False
                )

                # Call with timeout
                response = self.stub.GetStudyThumbnails(request, timeout=self.timeout)

                # Parse response
                patient_info = PatientInfo(
                    patient_id=response.patient_id,
                    patient_name=response.patient_name
                )

                series_list = []
                thumbnails = {}

                for series in response.series_thumbnails:
                    series_info = SeriesInfo(
                        series_uid=series.series_uid,
                        series_number=int(series.series_number),
                        series_description=series.series_description,
                        modality=series.modality,
                        image_count=series.image_count,
                        protocol_name=getattr(series, 'protocol_name', ''),
                        body_part_examined=getattr(series, 'body_part_examined', ''),
                        thumbnail_data=series.thumbnail_data if series.thumbnail_data else None
                    )
                    series_list.append(series_info)

                    # Store thumbnail with int key
                    if series.thumbnail_data:
                        thumbnails[int(series.series_number)] = bytes(series.thumbnail_data)

                # ✅ FIX: Sort series by numeric series_number to ensure correct download order
                # Series numbers are now integers, so sorting is straightforward: (1, 2, 101, 201, 1452514, ...)
                try:
                    series_list = sorted(series_list, key=lambda s: s.series_number)
                    logger.info(f"✅ Series sorted by numeric order: {[s.series_number for s in series_list]}")
                except Exception as e:
                    logger.warning(f"⚠️ Could not sort series numerically: {e}")

                metadata = StudyMetadata(
                    study_uid=study_uid,
                    patient_info=patient_info,
                    study_date=response.study_date,
                    series_list=series_list,
                    thumbnails=thumbnails
                )

                logger.info(
                    f"✅ Fetched metadata: {len(series_list)} series, "
                    f"{metadata.total_image_count} images"
                )

                return metadata

            except grpc.RpcError as e:
                if e.code() == grpc.StatusCode.DEADLINE_EXCEEDED:
                    logger.warning(f"⏰ gRPC timeout after {self.timeout}s (attempt {attempt + 1}/{max_retries})")
                elif e.code() == grpc.StatusCode.UNAVAILABLE:
                    logger.warning(f"🔌 gRPC service unavailable (attempt {attempt + 1}/{max_retries}): {e.details()}")
                    # Reconnect on service unavailable
                    self._connect()
                else:
                    logger.warning(f"❌ gRPC error (attempt {attempt + 1}/{max_retries}): {e.code()}, {e.details()}")

                if attempt < max_retries - 1:
                    import time
                    time.sleep(retry_delay * (attempt + 1))  # Exponential backoff (sync version)
                else:
                    logger.error(f"❌ Failed to fetch metadata after {max_retries} attempts")
                    return None

            except Exception as e:
                logger.warning(f"❌ Error fetching metadata (attempt {attempt + 1}/{max_retries}): {e}")

                if attempt < max_retries - 1:
                    import time
                    time.sleep(retry_delay * (attempt + 1))  # Exponential backoff (sync version)
                else:
                    logger.error(f"❌ Failed to fetch metadata after {max_retries} attempts: {e}")
                    return None

    async def fetch_study_metadata(self, study_uid: str) -> Optional[StudyMetadata]:
        """
        Fetch complete study metadata including thumbnails

        Args:
            study_uid: Study Instance UID

        Returns:
            StudyMetadata or None on error
        """
        if not self.stub:
            logger.error("❌ gRPC stub not initialized")
            return None

        # Retry logic for robustness
        max_retries = 3
        retry_delay = 2.0  # seconds
        
        for attempt in range(max_retries):
            try:
                # Check channel connectivity before making call
                if self.channel:
                    try:
                        import grpc
                        from grpc import ChannelConnectivity
                        
                        # Check if get_state method exists before using it
                        if hasattr(self.channel, 'get_state'):
                            state = self.channel.get_state(False)
                            if state != ChannelConnectivity.READY:
                                logger.warning(f"⚠️ gRPC channel not READY (state: {state}), reconnecting...")
                                self._connect()
                        else:
                            # If get_state is not available, skip state checking
                            pass
                    except Exception as e:
                        logger.warning(f"⚠️ Could not check channel state: {e}")
                
                # Import protobuf messages
                from PacsClient.components import dicom_service_pb2

                # Create request
                request = dicom_service_pb2.StudyThumbnailsRequest(
                    study_instance_uid=study_uid,
                    include_image_data=True,
                    include_base64=False
                )

                # Call with timeout
                response = self.stub.GetStudyThumbnails(request, timeout=self.timeout)

                # Parse response
                patient_info = PatientInfo(
                    patient_id=response.patient_id,
                    patient_name=response.patient_name
                )

                series_list = []
                thumbnails = {}

                for series in response.series_thumbnails:
                    series_info = SeriesInfo(
                        series_uid=series.series_uid,
                        series_number=int(series.series_number),
                        series_description=series.series_description,
                        modality=series.modality,
                        image_count=series.image_count,
                        protocol_name=getattr(series, 'protocol_name', ''),
                        body_part_examined=getattr(series, 'body_part_examined', ''),
                        thumbnail_data=series.thumbnail_data if series.thumbnail_data else None
                    )
                    series_list.append(series_info)

                    # Store thumbnail with int key
                    if series.thumbnail_data:
                        thumbnails[int(series.series_number)] = bytes(series.thumbnail_data)

                # ✅ FIX: Sort series by numeric series_number to ensure correct download order
                # Series numbers are now integers, so sorting is straightforward: (1, 2, 101, 201, 1452514, ...)
                try:
                    series_list = sorted(series_list, key=lambda s: s.series_number)
                    logger.info(f"✅ Series sorted by numeric order: {[s.series_number for s in series_list]}")
                except Exception as e:
                    logger.warning(f"⚠️ Could not sort series numerically: {e}")

                metadata = StudyMetadata(
                    study_uid=study_uid,
                    patient_info=patient_info,
                    study_date=response.study_date,
                    series_list=series_list,
                    thumbnails=thumbnails
                )

                logger.info(
                    f"✅ Fetched metadata: {len(series_list)} series, "
                    f"{metadata.total_image_count} images"
                )

                return metadata

            except grpc.RpcError as e:
                if e.code() == grpc.StatusCode.DEADLINE_EXCEEDED:
                    logger.warning(f"⏰ gRPC timeout after {self.timeout}s (attempt {attempt + 1}/{max_retries})")
                elif e.code() == grpc.StatusCode.UNAVAILABLE:
                    logger.warning(f"🔌 gRPC service unavailable (attempt {attempt + 1}/{max_retries}): {e.details()}")
                    # Reconnect on service unavailable
                    self._connect()
                else:
                    logger.warning(f"❌ gRPC error (attempt {attempt + 1}/{max_retries}): {e.code()}, {e.details()}")

                if attempt < max_retries - 1:
                    import asyncio
                    await asyncio.sleep(retry_delay * (attempt + 1))  # Exponential backoff
                else:
                    logger.error(f"❌ Failed to fetch metadata after {max_retries} attempts")
                    return None

            except Exception as e:
                logger.warning(f"❌ Error fetching metadata (attempt {attempt + 1}/{max_retries}): {e}")
                
                if attempt < max_retries - 1:
                    import asyncio
                    await asyncio.sleep(retry_delay * (attempt + 1))  # Exponential backoff
                else:
                    logger.error(f"❌ Failed to fetch metadata after {max_retries} attempts: {e}")
                    return None
    
    def close(self) -> None:
        """Close gRPC channel"""
        if self.channel:
            try:
                self.channel.close()
                logger.info("🔌 gRPC channel closed")
            except:
                pass
            self.channel = None
            self.stub = None
