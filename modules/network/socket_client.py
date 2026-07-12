# -*- coding: utf-8 -*-

import socket
import json
import logging
from typing import Dict, List, Any, Optional
import threading
import time

from modules.network.socket_config import get_socket_config
from modules.network.socket_token_manager import get_socket_token_manager
from modules.network.series_identity import normalize_series_entries

logger = logging.getLogger(__name__)

_LARGE_PAYLOAD_ENDPOINTS = {
    "GetStudyThumbnails",
    "GetStudyInfo",
    "QuerySeriesThumbnails",
}


def _normalize_series_identity(data: Any, *, endpoint: str, study_uid: str) -> None:
    """Series-number normalization at the SINGLE socket ingestion boundary.

    Every consumer of server series metadata — the download manager
    (``GrpcMetadataClient``, socket-backed), the home panel, the patient-tab
    thumbnails, previous-exams, the database writer — reaches the server through
    ``get_study_thumbnails`` / ``query_series_thumbnails``. Normalizing here (and
    ONLY here) means no downstream code can ever see a non-numeric
    ``series_number`` such as the literal string ``"None"`` that a device with a
    missing SeriesNumber (0020,0011) produces — the defect that made an entire
    radiography study fail to download (see modules/network/series_identity.py).

    Healthy payloads are left byte-identical and this is a no-op. Never raises.
    """
    try:
        repaired = normalize_series_entries(data)
        if repaired:
            logger.warning(
                "[SERIES_NUMBER_NORMALIZE] endpoint=%s study=%s repaired=%d "
                "reason=server_sent_unusable_series_number "
                "(missing/empty SeriesNumber on the source device) — assigned "
                "deterministic synthetic numbers so the study stays usable",
                endpoint,
                str(study_uid or "")[:48],
                repaired,
            )
    except Exception as exc:  # pragma: no cover - must never break a good fetch
        logger.debug("series-number normalization skipped: %s", exc)

# ── MongoDB $sortArray compatibility fallback (incident 2026-06-15) ───────────
# The backend's GetPatientList aggregation uses $sortArray, which is unsupported
# on MongoDB < 5.2: the whole pipeline fails with InvalidPipelineOperator
# (code 168) and the client got NO patient data. The true fix is server-side
# (drop $sortArray / upgrade MongoDB); on the client we degrade gracefully so a
# legacy server still yields a usable list instead of a hard failure.
#
# When (and ONLY when) that SPECIFIC error is seen, the client progressively
# degrades the query, then caches the first working mode so it is not
# re-discovered on every request. A healthy/modern server never triggers this —
# the normal request succeeds and the fallback stays completely inert. Unrelated
# failures (timeouts, auth) are NOT degraded.
#   "normal"        -> the request as-is (default)
#   "compatibility" -> ask the server for a legacy-safe aggregation
#   "simple"        -> ask the server to skip its sort; the client sorts the rows
_PL_FALLBACK_MODES = [
    ("normal", {}, False),
    ("compatibility", {"compatibility_mode": True, "mongodb_compatibility": True}, False),
    ("simple", {"simple_query": True, "no_sort": True}, True),  # True => client-side sort
]
_PL_MODE_BY_NAME = {name: (flags, csort) for name, flags, csort in _PL_FALLBACK_MODES}
# Process-wide cache of the first mode that returned data (one round-trip after
# discovery). A restart re-discovers, so a later server upgrade self-heals.
_PATIENT_LIST_FALLBACK_MODE = None  # type: Optional[str]
_PATIENT_LIST_FALLBACK_LOCK = threading.Lock()


def _is_sortarray_compat_error(response: Optional[Dict[str, Any]]) -> bool:
    """True ONLY for the MongoDB $sortArray / InvalidPipelineOperator failure —
    never for timeouts or unrelated errors (those must not trigger degradation)."""
    if not isinstance(response, dict):
        return False
    blob = " ".join(
        str(response.get(k, "")) for k in ("error", "message", "codeName", "code", "detail")
    ).lower()
    return (
        "sortarray" in blob
        or "invalidpipelineoperator" in blob
        or "code: 168" in blob
        or "unrecognized expression '$sort" in blob
    )


def _patient_list_client_sort(patients: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Best-effort newest-first sort for the no-server-sort path. The home table
    re-sorts for display, so this only needs a sensible default and must never
    raise."""
    def _key(p):
        if isinstance(p, dict):
            for f in ("study_date", "latest_study_date", "date", "StudyDate"):
                v = p.get(f)
                if v:
                    return str(v)
        return ""
    try:
        return sorted(patients, key=_key, reverse=True)
    except Exception:
        return patients


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
        self.lock = threading.RLock()
        
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
    
    def _recv_exact(self, size: int) -> bytes:
        """Receive exactly *size* bytes from the socket, accumulating partial reads."""
        if size <= 0:
            return b''

        buf = bytearray(size)
        pos = 0
        chunk_size = 262144 if size > 1048576 else 65536
        while pos < size:
            nbytes = self.socket.recv_into(memoryview(buf)[pos:], min(chunk_size, size - pos))
            if not nbytes:
                # connection closed before full payload
                return bytes(buf[:pos])
            pos += nbytes
        return bytes(buf)
    
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
                
                logger.debug(f"📤 [Socket] Preparing request for endpoint: {endpoint}")
                
                # Convert to JSON
                request_json = json.dumps(request, ensure_ascii=False)
                request_bytes = request_json.encode('utf-8')
                
                logger.debug(f"📤 [Socket] Sending request ({len(request_bytes)} bytes)")
                
                # Send message length (4 bytes, Big Endian) + content
                # Use sendall to guarantee complete delivery
                length_bytes = len(request_bytes).to_bytes(4, byteorder='big')
                self.socket.sendall(length_bytes)
                self.socket.sendall(request_bytes)
                _t_send = time.perf_counter()  # [NET_TIMING] request fully sent

                logger.debug(f"📤 [Socket] Request sent, waiting for response...")
                
                # Loop to handle broadcasts and wait for actual response.
                # Use a time deadline (based on socket timeout) instead of a small
                # fixed retry count to avoid dropping valid responses under bursty
                # broadcast traffic.
                max_broadcast_retries = 200
                broadcast_count = 0
                response_deadline = time.monotonic() + float(self.timeout or 10.0)

                while time.monotonic() < response_deadline and broadcast_count < max_broadcast_retries:
                    # Receive response length (exactly 4 bytes)
                    response_length_bytes = self._recv_exact(4)
                    if not response_length_bytes or len(response_length_bytes) != 4:
                        raise Exception("Invalid response length header")
                    
                    response_length = int.from_bytes(response_length_bytes, byteorder='big')
                    
                    # Validate response size to prevent excessive allocation.
                    # Study thumbnail payloads can legitimately exceed 50MB when
                    # base64 thumbnails are requested for many series.
                    max_response_bytes = 50 * 1024 * 1024
                    if endpoint in _LARGE_PAYLOAD_ENDPOINTS:
                        # Hermes uses a 500MB guard for study thumbnail payloads.
                        # Keep parity to avoid rejecting valid large studies.
                        max_response_bytes = 500 * 1024 * 1024
                    if response_length > max_response_bytes:
                        raise Exception(f"Response too large: {response_length} bytes")
                    
                    logger.debug(f"📥 [Socket] Response length: {response_length} bytes")
                    _t_hdr = time.perf_counter()  # [NET_TIMING] length header in hand = server started replying

                    # Receive response content (exact byte count)
                    response_data = self._recv_exact(response_length)
                    if not response_data or len(response_data) != response_length:
                        raise Exception("Incomplete response data")
                    _t_body = time.perf_counter()  # [NET_TIMING] full payload received

                    logger.debug(f"📥 [Socket] Received {len(response_data)} bytes of response data")

                    # Convert to JSON. Tolerant decode: a non-UTF-8 byte in a patient
                    # name / description field (Persian/Western-European source data
                    # encoded Windows-1256 / Latin-1) must not crash the patient-list /
                    # thumbnail parse. Strict UTF-8 first (normal case), then replacement
                    # so json.loads still succeeds; only that field degrades.
                    try:
                        _payload_text = response_data.decode('utf-8')
                    except UnicodeDecodeError as _dec_exc:
                        logger.warning(
                            f"⚠️ [Socket] Non-UTF-8 byte in response ({_dec_exc}); "
                            f"decoding with replacement so the parse proceeds"
                        )
                        _payload_text = response_data.decode('utf-8', errors='replace')
                    response = json.loads(_payload_text)
                    _t_parse = time.perf_counter()  # [NET_TIMING] JSON parsed

                    # Check if this is a broadcast message
                    if response.get('type') == 'broadcast':
                        broadcast_count += 1
                        event_type = response.get('event_type', 'unknown')
                        logger.debug(
                            f"📡 [Socket] Broadcast message (type: {event_type}), waiting for response... "
                            f"({broadcast_count}/{max_broadcast_retries})"
                        )
                        continue
                    
                    # This is the actual response.
                    # [NET_TIMING] (2026-06-09) split the cost: server_wait = time
                    # from request-sent to the server's first reply byte (server-side
                    # compute); transfer = time to receive the payload over the wire
                    # (network + payload size); parse = json.loads. payload_bytes is
                    # the exact response size — confirms whether the patient list is
                    # actually small.
                    try:
                        logger.warning(
                            "[NET_TIMING] endpoint=%s payload_bytes=%d server_wait_ms=%.0f "
                            "transfer_ms=%.0f parse_ms=%.0f total_ms=%.0f",
                            endpoint, int(response_length),
                            (_t_hdr - _t_send) * 1000.0,
                            (_t_body - _t_hdr) * 1000.0,
                            (_t_parse - _t_body) * 1000.0,
                            (_t_parse - _t_send) * 1000.0,
                        )
                    except Exception:
                        pass
                    logger.debug(f"📥 [Socket] Parsed response successfully")
                    return response
                
                # If we exit the loop, we timed out or saw excessive broadcasts without a response.
                logger.error(
                    f"❌ [Socket] Did not receive endpoint response in time "
                    f"(broadcasts={broadcast_count}, timeout={self.timeout}s)"
                )
                return None
                
            except Exception as e:
                logger.error(f"❌ [Socket] Error in send_request endpoint={endpoint}: {e}")
                self.connected = False
                if self.socket:
                    try:
                        self.socket.close()
                    except:
                        pass
                    self.socket = None
                return None
    
    def _extract_patient_list(self, response: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Normalize the GetPatientList payload into a list of patient dicts.
        Handles {'data': {'patients': [...]}} and {'data': [...]} and JSON-string
        items (unchanged from the original processing)."""
        data = response.get("data", {})
        patients = []
        if isinstance(data, dict):
            patients = data.get("patients", [])
        elif isinstance(data, list):
            patients = data
        if not isinstance(patients, list):
            return []
        processed = []
        for item in patients:
            if isinstance(item, str):
                try:
                    processed.append(json.loads(item))
                except Exception:
                    processed.append({"patient_name": str(item), "patient_id": str(item)})
            elif isinstance(item, dict):
                processed.append(item)
            else:
                processed.append({"patient_name": str(item), "patient_id": str(item)})
        return processed

    def get_patient_list_safe(self, **params) -> Optional[List[Dict[str, Any]]]:
        """Get patient list, with a MongoDB $sortArray compatibility fallback.

        On a healthy/modern server the normal request succeeds and nothing below
        changes. ONLY on the specific InvalidPipelineOperator/$sortArray failure
        does the client progressively degrade the query (compatibility ->
        simple/no_sort + client-side sort), caching the first working mode so it
        is reused. Unrelated failures (timeouts, auth) are returned as-is (no
        degradation). See docs MONGODB_COMPATIBILITY_INCIDENT_2026-06-15.
        """
        global _PATIENT_LIST_FALLBACK_MODE

        # Where to start: explicit config pin/force > cached discovered mode > normal.
        forced = None
        force_compat = False
        try:
            cfg = get_socket_config()
            forced = cfg.get_patient_list_fallback_mode()
            force_compat = cfg.is_force_compatibility_mode()
        except Exception:
            pass

        if forced in _PL_MODE_BY_NAME and forced != "normal":
            modes_to_try = [forced]               # pinned by config: only that mode
        else:
            names = [m[0] for m in _PL_FALLBACK_MODES]
            start = "compatibility" if force_compat else (
                _PATIENT_LIST_FALLBACK_MODE if _PATIENT_LIST_FALLBACK_MODE in _PL_MODE_BY_NAME else None
            )
            start_idx = names.index(start) if start in names else 0
            modes_to_try = names[start_idx:]

        last_response = None
        for mode_name in modes_to_try:
            flags, client_sort = _PL_MODE_BY_NAME[mode_name]
            req = dict(params)
            req.update(flags)
            try:
                response = self.send_request("GetPatientList", req)
            except Exception as e:
                logger.error(f"❌ Error getting patient list (mode={mode_name}): {e}")
                return None
            last_response = response

            if response and response.get("status") == "success":
                patients = self._extract_patient_list(response)
                if client_sort:
                    patients = _patient_list_client_sort(patients)
                if mode_name != "normal":
                    with _PATIENT_LIST_FALLBACK_LOCK:
                        _PATIENT_LIST_FALLBACK_MODE = mode_name
                    logger.info(
                        f"✅ Patient list recovered via compatibility fallback mode='{mode_name}'"
                    )
                return patients

            # Escalate ONLY on the specific $sortArray / InvalidPipelineOperator error.
            if _is_sortarray_compat_error(response):
                logger.warning(
                    f"⚠️ GetPatientList $sortArray incompatibility (mode={mode_name}); "
                    f"degrading query and retrying"
                )
                continue
            # Any other failure (timeout/auth/etc.) -> do not degrade further.
            break

        error_msg = (
            last_response.get("error", "Unknown error")
            if isinstance(last_response, dict) else "No response"
        )
        logger.error(f"❌ Patient list request failed: {error_msg}")
        return None

    def get_study_thumbnails(
        self,
        study_instance_uid: str,
        *,
        include_base64: bool = True,
        include_image_data: bool = False,
    ) -> Optional[Dict[str, Any]]:
        """Fetch study thumbnails/series metadata via socket endpoint.

        Returns normalized ``data`` payload on success, otherwise ``None``.
        """
        try:
            params: Dict[str, Any] = {
                "study_instance_uid": str(study_instance_uid or "").strip(),
                "include_base64": bool(include_base64),
                "include_image_data": bool(include_image_data),
            }
            if not params["study_instance_uid"]:
                return None

            response = None
            for attempt in range(2):
                response = self.send_request("GetStudyThumbnails", params)
                if response:
                    break
                if attempt == 0:
                    time.sleep(0.2)
            if not response:
                return None

            status = str(response.get("status", "") or "").lower()
            if status not in {"success", "ok"} and not bool(response.get("success")):
                return None

            data = response.get("data")
            if isinstance(data, dict):
                # contentVersion (server's monotonic per-study content counter) is
                # the authoritative staleness signal. The server may place it at the
                # response top level or inside data — surface it on the returned dict
                # either way. Absent => callers treat None as "unknown" and fall back.
                if "content_version" not in data:
                    # Accept both snake_case and the server's camelCase spelling,
                    # at the response top level OR inside data — otherwise a casing
                    # mismatch would silently disable the whole staleness gate.
                    cv = response.get("content_version")
                    if cv is None:
                        cv = response.get("contentVersion")
                    if cv is None:
                        cv = data.get("contentVersion")
                    if cv is not None:
                        data["content_version"] = cv
                _normalize_series_identity(data, endpoint="GetStudyThumbnails",
                                           study_uid=params["study_instance_uid"])
                return data
            return None
        except Exception as e:
            logger.error(f"❌ Error getting study thumbnails via socket: {e}")
            return None

    def get_study_info(self, study_instance_uid: str) -> Optional[Dict[str, Any]]:
        """Fetch lightweight study metadata via socket endpoint.

        Returns normalized ``data`` payload on success, otherwise ``None``.
        """
        try:
            uid = str(study_instance_uid or "").strip()
            if not uid:
                return None

            response = None
            for attempt in range(2):
                response = self.send_request("GetStudyInfo", {"study_instance_uid": uid})
                if response:
                    break
                if attempt == 0:
                    time.sleep(0.2)
            if not response:
                return None

            status = str(response.get("status", "") or "").lower()
            if status not in {"success", "ok"} and not bool(response.get("success")):
                return None

            data = response.get("data")
            return data if isinstance(data, dict) else None
        except Exception as e:
            logger.error(f"❌ Error getting study info via socket: {e}")
            return None

    def get_patient_status(self, patient_id) -> Optional[Dict[str, Any]]:
        """Fetch the FULL past-study list for one PatientID via ``GetPatientStatus``.

        The server returns every study of that patient_id (newest→oldest) with
        per-study date/modality/series/instance counts and report status — the
        "Previous Exams" feature consumes ``data['studies']``. Returns the
        normalized ``data`` payload on success, otherwise ``None`` (tolerant).
        See docs server doc §1.2.
        """
        try:
            pid = str(patient_id or "").strip()
            if not pid:
                return None

            response = None
            for attempt in range(2):
                response = self.send_request("GetPatientStatus", {"patient_id": pid})
                if response:
                    break
                if attempt == 0:
                    time.sleep(0.2)
            if not response:
                return None

            status = str(response.get("status", "") or "").lower()
            if status not in {"success", "ok"} and not bool(response.get("success")):
                return None

            data = response.get("data")
            return data if isinstance(data, dict) else None
        except Exception as e:
            logger.error(f"❌ Error getting patient status via socket: {e}")
            return None

    def get_patient_reception_history(
        self,
        patient_id=None,
        *,
        reception_id=None,
    ) -> Optional[Dict[str, Any]]:
        """Fetch the cross-PatientID reception history via ``GetPatientReceptionHistory``.

        This is the National-ID / RIS path: given the current ``patient_id``
        (which the server treats as an alias for ``reception_id``), the server
        resolves the same real person by ``nationalCode`` / ``risPatientId`` and
        returns every PRIOR reception — each of which may carry a DIFFERENT
        PatientID and its own ``studies[]``. Returns the normalized ``data``
        payload (``patientId`` / ``nationalCode`` / ``history[]``) on success,
        otherwise ``None``. See docs server doc §1.3.
        """
        try:
            params: Dict[str, Any] = {}
            rid = str(reception_id or "").strip()
            pid = str(patient_id or "").strip()
            if rid:
                params["reception_id"] = rid
            # patient_id is a documented alias for reception_id — send it too so
            # the server can resolve via either key.
            if pid:
                params["patient_id"] = pid
                params.setdefault("reception_id", pid)
            if not params:
                return None

            response = None
            for attempt in range(2):
                response = self.send_request("GetPatientReceptionHistory", params)
                if response:
                    break
                if attempt == 0:
                    time.sleep(0.2)
            if not response:
                return None

            status = str(response.get("status", "") or "").lower()
            if status not in {"success", "ok"} and not bool(response.get("success")):
                # Some HTTP-style deployments omit the status wrapper and return
                # the history fields at the top level; accept that shape too.
                if isinstance(response.get("history"), list):
                    return response
                return None

            data = response.get("data")
            if isinstance(data, dict):
                return data
            # Tolerate a top-level history payload under a success wrapper.
            if isinstance(response.get("history"), list):
                return response
            return None
        except Exception as e:
            logger.error(f"❌ Error getting patient reception history via socket: {e}")
            return None

    def query_series_thumbnails(
        self,
        *,
        study_uid: str,
        patient_id: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Fetch series metadata via QuerySeriesThumbnails endpoint.

        Some server deployments expose richer/safer payloads via this endpoint.
        Returns a normalized dict payload on success, otherwise ``None``.
        """
        try:
            uid = str(study_uid or "").strip()
            if not uid:
                return None

            params: Dict[str, Any] = {
                "study_instance_uid": uid,
                "study_uid": uid,
                "studyUid": uid,
                "limit": 100,
                "offset": 0,
            }
            pid = str(patient_id or "").strip()
            if pid:
                params["patient_id"] = pid

            response = None
            for attempt in range(2):
                response = self.send_request("QuerySeriesThumbnails", params)
                if response:
                    break
                if attempt == 0:
                    time.sleep(0.2)
            if not response:
                return None

            status = str(response.get("status", "") or "").lower()
            if status not in {"success", "ok"} and not bool(response.get("success")):
                return None

            data = response.get("data")
            if isinstance(data, dict):
                _normalize_series_identity(data, endpoint="QuerySeriesThumbnails",
                                           study_uid=uid)
                return data
            if isinstance(data, list):
                normalized = {
                    "study_instance_uid": uid,
                    "patient_id": pid,
                    "series_thumbnails": data,
                    "count_of_series": len(data),
                }
                _normalize_series_identity(normalized, endpoint="QuerySeriesThumbnails",
                                           study_uid=uid)
                return normalized
            return None
        except Exception as e:
            logger.error(f"❌ Error querying series thumbnails via socket: {e}")
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
                "studyUid": study_uid,
                "new_status": new_status,
                "newStatus": new_status,
                "report_status": new_status,
                "reportStatus": new_status,
                "status": new_status,
            }
            if user_id:
                params["user_id"] = user_id
            if comment:
                params["comment"] = comment
                params["report_comment"] = comment
                params["reportComment"] = comment
                params["pacs_comment"] = comment
                params["pacsComment"] = {"text": comment}
            
            response = self.send_request("UpdateReportStatus", params)
            
            if response and (
                str(response.get("status", "")).lower() in {"success", "ok"}
                or bool(response.get("success"))
                or response.get("updated") is True
            ):
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
            params = {
                "study_uid": study_uid,
                "studyUid": study_uid,
            }
            response = self.send_request("GetReportStatus", params)
            
            if response and (
                str(response.get("status", "")).lower() in {"success", "ok"}
                or bool(response.get("success"))
                or isinstance(response.get("data"), dict)
            ):
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
    Lazy connection pool for socket connections.

    Connections are created on demand (not eagerly at init) and validated
    before reuse.  Pool size is a cap — not a pre-allocation target.
    """

    def __init__(self, host: str, port: int, pool_size: int = 5):
        self.host = host
        self.port = port
        self.pool_size = pool_size
        self.connections: list = []
        self.lock = threading.Lock()

    def get_connection(self) -> Optional[PatientListSocketClient]:
        """Get a connection from the pool, or create a new one."""
        with self.lock:
            # Try to return an existing connected client
            while self.connections:
                client = self.connections.pop()
                if client.is_connected():
                    return client
                # Stale — close and discard
                try:
                    client.disconnect()
                except Exception:
                    pass

        # No pooled connection available — create fresh
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
