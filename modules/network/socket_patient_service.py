# -*- coding: utf-8 -*-

import asyncio
import logging
from typing import Dict, List, Any, Optional, Callable
from PySide6.QtCore import QObject, Signal, QTimer
from PySide6.QtWidgets import QMessageBox

from .socket_client import PatientListSocketClient, SocketConnectionPool
from modules.network.socket_config import get_socket_config

logger = logging.getLogger(__name__)


class SocketPatientService(QObject):
    """
    Socket-based Patient Service for PACS Client
    
    This service provides an interface between the UI and the Socket server
    for patient list retrieval and management.
    """
    
    # Signals
    patientsReceived = Signal(list)  # Emitted when patients are received
    searchStarted = Signal()  # Emitted when search starts
    searchCompleted = Signal()  # Emitted when search completes
    searchError = Signal(str)  # Emitted when search encounters an error
    connectionStatusChanged = Signal(bool)  # Emitted when connection status changes
    
    def __init__(self, parent=None):
        """
        Initialize the Socket Patient Service
        
        Args:
            parent: Parent QObject
        """
        super().__init__(parent)
        
        # Get configuration
        self.config = get_socket_config()
        
        # Initialize client
        self.client = None
        self.connection_pool = None
        self.is_searching = False
        
        # Search parameters
        self.last_search_params = {}
        
        # Setup connection pool if enabled
        if self.config.get("use_connection_pool", False):
            self._setup_connection_pool()

    def reload_connection(self):
        self._setup_connection_pool()

    def _setup_connection_pool(self):
        """Setup connection pool for better performance"""
        try:
            host = self.config.get_socket_host()
            port = self.config.get_socket_port()
            pool_size = self.config.get_connection_pool_size()
            
            self.connection_pool = SocketConnectionPool(host, port, pool_size)
            logger.info(f"✅ Connection pool setup with {pool_size} connections")
        except Exception as e:
            logger.error(f"❌ Failed to setup connection pool: {e}")
            self.connection_pool = None
    
    def _get_client(self) -> Optional[PatientListSocketClient]:
        """
        Get a client instance (from pool or create new)
        
        Returns:
            PatientListSocketClient or None
        """
        if self.connection_pool:
            return self.connection_pool.get_connection()
        else:
            if not self.client:
                self.client = PatientListSocketClient(
                    host=self.config.get_socket_host(),
                    port=self.config.get_socket_port(),
                    timeout=self.config.get_connection_timeout()
                )
            return self.client
    
    def _return_client(self, client: PatientListSocketClient):
        """
        Return client to pool or keep for reuse
        
        Args:
            client: Client to return
        """
        if self.connection_pool:
            self.connection_pool.return_connection(client)
    
    def is_connected(self) -> bool:
        """
        Check if service is connected to server
        
        Returns:
            bool: True if connected, False otherwise
        """
        if self.connection_pool:
            # For connection pool, we assume it's always available
            return True
        else:
            return self.client and self.client.is_connected()
    
    def connect_to_server(self) -> bool:
        """
        Connect to the Socket server
        
        Returns:
            bool: True if connection successful, False otherwise
        """
        try:
            client = self._get_client()
            if client:
                if client.connect():
                    self.connectionStatusChanged.emit(True)
                    logger.info("✅ Connected to Socket server")
                    return True
                else:
                    self.connectionStatusChanged.emit(False)
                    logger.error("❌ Failed to connect to Socket server")
                    return False
            else:
                logger.error("❌ Failed to get client instance")
                return False
        except Exception as e:
            logger.error(f"❌ Connection error: {e}")
            self.connectionStatusChanged.emit(False)
            return False
    
    def disconnect_from_server(self):
        """Disconnect from the Socket server"""
        try:
            if self.connection_pool:
                self.connection_pool.close_all()
            elif self.client:
                self.client.disconnect()
            
            self.connectionStatusChanged.emit(False)
            logger.info("🔌 Disconnected from Socket server")
        except Exception as e:
            logger.error(f"❌ Disconnect error: {e}")
    
    def search_patients_async(self, search_params: Dict[str, Any], callback: Optional[Callable] = None):
        """
        Search patients asynchronously
        
        Args:
            search_params (dict): Search parameters
            callback (callable, optional): Callback function for results
        """
        if self.is_searching:
            logger.warning("⚠️ Search already in progress")
            return
        
        # Store search parameters
        self.last_search_params = search_params.copy()
        
        # Start search task
        asyncio.create_task(self._search_patients_task(search_params, callback))
    
    async def _search_patients_task(self, search_params: Dict[str, Any], callback: Optional[Callable] = None):
        """
        Internal async task for searching patients
        
        Args:
            search_params (dict): Search parameters
            callback (callable, optional): Callback function for results
        """
        self.is_searching = True
        self.searchStarted.emit()
        
        try:
            # Get client
            client = self._get_client()
            if not client:
                error_msg = "Failed to get client instance"
                logger.error(f"❌ {error_msg}")
                self.searchError.emit(error_msg)
                return
            
            # Perform search
            logger.info(f"🔍 Starting patient search with params: {search_params}")
            patients = client.get_patient_list_safe(**search_params)
            
            if patients is not None:
                logger.info(f"📊 Found {len(patients)} patients")
                
                # Emit signals
                self.patientsReceived.emit(patients)
                self.searchCompleted.emit()
                
                # Call callback if provided
                if callback:
                    callback(patients)
            else:
                error_msg = "Search returned None"
                logger.error(f"❌ {error_msg}")
                self.searchError.emit(error_msg)
        
        except Exception as e:
            error_msg = f"Search error: {str(e)}"
            logger.error(f"❌ {error_msg}")
            self.searchError.emit(error_msg)
        
        finally:
            self.is_searching = False
            # Return client to pool
            if client:
                self._return_client(client)
    
    def search_patients_sync(self, search_params: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Search patients synchronously
        
        Args:
            search_params (dict): Search parameters
            
        Returns:
            list: List of patients
        """
        client = None
        try:
            client = self._get_client()
            if not client:
                logger.error("❌ Failed to get client instance")
                return []
            
            logger.info(f"🔍 Starting synchronous patient search with params: {search_params}")
            patients = client.get_patient_list_safe(**search_params)
            
            if patients is not None:
                logger.info(f"📊 Found {len(patients)} patients")
            else:
                logger.error("❌ Search returned None")
                patients = []
            
            return patients
        
        except Exception as e:
            logger.error(f"❌ Search error: {str(e)}")
            return []
        
        finally:
            # Return client to pool
            if client:
                self._return_client(client)
    
    def get_patient_by_id(self, patient_id: str) -> Optional[Dict[str, Any]]:
        """
        Get a specific patient by ID
        
        Args:
            patient_id (str): Patient ID
            
        Returns:
            dict or None: Patient data or None if not found
        """
        client = None
        try:
            client = self._get_client()
            if not client:
                return None
            
            patients = client.get_patient_list_safe(patient_id=patient_id, limit=1)
            
            if patients and len(patients) > 0:
                return patients[0]
            else:
                return None
        
        except Exception as e:
            logger.error(f"❌ Error getting patient by ID: {e}")
            return None
        
        finally:
            if client:
                self._return_client(client)
    
    def search_patients_by_name(self, name: str, limit: int = 100) -> List[Dict[str, Any]]:
        """
        Search patients by name
        
        Args:
            name (str): Patient name (supports wildcards)
            limit (int): Maximum number of results
            
        Returns:
            list: List of matching patients
        """
        return self.search_patients_sync({
            "patient_name": f"*{name}*",
            "limit": limit
        })
    
    def search_patients_by_date_range(self, date_from: str, date_to: str, limit: int = 100) -> List[Dict[str, Any]]:
        """
        Search patients by date range
        
        Args:
            date_from (str): Start date (YYYYMMDD)
            date_to (str): End date (YYYYMMDD)
            limit (int): Maximum number of results
            
        Returns:
            list: List of patients in date range
        """
        return self.search_patients_sync({
            "date_from": date_from,
            "date_to": date_to,
            "limit": limit
        })
    
    def search_patients_by_modality(self, modality: str, limit: int = 100) -> List[Dict[str, Any]]:
        """
        Search patients by modality
        
        Args:
            modality (str): Modality type
            limit (int): Maximum number of results
            
        Returns:
            list: List of patients with specified modality
        """
        return self.search_patients_sync({
            "modality": modality,
            "limit": limit
        })
    
    def get_patients_with_pagination(self, page: int = 1, page_size: int = 50, **filters) -> Dict[str, Any]:
        """
        Get patients with pagination
        
        Args:
            page (int): Page number (1-based)
            page_size (int): Number of patients per page
            **filters: Additional search filters
            
        Returns:
            dict: Paginated results with metadata
        """
        try:
            client = self._get_client()
            if not client:
                return {"patients": [], "total_count": 0, "page": page, "page_size": page_size}
            
            # Calculate offset
            offset = (page - 1) * page_size
            
            # Prepare search parameters
            search_params = {
                "limit": page_size,
                "offset": offset,
                "include_study_count": True,
                "include_latest_study": True
            }
            search_params.update(filters)
            
            # Perform search
            patients = client.get_patient_list_safe(**search_params)
            
            # Get total count (this would need to be implemented in the server)
            # For now, we'll estimate based on returned results
            total_count = len(patients) if patients else 0
            
            return {
                "patients": patients or [],
                "total_count": total_count,
                "page": page,
                "page_size": page_size,
                "has_next": len(patients or []) == page_size,
                "has_previous": page > 1
            }
        
        except Exception as e:
            logger.error(f"❌ Pagination error: {e}")
            return {"patients": [], "total_count": 0, "page": page, "page_size": page_size}
        
        finally:
            if client:
                self._return_client(client)
    
    def update_server_settings(self, host: str, port: int, save_to_file: bool = True):
        """
        Update server settings
        
        Args:
            host (str): Server host
            port (int): Server port
            save_to_file (bool): Whether to save changes to file
        """
        try:
            # Update configuration
            self.config.update_server_settings(host, port, save_to_file)
            
            # Disconnect current connections
            self.disconnect_from_server()
            
            # Recreate connection pool if needed
            if self.connection_pool:
                self._setup_connection_pool()
            
            logger.info(f"🔄 Updated server settings: {host}:{port}")
        
        except Exception as e:
            logger.error(f"❌ Error updating server settings: {e}")
    
    def update_server_settings_temporary(self, host: str, port: int):
        """
        Update server settings temporarily without saving to file
        
        Args:
            host (str): Server host
            port (int): Server port
        """
        self.update_server_settings(host, port, save_to_file=False)
    
    def get_server_info(self) -> Dict[str, Any]:
        """
        Get server information
        
        Returns:
            dict: Server information
        """
        return {
            "host": self.config.get_socket_host(),
            "port": self.config.get_socket_port(),
            "connected": self.is_connected(),
            "searching": self.is_searching,
            "last_search_params": self.last_search_params
        }
    
    def test_connection(self) -> bool:
        """
        Test connection to server
        
        Returns:
            bool: True if connection successful, False otherwise
        """
        client = None
        try:
            client = self._get_client()
            if not client:
                return False
            
            # Try to connect
            connected = client.connect()
            if connected:
                # Try a simple request with minimal parameters
                patients = client.get_patient_list_safe(limit=1)
                logger.info("✅ Connection test successful")
                return True
            else:
                logger.error("❌ Connection test failed")
                return False
        
        except Exception as e:
            logger.error(f"❌ Connection test error: {e}")
            return False
        
        finally:
            if client:
                self._return_client(client)
    
    def cleanup(self):
        """Cleanup resources"""
        try:
            self.disconnect_from_server()
            # Force cleanup of client
            if self.client:
                try:
                    self.client.disconnect()
                except:
                    pass
                self.client = None
            logger.info("🧹 Socket Patient Service cleaned up")
        except Exception as e:
            logger.error(f"❌ Cleanup error: {e}")
    
    def __del__(self):
        """Destructor to ensure cleanup"""
        try:
            self.cleanup()
        except:
            pass


# Global service instance
_socket_patient_service = None


def get_socket_patient_service() -> SocketPatientService:
    """
    Get global Socket Patient Service instance
    
    Returns:
        SocketPatientService: Global service instance
    """
    global _socket_patient_service
    if _socket_patient_service is None:
        _socket_patient_service = SocketPatientService()

    else:
        _socket_patient_service.reload_connection()
    return _socket_patient_service


# # Example usage
# if __name__ == "__main__":
#     import sys
#     from PySide6.QtWidgets import QApplication
#
#     app = QApplication(sys.argv)
#
#     # Create service
#     service = SocketPatientService()
#
#     # Connect signals
#     service.patientsReceived.connect(lambda patients: print(f"Received {len(patients)} patients"))
#     service.searchError.connect(lambda error: print(f"Search error: {error}"))
#     service.connectionStatusChanged.connect(lambda status: print(f"Connection status: {status}"))
#
#     # Test connection
#     if service.test_connection():
#         print("✅ Connection test successful")
#
#         # Test search
#         service.search_patients_async({
#             "limit": 10,
#             "include_study_count": True
#         })
#     else:
#         print("❌ Connection test failed")
#
#     # Run event loop briefly
#     QTimer.singleShot(5000, app.quit)
#     app.exec()
#
#     # Cleanup
#     service.cleanup()
