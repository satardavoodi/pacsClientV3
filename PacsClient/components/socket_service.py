# -*- coding: utf-8 -*-

import logging
from typing import Optional, Dict, Any

from ..utils.socket_config import get_socket_config
# Use Zeta SocketDicomClient (new implementation)
from PacsClient.zeta_download_manager.network.socket_client import SocketDicomClient


logger = logging.getLogger(__name__)


class SocketService:
    """
    Reusable app-wide Socket service.
    Provides a single place to manage connection and simple requests.
    
    Now uses Zeta SocketDicomClient for improved performance and reliability.
    """

    def __init__(self):
        self.config = get_socket_config()
        self.client: Optional[SocketDicomClient] = None

    def _ensure_client(self) -> Optional[SocketDicomClient]:
        try:
            if self.client is None:
                logger.info(f"🔧 Creating new Zeta SocketDicomClient")
                logger.info(f"   Host: {self.config.get_socket_host()}")
                logger.info(f"   Port: {self.config.get_socket_port()}")
                logger.info(f"   Timeout: {self.config.get_connection_timeout()}")
                self.client = SocketDicomClient(
                    host=self.config.get_socket_host(),
                    port=int(self.config.get_socket_port()),
                    timeout=float(self.config.get_connection_timeout()),
                )
                logger.info(f"✅ Zeta client created successfully")
            return self.client
        except Exception as e:
            logger.error(f"❌ Failed to ensure client: {e}")
            return None

    def connect(self) -> bool:
        try:
            client = self._ensure_client()
            if not client:
                logger.error("❌ Failed to ensure client for connect")
                return False
            return client.connect()
        except Exception as e:
            logger.error(f"❌ SocketService connect error: {e}")
            return False

    def connect_with_retry(self) -> bool:
        try:
            client = self._ensure_client()
            if not client:
                logger.error("❌ Failed to ensure client for connect_with_retry")
                return False
            return client.connect_with_retry()
        except Exception as e:
            logger.error(f"❌ SocketService connect_with_retry error: {e}")
            return False

    def disconnect(self) -> None:
        try:
            if self.client:
                self.client.disconnect()
        except Exception as e:
            logger.error(f"❌ SocketService disconnect error: {e}")

    def is_connected(self) -> bool:
        return bool(self.client and self.client.is_connected())

    def test_connection(self) -> bool:
        try:
            if not self.connect():
                return False
            # Test connection - Zeta client uses connected attribute
            return self.client.connected if self.client else False
        except Exception as e:
            logger.error(f"❌ SocketService test_connection error: {e}")
            return False

    def update_server(self, host: str, port: int, save_to_file: bool = True) -> None:
        try:
            self.config.update_server_settings(host, int(port), save_to_file)
            # Reset client to apply new settings
            if self.client:
                try:
                    self.client.disconnect()
                except Exception:
                    pass
                self.client = None
            logger.info(f"🔄 SocketService server updated to {host}:{port}")
        except Exception as e:
            logger.error(f"❌ SocketService update_server error: {e}")

    # NOTE: The following methods use legacy API patterns
    # TODO: Refactor to use Zeta DownloadExecutor for full downloads
    # For now, these provide compatibility shims for existing code
    
    def get_study_info(self, study_uid: str) -> Optional[Dict[str, Any]]:
        client = self._ensure_client()
        if not client:
            logger.error("❌ Failed to ensure client for get_study_info")
            return None
        if not self.is_connected() and not self.connect_with_retry():
            logger.error("❌ Failed to connect for get_study_info")
            return None
        logger.info(f"🔍 Calling client send_request for GetStudyInfo: {study_uid}")
        # Use Zeta's send_request method
        result = client.send_request("GetStudyInfo", {"study_uid": study_uid})
        logger.info(f"🔍 get_study_info result: {result is not None}")
        return result

    def download_study_resumable(
        self,
        study_uid: str,
        output_dir: str,
        batch_size: int = 10,
        compression: str = "gzip",
        resume: bool = True,
        progress_callback=None,
        patient_info: dict = None,
    ) -> bool:
        logger.info(f"🔄 SocketService.download_study_resumable called")
        logger.info(f"   Study UID: {study_uid}")
        logger.info(f"   Output dir: {output_dir}")
        logger.info(f"   Batch size: {batch_size}")
        logger.info(f"   Compression: {compression}")
        logger.info(f"   Resume: {resume}")
        logger.info(f"   Progress callback: {progress_callback is not None}")
        logger.info(f"   Patient info: {patient_info.get('patient_name', 'N/A') if patient_info else 'None'}")
        
        client = self._ensure_client()
        if not client:
            logger.error("❌ Failed to ensure client")
            return False
        logger.info(f"✅ Client ensured: {type(client)}")
            
        if not self.is_connected() and not self.connect_with_retry():
            logger.error("❌ Failed to connect to server")
            return False
        
        logger.info("✅ Client connected, starting download via Zeta adapter")
        
        # Use Zeta adapter for downloads
        from .zeta_adapter import start_zeta_download
        
        study_info = {
            'study_uid': study_uid,
            'patient_id': patient_info.get('patient_id', '') if patient_info else '',
            'patient_name': patient_info.get('patient_name', '') if patient_info else '',
            'study_date': patient_info.get('study_date', '') if patient_info else '',
            'modality': patient_info.get('modality', '') if patient_info else '',
            'description': patient_info.get('description', '') if patient_info else '',
        }
        
        try:
            result = start_zeta_download(
                study_info=study_info,
                progress_callback=progress_callback,
                completion_callback=None
            )
            logger.info(f"🔍 Zeta download started: {result}")
            return result
        except Exception as e:
            logger.error(f"❌ Zeta download failed: {e}")
            import traceback
            logger.error(f"❌ Full traceback: {traceback.format_exc()}")
            return False
    
    def cleanup(self):
        """Cleanup resources"""
        try:
            if self.client:
                self.client.disconnect()
                self.client = None
        except Exception as e:
            logger.error(f"❌ SocketService cleanup error: {e}")
    
    def __del__(self):
        """Destructor to ensure cleanup"""
        try:
            self.cleanup()
        except:
            pass


# Global singleton accessor
_socket_service: Optional[SocketService] = None


def get_socket_service() -> SocketService:
    global _socket_service
    if _socket_service is None:
        logger.info("🔧 Creating new SocketService")
        _socket_service = SocketService()
        logger.info("✅ SocketService created successfully")
    return _socket_service


