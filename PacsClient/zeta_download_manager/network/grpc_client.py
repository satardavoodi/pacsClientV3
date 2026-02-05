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
            # Channel options for slow networks
            options = [
                ('grpc.keepalive_time_ms', 30000),      # 30s keepalive
                ('grpc.keepalive_timeout_ms', 10000),   # 10s timeout
                ('grpc.keepalive_permit_without_calls', True),
                ('grpc.http2.min_time_between_pings_ms', 10000),
                ('grpc.max_receive_message_length', 100 * 1024 * 1024),  # 100MB
            ]
            
            self.channel = grpc.insecure_channel(self.server_address, options=options)
            
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
        
        try:
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
                    series_number=str(series.series_number),
                    series_description=series.series_description,
                    modality=series.modality,
                    image_count=series.image_count,
                    protocol_name=getattr(series, 'protocol_name', ''),
                    body_part_examined=getattr(series, 'body_part_examined', ''),
                    thumbnail_data=series.thumbnail_data if series.thumbnail_data else None
                )
                series_list.append(series_info)
                
                # Store thumbnail
                if series.thumbnail_data:
                    thumbnails[str(series.series_number)] = bytes(series.thumbnail_data)
            
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
                logger.error(f"⏰ gRPC timeout after {self.timeout}s")
            else:
                logger.error(f"❌ gRPC error: {e.code()}, {e.details()}")
            return None
        
        except Exception as e:
            logger.error(f"❌ Error fetching metadata: {e}")
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
