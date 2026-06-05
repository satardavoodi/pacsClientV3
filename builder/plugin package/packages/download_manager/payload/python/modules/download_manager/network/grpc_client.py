"""
Metadata client compatibility layer for thumbnail and study metadata retrieval.

The historical gRPC API is preserved for call-site compatibility, but the
implementation now uses the Socket patient-list service so metadata fetches do
not block the UI on gRPC channel startup.
"""

import asyncio
import base64
import logging
from typing import Dict, Any, Optional

from ..core.models import StudyMetadata, SeriesInfo, PatientInfo
from ..core.constants import DEFAULT_SOCKET_HOST, DEFAULT_GRPC_PORT, CONNECTION_TIMEOUT
from modules.network.socket_client import PatientListSocketClient

logger = logging.getLogger(__name__)


class GrpcMetadataClient:
    """
    Socket-backed thumbnail and metadata retrieval compatibility layer
    
    Features:
    - Fast metadata fetching through the existing socket pipeline
    - Thumbnail download via the same response payload used by the UI
    - Lazy initialization so widget creation does not block on network setup
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
            port: Socket metadata port (kept for compatibility)
            timeout: Request timeout
        """
        self.host = host or DEFAULT_SOCKET_HOST
        self.port = port or DEFAULT_GRPC_PORT
        self.timeout = timeout or CONNECTION_TIMEOUT
        self.server_address = f"{self.host}:{self.port}"
        
        self.channel = None
        self.stub = None
        self._socket_client: Optional[PatientListSocketClient] = None

    def _get_socket_client(self) -> PatientListSocketClient:
        if self._socket_client is None:
            # GrpcMetadataClient is socket-backed: the socket client must use the
            # socket-protocol port from socket_config (e.g. 50052), never the legacy
            # gRPC port (50051) that call sites still pass for historical compatibility.
            from modules.network.socket_config import get_socket_server_settings
            _cfg = get_socket_server_settings() or {}
            _socket_host = self.host or _cfg.get('host') or DEFAULT_SOCKET_HOST
            _socket_port = int(_cfg.get('port') or 50052)
            self._socket_client = PatientListSocketClient(
                host=_socket_host,
                port=_socket_port,
                timeout=self.timeout,
            )
        return self._socket_client
    
    def _connect(self) -> None:
        """Compatibility no-op retained for existing call sites."""
        return None
    
    def _channel_state_change(self, connectivity):
        """Callback for channel state changes"""
        logger.debug(f"📡 metadata client state changed to: {connectivity}")

    def _build_metadata_from_socket(self, study_uid: str) -> Optional[StudyMetadata]:
        socket_client = self._get_socket_client()
        data = socket_client.get_study_thumbnails(
            study_uid,
            include_base64=False,
            include_image_data=False,
        )
        if not data:
            return None

        patient_info = PatientInfo(
            patient_id=str(data.get("patient_id") or ""),
            patient_name=str(data.get("patient_name") or ""),
        )

        series_list = []
        thumbnails = {}
        for series in data.get("series_thumbnails") or []:
            if not isinstance(series, dict):
                continue
            thumb_raw = series.get("thumbnail_data") or series.get("thumbnail_base64") or ""
            thumb_bytes = b""
            if isinstance(thumb_raw, str) and thumb_raw:
                try:
                    thumb_bytes = base64.b64decode(thumb_raw)
                except Exception:
                    thumb_bytes = b""
            elif isinstance(thumb_raw, (bytes, bytearray)):
                thumb_bytes = bytes(thumb_raw)

            series_info = SeriesInfo(
                series_uid=str(series.get("series_uid") or ""),
                series_number=int(str(series.get("series_number") or 0)),
                series_description=str(series.get("series_description") or ""),
                modality=str(series.get("modality") or ""),
                image_count=int(series.get("image_count") or 0),
                protocol_name=series.get("protocol_name"),
                body_part_examined=series.get("body_part_examined"),
                manufacturer=series.get("manufacturer"),
                institution_name=series.get("institution_name"),
                thumbnail_data=thumb_bytes or None,
            )
            series_list.append(series_info)
            if thumb_bytes:
                thumbnails[str(series.get("series_number") or "")] = thumb_bytes

        metadata = StudyMetadata(
            study_uid=str(study_uid or ""),
            patient_info=patient_info,
            study_date=str(data.get("study_date") or ""),
            study_time=data.get("study_time"),
            study_description=data.get("study_description"),
            series_list=series_list,
            thumbnails=thumbnails,
        )
        return metadata

    def _fetch_metadata_with_retries(self, study_uid: str) -> Optional[StudyMetadata]:
        max_retries = 3
        retry_delay = 2.0
        for attempt in range(max_retries):
            try:
                return self._build_metadata_from_socket(study_uid)
            except Exception as exc:
                logger.warning(
                    "❌ Metadata fetch via socket failed (attempt %s/%s): %s",
                    attempt + 1,
                    max_retries,
                    exc,
                )
                if attempt < max_retries - 1:
                    import time
                    time.sleep(retry_delay * (attempt + 1))
                else:
                    return None

    def fetch_study_metadata_sync(self, study_uid: str) -> Optional[StudyMetadata]:
        """
        Synchronous version of fetch_study_metadata for use in non-async contexts.
        
        Fetch complete study metadata including thumbnails

        Args:
            study_uid: Study Instance UID

        Returns:
            StudyMetadata or None on error
        """
        return self._fetch_metadata_with_retries(study_uid)

    async def fetch_study_metadata(self, study_uid: str) -> Optional[StudyMetadata]:
        """
        Fetch complete study metadata including thumbnails

        Args:
            study_uid: Study Instance UID

        Returns:
            StudyMetadata or None on error
        """
        return await asyncio.to_thread(self._fetch_metadata_with_retries, study_uid)
    
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
