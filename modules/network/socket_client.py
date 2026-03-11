# -*- coding: utf-8 -*-

import socket
import json
import logging
from typing import Dict, List, Any, Optional
import threading
import time

from modules.network.socket_config import get_socket_config
from modules.network.socket_token_manager import get_socket_token_manager

logger = logging.getLogger(__name__)


class PatientListSocketClient:
    """
    Simple Socket Client for Patient List operations
    """
    
    def __init__(self, host=None, port=None, timeout=None):
        config = get_socket_config()
        self.host = host if host is not None else config.get_socket_host()
        self.port = port if port is not None else config.get_socket_port()
        self.timeout = timeout if timeout is not None else config.get_connection_timeout()
        self.socket = None
        self.connected = False
        self.lock = threading.Lock()
        
    def connect(self) -> bool:
        """Connect to the Socket server"""
        logger.info(f"🔌 [Socket] connect() called - Host: {self.host}, Port: {self.port}")
        with self.lock:
            try:
                # Close existing socket if any
                if self.socket:
                    try:
                        self.socket.close()
                    except:
                        pass
                
                self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                self.socket.settimeout(self.timeout)
                
                self.socket.connect((self.host, self.port))
                self.connected = True
                logger.info(f"✅ Connected to Socket server at {self.host}:{self.port}")
                return True
            except Exception as e:
                logger.error(f"❌ Connection failed: {e}")
                self.connected = False
                # Clean up socket on failure
                if self.socket:
                    try:
                        self.socket.close()
                    except:
                        pass
                    self.socket = None
                return False
    
    def disconnect(self):
        """Disconnect from the server"""
        with self.lock:
            if self.socket:
                try:
                    self.socket.shutdown(socket.SHUT_RDWR)
                except:
                    pass
                try:
                    self.socket.close()
                except:
                    pass
                self.socket = None
                self.connected = False
                logger.info("🔌 Disconnected from Socket server")
    
    def is_connected(self) -> bool:
        """Check if connected"""
        return self.connected and self.socket is not None
    
    def send_request(self, endpoint: str, params: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Send request and receive response"""
        logger.info(f"🔌 [Socket] send_request called for endpoint: {endpoint}")
        with self.lock:
            # Check if socket exists and is connected, if not try to connect
            if not self.connected or self.socket is None:
                logger.info(f"🔌 [Socket] Not connected, attempting to connect...")
                if not self.connect():
                    logger.error(f"❌ [Socket] Connection failed")
                    return None
                logger.info(f"✅ [Socket] Connected successfully")
            
            try:
                # Create request
                request = {
                    "endpoint": endpoint,
                    "params": params
                }
                
                # Add token to request (if available)
                token_manager = get_socket_token_manager()
                request = token_manager.add_token_to_request(request)
                
                logger.info(f"📤 [Socket] Preparing request for endpoint: {endpoint}")
                
                # Convert to JSON
                request_json = json.dumps(request, ensure_ascii=False)
                request_bytes = request_json.encode('utf-8')
                
                logger.info(f"📤 [Socket] Sending request ({len(request_bytes)} bytes)")
                
                # Send message length (4 bytes, Big Endian)
                length_bytes = len(request_bytes).to_bytes(4, byteorder='big')
                self.socket.send(length_bytes)
                
                # Send message content
                self.socket.send(request_bytes)
                
                logger.info(f"✅ [Socket] Request sent, waiting for response...")
                
                # Loop to handle broadcasts and wait for actual response
                max_broadcast_retries = 10
                broadcast_count = 0
                
                while broadcast_count < max_broadcast_retries:
                    # Receive response length
                    response_length_bytes = self.socket.recv(4)
                    if len(response_length_bytes) != 4:
                        raise Exception("Invalid response length header")
                    
                    response_length = int.from_bytes(response_length_bytes, byteorder='big')
                    logger.info(f"📥 [Socket] Response length: {response_length} bytes")
                    
                    # Receive response content
                    response_data = b''
                    while len(response_data) < response_length:
                        chunk_size = min(8192, response_length - len(response_data))
                        chunk = self.socket.recv(chunk_size)
                        if not chunk:
                            break
                        response_data += chunk
                    
                    logger.info(f"📥 [Socket] Received {len(response_data)} bytes of response data")
                    
                    # Convert to JSON
                    response = json.loads(response_data.decode('utf-8'))
                    
                    # Check if this is a broadcast message
                    if response.get('type') == 'broadcast':
                        broadcast_count += 1
                        event_type = response.get('event_type', 'unknown')
                        logger.info(f"📡 [Socket] Received broadcast message (type: {event_type}), continuing to wait for actual response... ({broadcast_count}/{max_broadcast_retries})")
                        continue  # Skip this broadcast and wait for the actual response
                    
                    # This is the actual response
                    logger.info(f"📥 [Socket] Parsed response successfully")
                    return response
                
                # If we exit the loop, we received too many broadcasts without a response
                logger.error(f"❌ [Socket] Received {broadcast_count} broadcasts without getting actual response")
                return None
                
            except Exception as e:
                logger.error(f"❌ [Socket] Error in send_request: {e}")
                self.connected = False
                if self.socket:
                    try:
                        self.socket.close()
                    except:
                        pass
                    self.socket = None
                return None
    
    def get_patient_list_safe(self, **params) -> Optional[List[Dict[str, Any]]]:
        """Get patient list with error handling"""
        try:
            response = self.send_request("GetPatientList", params)
            if response and response.get("status") == "success":
                data = response.get("data", {})
                
                # Handle different response formats
                patients = []
                if isinstance(data, dict):
                    # Format: {'data': {'patients': [...]}}
                    patients = data.get("patients", [])
                elif isinstance(data, list):
                    # Format: {'data': [...]}
                    patients = data
                
                # Process patient data
                if isinstance(patients, list):
                    processed_data = []
                    for item in patients:
                        if isinstance(item, str):
                            # Try to parse string as JSON
                            try:
                                import json
                                parsed_item = json.loads(item)
                                processed_data.append(parsed_item)
                            except:
                                # If parsing fails, create a basic dict
                                processed_data.append({"patient_name": str(item), "patient_id": str(item)})
                        elif isinstance(item, dict):
                            processed_data.append(item)
                        else:
                            # Convert other types to basic dict
                            processed_data.append({"patient_name": str(item), "patient_id": str(item)})
                    return processed_data
                else:
                    return []
            else:
                error_msg = response.get("error", "Unknown error") if response else "No response"
                logger.error(f"❌ Patient list request failed: {error_msg}")
                return None
        except Exception as e:
            logger.error(f"❌ Error getting patient list: {e}")
            return None
    
    # ========== Report Status Methods ==========
    
    def update_report_status(self, study_uid: str, new_status: str, user_id: str = None, comment: str = None) -> Optional[Dict[str, Any]]:
        """
        Update report status for a study
        
        Args:
            study_uid: Study Instance UID
            new_status: New status value
            user_id: Optional user ID who made the change
            comment: Optional comment for the change
            
        Returns:
            Response dict or None on error
        """
        try:
            params = {
                "study_uid": study_uid,
                "new_status": new_status
            }
            if user_id:
                params["user_id"] = user_id
            if comment:
                params["comment"] = comment
            
            response = self.send_request("UpdateReportStatus", params)
            
            if response and response.get("status") == "success":
                return response
            else:
                # Better error extraction with full response logging
                if response:
                    error_msg = response.get("error") or response.get("message") or response.get("msg", "Unknown error")
                    logger.error(f"Update report status failed: {error_msg}")
                    logger.error(f"Full response for debugging: {response}")
                else:
                    error_msg = "No response"
                    logger.error(f"Update report status failed: {error_msg}")
                return None
        except Exception as e:
            logger.error(f"Exception in update_report_status: {e}")
            return None
    
    def get_report_status(self, study_uid: str) -> Optional[Dict[str, Any]]:
        """
        Get current report status for a study
        
        Args:
            study_uid: Study Instance UID
            
        Returns:
            Response dict with status or None on error
        """
        try:
            params = {"study_uid": study_uid}
            response = self.send_request("GetReportStatus", params)
            
            if response and response.get("status") == "success":
                return response
            else:
                error_msg = response.get("error", "Unknown error") if response else "No response"
                logger.error(f"Get report status failed: {error_msg}")
                return None
        except Exception as e:
            logger.error(f"Error getting report status: {e}")
            return None
    
    def get_report_status_history(self, study_uid: str) -> Optional[Dict[str, Any]]:
        """
        Get report status history for a study
        
        Args:
            study_uid: Study Instance UID
            
        Returns:
            Response dict with history or None on error
        """
        try:
            params = {"study_uid": study_uid}
            response = self.send_request("GetReportStatusHistory", params)
            if response and response.get("status") == "success":
                return response
            else:
                error_msg = response.get("error", "Unknown error") if response else "No response"
                logger.error(f"❌ Get report status history failed: {error_msg}")
                return None
        except Exception as e:
            logger.error(f"❌ Error getting report status history: {e}")
            return None
    
    def get_studies_by_report_status(self, report_status: str, patient_id: str = None, 
                                     start_date: str = None, end_date: str = None,
                                     limit: int = 50, offset: int = 0,
                                     sort_by: str = "StudyDate", sort_order: str = "desc") -> Optional[Dict[str, Any]]:
        """
        Get studies filtered by report status
        
        Args:
            report_status: Status to filter by
            patient_id: Optional patient ID filter
            start_date: Optional start date (YYYYMMDD)
            end_date: Optional end date (YYYYMMDD)
            limit: Maximum number of results
            offset: Offset for pagination
            sort_by: Field to sort by
            sort_order: Sort order (asc/desc)
            
        Returns:
            Response dict with studies or None on error
        """
        try:
            params = {
                "report_status": report_status,
                "limit": limit,
                "offset": offset,
                "sort_by": sort_by,
                "sort_order": sort_order
            }
            if patient_id:
                params["patient_id"] = patient_id
            if start_date:
                params["start_date"] = start_date
            if end_date:
                params["end_date"] = end_date
            
            response = self.send_request("GetStudiesByReportStatus", params)
            if response and response.get("status") == "success":
                return response
            else:
                error_msg = response.get("error", "Unknown error") if response else "No response"
                logger.error(f"❌ Get studies by report status failed: {error_msg}")
                return None
        except Exception as e:
            logger.error(f"❌ Error getting studies by report status: {e}")
            return None
    
    def __enter__(self):
        """Context manager entry"""
        self.connect()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit"""
        self.disconnect()
    
    def __del__(self):
        """Destructor to ensure socket is closed"""
        try:
            self.disconnect()
        except:
            pass


class SocketConnectionPool:
    """
    Simple connection pool for socket connections
    """
    
    def __init__(self, host: str, port: int, pool_size: int = 5):
        self.host = host
        self.port = port
        self.pool_size = pool_size
        self.connections = []
        self.lock = threading.Lock()
        
        # Initialize connections
        for _ in range(pool_size):
            client = PatientListSocketClient(host, port)
            self.connections.append(client)
    
    def get_connection(self) -> Optional[PatientListSocketClient]:
        """Get a connection from the pool"""
        with self.lock:
            if self.connections:
                return self.connections.pop()
            else:
                # Create new connection if pool is empty
                return PatientListSocketClient(self.host, self.port)
    
    def return_connection(self, client: PatientListSocketClient):
        """Return a connection to the pool"""
        with self.lock:
            if len(self.connections) < self.pool_size:
                self.connections.append(client)
            else:
                # Pool is full, disconnect the client
                client.disconnect()
    
    def close_all(self):
        """Close all connections in the pool"""
        with self.lock:
            for client in self.connections:
                try:
                    client.disconnect()
                except:
                    pass
            self.connections.clear()
    
    def __del__(self):
        """Destructor to ensure all connections are closed"""
        try:
            self.close_all()
        except:
            pass
