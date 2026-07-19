# -*- coding: utf-8 -*-

import logging
import os
import time
import threading
from typing import Dict, List, Any, Optional, Callable
from PySide6.QtCore import QObject, Signal

from .socket_client import PatientListSocketClient, SocketConnectionPool
from .socket_patient_service import get_socket_patient_service
from modules.network.socket_config import get_socket_config

logger = logging.getLogger(__name__)


# --- Report-status circuit breaker (added 2026-06-16) -------------------------
# The PACS server does not answer the GetReportStatus endpoint (documented as a
# benign server-side gap). Because report-status calls reuse the SHARED
# PatientListSocketClient, every unanswered call holds that client's RLock for up
# to the socket timeout (~30s), blocking GUI-thread patient/thumbnail socket calls
# (observed 1.3-1.7s main-thread stalls) and emitting ~30s-cadence ERROR spam.
# After a few consecutive failures we open a breaker and short-circuit
# get_report_status() for a cooldown, so the shared lock is never held for an
# endpoint the server isn't answering. Self-heals on the next success.
# Reversible: set AIPACS_REPORTSTATUS_BREAKER=0 to restore the prior behavior.
_RS_BREAKER_ENABLED = os.environ.get("AIPACS_REPORTSTATUS_BREAKER", "1") != "0"
try:
    _RS_BREAKER_THRESHOLD = max(1, int(os.environ.get("AIPACS_REPORTSTATUS_BREAKER_FAILS", "3")))
except ValueError:
    _RS_BREAKER_THRESHOLD = 3
try:
    _RS_BREAKER_COOLDOWN_S = max(5.0, float(os.environ.get("AIPACS_REPORTSTATUS_BREAKER_COOLDOWN", "300")))
except ValueError:
    _RS_BREAKER_COOLDOWN_S = 300.0


# Valid report statuses
VALID_STATUSES = [
    "pending",
    "awaiting_physician_approval",
    "awaiting_secretary_approval",
    "awaiting_approval",
    "physician_approved",
    "secretary_approved",
    "completed",
    "archived"
]

# Status set by the Patient-Tab Cloud "Sync Patient Data with Server" action.
# 2026-07-15 (user directive): a cloud sync hands the study to the secretary with
# a CLEAN approval slate — status "Awaiting Secretary Approval" with BOTH approval
# flags cleared (the physician has synced the study but has NOT formally approved
# yet). This intentionally reverses the 2026-06-22 "physician_approved" default.
# Single source of truth: both the sync service and the toolbar's post-sync local
# update read this constant so they can never drift apart. Override / kill-switch:
# set env AIPACS_SYNC_REPORT_STATUS (e.g. to "physician_approved" to restore the
# 2026-06-22 value). See docs/reports/PATIENT_TAB_STATUS_SYNC_CONTROLS_AUDIT_2026-07-15.md.
SYNC_REPORT_STATUS = os.environ.get("AIPACS_SYNC_REPORT_STATUS", "awaiting_secretary_approval")
if SYNC_REPORT_STATUS not in VALID_STATUSES:
    logger.warning(
        "Invalid AIPACS_SYNC_REPORT_STATUS=%r; falling back to awaiting_secretary_approval",
        SYNC_REPORT_STATUS,
    )
    SYNC_REPORT_STATUS = "awaiting_secretary_approval"

# Report statuses with English labels
REPORT_STATUSES = {
    "pending": "Pending",
    "awaiting_physician_approval": "Awaiting Physician Approval",
    "awaiting_secretary_approval": "Awaiting Secretary Approval",
    "awaiting_approval": "Awaiting Approval",
    "physician_approved": "Physician Approved",
    "secretary_approved": "Secretary Approved",
    "completed": "Completed",
    "archived": "Archived"
}

# Status colors for UI
STATUS_COLORS = {
    "pending": "#f59e0b",  # amber
    "awaiting_physician_approval": "#3b82f6",  # blue
    "awaiting_secretary_approval": "#8b5cf6",  # purple
    "awaiting_approval": "#6366f1",  # indigo
    "physician_approved": "#10b981",  # green (different from secretary)
    "secretary_approved": "#06b6d4",  # cyan (different from physician)
    "completed": "#059669",  # emerald
    "archived": "#6b7280"  # gray
}


# --- Status -> INO reception approvalFlags mapping (2026-07-09) ---------------
# INO Reception renders the patient/report state from ``report.approvalFlags``
# (physicianApproved / secretaryApproved), NOT from the raw ``report.status``
# string. The ``/api/pacs/update-report`` call historically sent only
# ``status``, so a DOWNGRADE (e.g. Completed -> Awaiting Physician) changed
# ``report.status`` but left the approval flags set, and INO kept showing the
# report as approved (root cause + live proof reception 46682:
# docs/reports/AINO_RECEPTION_STATUS_SYNC_REVIEW_2026-07-09.md). We now send
# ``approvalFlags`` consistent with the chosen status so INO's displayed status
# follows a downgrade too. Flag-gated (default ON); ``=0`` restores the legacy
# status-only body. Harmless if the server ignores the field.
UPDATE_REPORT_APPROVAL_FLAGS = (
    os.environ.get("AIPACS_UPDATE_REPORT_APPROVAL_FLAGS", "1") or "1"
).strip() != "0"

# Physician has signed off at/after the physician-approved stage. Secretary has
# finalized at/after the secretary-approved stage. Everything else (pending /
# awaiting_*) is not yet approved.
#
# 2026-07-15 (user directive): "Awaiting Secretary Approval" now clears BOTH
# approval flags — it is a clean slate handed to the secretary, NOT "physician
# already approved". This makes the Cloud sync (which sets awaiting_secretary_
# approval) produce physicianApproved=false, secretaryApproved=false, and is
# applied GLOBALLY (the dropdown / editor use the same map). Kill switch
# AIPACS_AWAITING_SECRETARY_BOTH_FALSE=0 restores the legacy meaning
# (awaiting_secretary_approval ⇒ physicianApproved=true).
_AWAITING_SECRETARY_BOTH_FALSE = (
    os.environ.get("AIPACS_AWAITING_SECRETARY_BOTH_FALSE", "1") or "1"
).strip() != "0"

_PHYSICIAN_APPROVED_STATES = {
    "physician_approved",
    "secretary_approved",
    "completed",
    "archived",
}
if not _AWAITING_SECRETARY_BOTH_FALSE:
    # Legacy: physician approved, awaiting secretary.
    _PHYSICIAN_APPROVED_STATES.add("awaiting_secretary_approval")
_SECRETARY_APPROVED_STATES = {"secretary_approved", "completed", "archived"}


def approval_flags_for_status(status: str) -> Dict[str, bool]:
    """Map an internal report status to INO's ``approvalFlags`` booleans.

    Pure / no I/O. Returns
    ``{"physicianApproved": bool, "secretaryApproved": bool}`` so that a report
    DOWNGRADE clears the flags INO renders the patient status from — the fix for
    "status not updating on the reception side". A forward transition to
    completed/approved sets them. Unknown statuses map to False/False (safe).
    """
    s = (status or "").strip()
    return {
        "physicianApproved": s in _PHYSICIAN_APPROVED_STATES,
        "secretaryApproved": s in _SECRETARY_APPROVED_STATES,
    }


class SocketReportStatusService(QObject):
    """
    Socket-based Report Status Service for PACS Client
    
    This service provides an interface between the UI and the Socket server
    for managing report statuses of studies.
    """
    
    # Signals
    statusUpdated = Signal(str, str, str)  # study_uid, old_status, new_status
    statusReceived = Signal(str, dict)  # study_uid, status_data
    historyReceived = Signal(str, list)  # study_uid, history_list
    studiesReceived = Signal(list, dict)  # studies list, metadata
    statusError = Signal(str, str)  # study_uid, error_message
    connectionStatusChanged = Signal(bool)  # connection status
    
    def __init__(self, parent=None):
        """
        Initialize the Socket Report Status Service
        
        Args:
            parent: Parent QObject
        """
        super().__init__(parent)
        
        # Get configuration
        self.config = get_socket_config()
        
        # Initialize client
        self.client = None
        self.connection_pool = None
        
        # Setup connection pool if enabled
        if self.config.get("use_connection_pool", False):
            self._setup_connection_pool()

        # Circuit-breaker state: protects the SHARED socket client from being held
        # ~30s on the unanswered GetReportStatus endpoint (see module header).
        self._rs_breaker_lock = threading.Lock()
        self._rs_consecutive_failures = 0
        self._rs_breaker_open_until = 0.0
        self._rs_breaker_logged = False
    
    def reload_connection(self):
        """Reload connection pool"""
        self._setup_connection_pool()
    
    def _setup_connection_pool(self):
        """Setup connection pool for better performance"""
        try:
            host = self.config.get_socket_host()
            port = self.config.get_socket_port()
            pool_size = self.config.get_connection_pool_size()
            
            self.connection_pool = SocketConnectionPool(host, port, pool_size)
            logger.info(f"✅ Report Status Service: Connection pool setup with {pool_size} connections")
        except Exception as e:
            logger.error(f"❌ Failed to setup connection pool: {e}")
            self.connection_pool = None
    
    def _get_client(self) -> Optional[PatientListSocketClient]:
        """
        Get a client instance (from pool or create new)
        Reuses existing connection from socket_patient_service if available
        
        Returns:
            PatientListSocketClient or None
        """
        # Try to reuse client from socket_patient_service first
        try:
            patient_service = get_socket_patient_service()
            if patient_service and patient_service.client:
                return patient_service.client
        except Exception as e:
            logger.warning(f"Could not get client from patient service: {e}")
        
        # Fallback to own client
        if self.connection_pool:
            return self.connection_pool.get_connection()
        else:
            if not self.client:
                self.client = PatientListSocketClient(
                    host=self.config.get_socket_host(),
                    port=self.config.get_socket_port(),
                    timeout=self.config.get_connection_timeout()
                )
                # Try to connect immediately
                if not self.client.is_connected():
                    self.client.connect()
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
                    logger.info("✅ Report Status Service: Connected to Socket server")
                    return True
                else:
                    self.connectionStatusChanged.emit(False)
                    logger.error("❌ Report Status Service: Failed to connect to Socket server")
                    return False
            else:
                logger.error("❌ Report Status Service: Failed to get client instance")
                return False
        except Exception as e:
            logger.error(f"❌ Report Status Service: Connection error: {e}")
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
            logger.info("🔌 Report Status Service: Disconnected from Socket server")
        except Exception as e:
            logger.error(f"❌ Report Status Service: Disconnect error: {e}")
    
    def update_report_status(self, study_uid: str, new_status: str, 
                            user_id: str = None, comment: str = None) -> Optional[Dict[str, Any]]:
        """
        Update report status for a study
        
        Args:
            study_uid: Study Instance UID
            new_status: New status value (must be one of VALID_STATUSES)
            user_id: Optional user ID who made the change
            comment: Optional comment for the change
            
        Returns:
            Response dict or None on error
        """
        # Validate status
        if new_status not in VALID_STATUSES:
            error_msg = f"Invalid status: {new_status}. Valid statuses: {VALID_STATUSES}"
            logger.error(f"❌ {error_msg}")
            self.statusError.emit(study_uid, error_msg)
            return None
        
        client = None
        try:
            client = self._get_client()
            if not client:
                error_msg = "Failed to get client instance"
                logger.error(error_msg)
                self.statusError.emit(study_uid, error_msg)
                return None
            
            # Ensure client is connected (reuse existing connection if available)
            if not client.is_connected():
                if not client.connect():
                    error_msg = "Failed to connect to server"
                    logger.error(error_msg)
                    self.statusError.emit(study_uid, error_msg)
                    return None
            
            response = client.update_report_status(study_uid, new_status, user_id, comment)
            
            if response:
                old_status = response.get("previous_status", "unknown")
                self.statusUpdated.emit(study_uid, old_status, new_status)
                return response
            else:
                error_msg = "Update failed - no response from server"
                logger.error(error_msg)
                self.statusError.emit(study_uid, error_msg)
                return None
                
        except Exception as e:
            error_msg = f"Error updating report status: {str(e)}"
            logger.error(f"❌ {error_msg}")
            self.statusError.emit(study_uid, error_msg)
            return None
        finally:
            if client:
                self._return_client(client)
    
    # --- Circuit-breaker helpers (added 2026-06-16) ---------------------------
    def _rs_breaker_is_open(self) -> bool:
        """True while the breaker is open (skip the call, never touch the lock)."""
        if not _RS_BREAKER_ENABLED:
            return False
        with self._rs_breaker_lock:
            return bool(self._rs_breaker_open_until) and time.monotonic() < self._rs_breaker_open_until

    def _rs_note_success(self) -> None:
        """Reset the breaker after the server answers GetReportStatus."""
        if not _RS_BREAKER_ENABLED:
            return
        with self._rs_breaker_lock:
            if self._rs_consecutive_failures or self._rs_breaker_open_until:
                logger.info("Report-status endpoint answered again; circuit breaker reset")
            self._rs_consecutive_failures = 0
            self._rs_breaker_open_until = 0.0
            self._rs_breaker_logged = False

    def _rs_note_failure(self) -> None:
        """Count a consecutive failure and open the breaker past the threshold."""
        if not _RS_BREAKER_ENABLED:
            return
        with self._rs_breaker_lock:
            self._rs_consecutive_failures += 1
            if self._rs_consecutive_failures >= _RS_BREAKER_THRESHOLD:
                self._rs_breaker_open_until = time.monotonic() + _RS_BREAKER_COOLDOWN_S
                if not self._rs_breaker_logged:
                    logger.warning(
                        "GetReportStatus unanswered %dx consecutively; opening circuit "
                        "breaker for %.0fs to protect the shared socket lock "
                        "(set AIPACS_REPORTSTATUS_BREAKER=0 to disable)",
                        self._rs_consecutive_failures, _RS_BREAKER_COOLDOWN_S,
                    )
                    self._rs_breaker_logged = True

    def get_report_status(self, study_uid: str) -> Optional[Dict[str, Any]]:
        """
        Get current report status for a study

        Args:
            study_uid: Study Instance UID

        Returns:
            Response dict with status or None on error
        """
        # Circuit breaker: while open, skip the call entirely so the shared socket
        # client's lock is never held ~30s on an endpoint the server isn't answering.
        if self._rs_breaker_is_open():
            return None

        client = None
        try:
            client = self._get_client()
            if not client:
                return None

            response = client.get_report_status(study_uid)

            if response:
                self._rs_note_success()
                # Extract status from response (check multiple possible locations)
                report_status = (
                    response.get("report_status") or
                    response.get("reportStatus") or
                    response.get("data", {}).get("report_status") or
                    response.get("data", {}).get("reportStatus") or
                    "pending"
                )

                status_data = {
                    "report_status": report_status,
                    "updated_at": response.get("updated_at") or response.get("data", {}).get("updated_at")
                }
                self.statusReceived.emit(study_uid, status_data)
                return response
            else:
                self._rs_note_failure()
                return None

        except Exception as e:
            self._rs_note_failure()
            logger.error(f"Error getting report status: {e}")
            return None
        finally:
            if client:
                self._return_client(client)
    
    def get_report_status_history(self, study_uid: str) -> Optional[Dict[str, Any]]:
        """
        Get report status history for a study
        
        Args:
            study_uid: Study Instance UID
            
        Returns:
            Response dict with history or None on error
        """
        client = None
        try:
            client = self._get_client()
            if not client:
                return None
            
            response = client.get_report_status_history(study_uid)
            if response:
                history = response.get("history", [])
                self.historyReceived.emit(study_uid, history)
                return response
            else:
                return None
                
        except Exception as e:
            logger.error(f"❌ Error getting report status history: {e}")
            return None
        finally:
            if client:
                self._return_client(client)
    
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
        # Validate status
        if report_status not in VALID_STATUSES:
            logger.error(f"❌ Invalid status: {report_status}")
            return None
        
        client = None
        try:
            client = self._get_client()
            if not client:
                return None
            
            logger.info(f"🔍 Getting studies with status: {report_status}")
            response = client.get_studies_by_report_status(
                report_status, patient_id, start_date, end_date,
                limit, offset, sort_by, sort_order
            )
            
            if response:
                studies = response.get("studies", [])
                metadata = {
                    "total_count": response.get("total_count", 0),
                    "returned_count": response.get("returned_count", len(studies)),
                    "offset": response.get("offset", offset),
                    "limit": response.get("limit", limit)
                }
                self.studiesReceived.emit(studies, metadata)
                return response
            else:
                return None
                
        except Exception as e:
            logger.error(f"❌ Error getting studies by report status: {e}")
            return None
        finally:
            if client:
                self._return_client(client)
    
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
            
            connected = client.connect()
            if connected:
                logger.info("✅ Report Status Service: Connection test successful")
                return True
            else:
                logger.error("❌ Report Status Service: Connection test failed")
                return False
        except Exception as e:
            logger.error(f"❌ Report Status Service: Connection test error: {e}")
            return False
        finally:
            if client:
                self._return_client(client)
    
    def cleanup(self):
        """Cleanup resources"""
        try:
            self.disconnect_from_server()
            if self.client:
                try:
                    self.client.disconnect()
                except:
                    pass
                self.client = None
            logger.info("🧹 Report Status Service cleaned up")
        except Exception as e:
            logger.error(f"❌ Cleanup error: {e}")
    
    def __del__(self):
        """Destructor to ensure cleanup"""
        try:
            self.cleanup()
        except:
            pass


# Global service instance
_report_status_service = None


def get_report_status_service() -> SocketReportStatusService:
    """
    Get global Report Status Service instance
    
    Returns:
        SocketReportStatusService: Global service instance
    """
    global _report_status_service
    if _report_status_service is None:
        _report_status_service = SocketReportStatusService()
    else:
        _report_status_service.reload_connection()
    return _report_status_service

