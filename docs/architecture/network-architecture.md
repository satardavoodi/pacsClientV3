# Network & Server Communication Architecture

> **Version:** v2.3.1 | **Updated:** 2026-04-13

## Purpose

AIPacs communicates with the **AIPacs Server** over two transport channels:

| Channel | Transport | Port | Primary role |
|---------|-----------|------|--------------|
| **Socket (custom protocol)** | TCP + JSON envelope | 50052 | Patient lists, report status, DICOM downloads, admission data |
| **gRPC** | HTTP/2 + Protobuf | 50051 | Thumbnails only (minor role) |

The socket channel carries >95% of all server traffic.  gRPC is used
exclusively for study/series thumbnail metadata and image data fetching.

---

## Architecture Diagram

```
┌──────────────────────────────────────────────────────────────────┐
│                        AIPacs Desktop App                        │
│                                                                  │
│  ┌────────────┐    ┌──────────────────┐    ┌──────────────────┐ │
│  │ HomePanelW │    │DownloadManagerW  │    │ PatientWidget    │ │
│  │  (UI)      │    │  (UI)            │    │  (Viewer UI)     │ │
│  └─────┬──────┘    └────────┬─────────┘    └────────┬─────────┘ │
│        │                    │                       │            │
│  ┌─────▼────────────────────▼───────────────────────▼──────────┐│
│  │              SocketService  (singleton facade)               ││
│  │  modules/network/socket_service.py                          ││
│  └──────┬──────────────────────┬───────────────────────────────┘│
│         │                      │                                │
│  ┌──────▼──────────┐    ┌─────▼─────────────────┐              │
│  │PatientListSocket│    │SocketDicomClient      │              │
│  │    Client       │    │(download-path)        │              │
│  │ modules/network/│    │modules/download_mgr/  │              │
│  │ socket_client.py│    │network/socket_client.py│             │
│  └──────┬──────────┘    └─────┬─────────────────┘              │
│         │                     │                                 │
│  ┌──────▼──────────┐    ┌────▼──────────────────┐              │
│  │SocketConnection │    │ConnectionHealthMonitor│              │
│  │    Pool         │    │(R30-R34 adaptive)     │              │
│  └──────┬──────────┘    └───────────────────────┘              │
│         │                                                       │
│  ┌──────▼──────────────────────────────────────────────────────┐│
│  │           SocketTokenManager  (JWT singleton)               ││
│  │           modules/network/socket_token_manager.py           ││
│  └─────────────────────────────────────────────────────────────┘│
│                                                                  │
│  ┌─────────────────────┐    ┌──────────────────────────────────┐│
│  │  DicomGrpcClient    │    │  SocketConfig                    ││
│  │  modules/network/   │    │  modules/network/socket_config.py││
│  │  grpc_client.py     │    │  + config/socket_config.json     ││
│  └──────────┬──────────┘    └──────────────────────────────────┘│
│             │                                                    │
└─────────────┼────────────────────────────────────────────────────┘
              │
       ───────┼──────────── Network boundary ────────────────
              │
┌─────────────▼────────────────────────────────────────────────────┐
│                      AIPacs Server                               │
│                                                                  │
│   ┌────────────────┐        ┌────────────────┐                  │
│   │ Socket Endpoint│        │ gRPC Endpoint  │                  │
│   │   :50052       │        │   :50051       │                  │
│   │ Patient list   │        │ Thumbnails     │                  │
│   │ Report status  │        │ DICOM images   │                  │
│   │ DICOM download │        │                │                  │
│   │ Admission data │        │                │                  │
│   └────────────────┘        └────────────────┘                  │
│                                                                  │
│   ┌────────────────────────────────────────────┐                │
│   │             DICOM Storage / PACS            │                │
│   └────────────────────────────────────────────┘                │
└──────────────────────────────────────────────────────────────────┘
```

---

## File Map

### Core network modules (`modules/network/`)

| File | Responsibility | Singleton? |
|------|---------------|------------|
| `socket_service.py` | **Facade** — all server calls go through here | Yes (`get_socket_service()`) |
| `socket_client.py` | Patient list queries, report status, generic `send_request` | No (pooled) |
| `socket_config.py` | Config loader: host, port, timeouts, TCP tuning | Yes (`get_socket_config()`) |
| `socket_token_manager.py` | JWT token storage, thread-safe | Yes (double-check locking) |
| `socket_patient_service.py` | Higher-level patient search wrapper | No |
| `socket_report_status_service.py` | Report status update/query wrapper | No |
| `grpc_client.py` | Thumbnail + DICOM image fetching via gRPC | No (per-use) |
| `dicom_service.proto` | Protobuf schema for gRPC service | — |
| `dicom_service_pb2.py` | Generated Protobuf Python bindings | — |
| `dicom_service_pb2_grpc.py` | Generated gRPC stub/servicer | — |
| `connection_health_monitor.py` | Legacy health monitor (superseded by download_manager version) | — |
| `server_settings_dialog.py` | UI dialog for server host/port configuration | — |
| `series_utils.py` | Series-level data utilities | — |
| `zeta_adapter.py` | Adapter bridging old Zeta DM API to new socket API | — |
| `upload_download_attchments.py` | Attachment upload/download helpers | — |
| `upload_task_manager.py` | Background upload task queue | — |

### Download-path network modules (`modules/download_manager/network/`)

| File | Responsibility |
|------|---------------|
| `socket_client.py` | `SocketDicomClient` — production DICOM downloader with retry, batch, compression |
| `health_monitor.py` | `ConnectionHealthMonitor` (R30-R34) — adaptive throttle, health tracking |

### Configuration

| Source | Priority | Notes |
|--------|----------|-------|
| `config/socket_config.json` | Runtime config | Loaded by `SocketConfig`; saved on first run |
| Environment variables | Override | `AIPACS_SOCKET_HOST`, `AIPACS_SOCKET_PORT`, `AIPACS_GRPC_PORT` |
| `modules/download_manager/core/constants.py` | Fallback defaults | Used when config is unavailable |

---

## Wire Protocol (Socket Channel)

### Framing

All messages use **4-byte big-endian length prefix + UTF-8 JSON body**:

```
┌──────────────┬───────────────────────────────┐
│ 4 bytes (BE) │ N bytes (UTF-8 JSON)          │
│  msg length  │ { "endpoint": "...", ... }     │
└──────────────┴───────────────────────────────┘
```

### Request format

```json
{
  "endpoint": "GetPatientList",
  "params": { "page": 1, "limit": 50 },
  "token": "eyJhbGciOiJIU..."
}
```

### Response format

```json
{
  "status": "success",
  "data": { ... }
}
```

Or broadcast (filtered/skipped by client):

```json
{
  "type": "broadcast",
  "event_type": "new_study",
  "data": { ... }
}
```

### Safety guards (v2.3.1)

| Guard | Purpose |
|-------|---------|
| `sendall()` instead of `send()` | Prevents partial writes on large payloads |
| `_recv_exact(size)` | Accumulates partial reads until exact byte count received |
| 50 MB response size limit | Prevents unbounded memory allocation from server bugs |
| 10 broadcast skip limit | Prevents infinite loop if server only sends broadcasts |

### Socket endpoints

| Endpoint | Direction | Purpose |
|----------|-----------|---------|
| `Login` | Request | Authenticate, receive JWT token (no retry — fail-fast) |
| `GetPatientList` | Request | Fetch patient list (paginated) |
| `GetReportStatus` | Request | Get report status for a study |
| `UpdateReportStatus` | Request | Update report status |
| `GetReportStatusHistory` | Request | Report status audit trail |
| `DownloadDicomImages` | Request | Download DICOM images for a series (batched) |
| `GetInstanceBatch` | Request | Batch instance download within series |
| `broadcast` | Server→Client | Real-time notifications (new study, status change) |

---

## gRPC Channel

### Service definition (`dicom_service.proto`)

| RPC | Type | Purpose |
|-----|------|---------|
| `GetStudyThumbnails` | Unary | Study metadata + series thumbnail list |
| `GetDicomImages` | Server streaming | Stream DICOM files for a series |

### Client features (v2.3.1)

| Feature | Implementation |
|---------|---------------|
| Auto-reconnect | `_ensure_stub()` reconnects if channel/stub is `None` |
| Configurable timeout | All RPCs use `timeout=self.timeout` (default 30s) |
| Keepalive | gRPC keepalive pings every 60s, 10s timeout |
| Max message size | 100 MB receive limit |
| Context manager | Supports `with DicomGrpcClient() as client:` |
| Insecure channel | Used intentionally — server is on private LAN behind firewall |

---

## Authentication

```
Login flow:
  1. User enters credentials in LoginDialog
  2. SocketService.send_request("Login", {username, password})
     — No retry on Login (fail-fast by design)
  3. Server returns JWT token
  4. SocketTokenManager.set_token(token, user_info)
  5. All subsequent send_request() calls auto-attach token via
     token_manager.add_token_to_request(request)
```

### Token lifecycle

| Event | Action |
|-------|--------|
| Login success | `set_token(jwt, user_dict)` |
| App shutdown | Token discarded (no persist) |
| Token expired | Server returns auth error → UI shows re-login |
| Thread safety | All access is under `threading.Lock` |

---

## Connection Pool (`SocketConnectionPool`)

Used by `PatientListSocketClient` for patient queries and report status.

### Design (v2.3.1 — lazy creation)

```python
pool = SocketConnectionPool(host, port, timeout, pool_size=3)
client = pool.get_client()   # Creates on demand, validates before returning
try:
    result = client.send_request(...)
finally:
    pool.return_client(client)
```

| Property | Value |
|----------|-------|
| Default size | 3 connections |
| Creation | Lazy — connections created on first `get_client()` |
| Validation | `is_connected()` check before returning pooled client |
| Stale handling | Disconnected clients removed, fresh one created |
| Thread safety | `threading.Lock` around pool operations |
| Timeout | Configurable via `SocketConfig.connection_timeout` |

---

## Retry Architecture

### Three-layer retry (download path only)

```
Layer 1: send_request() wrapper
  ├─ Up to REQUEST_MAX_RETRIES (3) per individual call
  ├─ Exponential backoff between retries
  └─ Login requests SKIP retry (fail-fast)

Layer 2: connect_with_retry() (socket level)
  ├─ Up to RECONNECT_MAX_RETRIES (5) attempts
  ├─ Exponential backoff: delay = min(base * factor^attempt, max_delay) + jitter
  └─ Jitter prevents thundering herd on server recovery

Layer 3: Per-series retry loop (series_downloader.py)
  ├─ Up to MAX_SERIES_RETRIES (3) rounds for failed series
  ├─ Backoff between rounds: 3s → 6s → 12s
  └─ Fresh socket reconnect between rounds
```

### All retry constants (`modules/download_manager/core/constants.py`)

| Constant | Value | Purpose |
|----------|-------|---------|
| `RECONNECT_MAX_RETRIES` | 5 | Socket reconnection attempts |
| `RECONNECT_BASE_DELAY` | 1.0s | Initial reconnect delay |
| `RECONNECT_MAX_DELAY` | 30.0s | Max backoff cap |
| `RECONNECT_BACKOFF_FACTOR` | 2.0 | Exponential multiplier |
| `RECONNECT_JITTER_MAX` | 1.0s | Random jitter range |
| `MAX_SERIES_RETRIES` | 3 | Per-series retry rounds |
| `SERIES_RETRY_BASE_DELAY` | 3.0s | Base inter-round delay |
| `REQUEST_MAX_RETRIES` | 3 | Per-request retry |
| `REQUEST_RETRY_BASE_DELAY` | 1.0s | Per-request retry delay |

---

## Connection Health Monitoring (R30–R34)

Located in `modules/download_manager/network/health_monitor.py`.

| Rule | Behavior |
|------|----------|
| R30 | Track success/failure counts, latency, success rate |
| R32 | Adaptive throttle — increase delay on degraded connection |
| R33 | Connection test before critical operations |
| R34 | Graceful degradation — reduce parallelism on poor health |

### Health metrics

```python
@dataclass
class HealthMetrics:
    consecutive_successes: int
    consecutive_failures: int
    success_rate: float          # percentage
    average_latency_ms: float
    is_healthy: bool             # success_rate > 80% AND consecutive_failures < 3
```

---

## TCP Tuning

Set in `SocketDicomClient` (download path):

| Option | Value | Reason |
|--------|-------|--------|
| `TCP_NODELAY` | True | Low latency for request/response |
| `SO_KEEPALIVE` | True | Detect dead connections |
| `SO_RCVBUF` | 256 KB | Large receive buffer for DICOM streams |
| `SO_SNDBUF` | 256 KB | Large send buffer |

Set in `SocketConfig` defaults:

| Option | Value | Notes |
|--------|-------|-------|
| `buffer_size` | 256 KB | Socket recv buffer |
| `tcp_window_size` | 1 MB | TCP window (conservative) |
| `chunk_size` | 64 KB | Read chunk size |
| `batch_timeout` | 120s | Per-batch timeout |

---

## Data Flow: Patient List Query

```
HomePanelWidget._search_server_async()
  └─ HomeSearchService.search_server_async()
       └─ SocketService.send_request("GetPatientList", params)
            └─ PatientListSocketClient.send_request()
                 ├─ Auto-connect if disconnected
                 ├─ Attach JWT token
                 ├─ sendall(length + JSON)
                 ├─ _recv_exact(4) → response length
                 ├─ _recv_exact(N) → response body
                 ├─ Skip broadcast messages
                 └─ Return parsed JSON dict
```

## Data Flow: DICOM Download

```
HomePanelWidget._on_patient_double_clicked_async()
  └─ DownloadManagerWidget.start_priority_download_immediately()
       └─ DownloadExecutor → SeriesDownloader
            └─ SocketDicomClient.download_series()
                 ├─ connect_with_retry() (exponential backoff + jitter)
                 ├─ For each batch (10 instances):
                 │    ├─ send_request("GetInstanceBatch", {series, batch_start, batch_size})
                 │    ├─ Receive GZIP-compressed DICOM data
                 │    ├─ Decompress + save Instance_NNNN.dcm
                 │    ├─ Progress callback → UI signal
                 │    └─ Health monitor: record_success/record_failure
                 ├─ Adaptive batch sizing based on network health
                 └─ Per-series retry (3 rounds, 3s→6s→12s backoff)
```

## Data Flow: Report Status Update

```
ReportStatusWidget.update_status()
  └─ SocketReportStatusService.update_report_status(study_uid, new_status)
       └─ PatientListSocketClient.update_report_status()
            └─ send_request("UpdateReportStatus", params)
```

---

## Rules for Future Development

### MUST

- All server communication MUST go through `SocketService` (singleton) — never create raw socket connections in UI code.
- All socket `send()` calls MUST use `sendall()` — partial writes corrupt framing.
- All socket `recv()` for exact-length data MUST use `_recv_exact()` — partial reads corrupt framing.
- Response size MUST be validated before allocation (current limit: 50 MB).
- JWT token MUST be attached to every request via `SocketTokenManager.add_token_to_request()`.
- Login requests MUST NOT be retried — fail-fast by design.
- All retry constants MUST live in `modules/download_manager/core/constants.py` — not scattered across files.
- Server host/port MUST come from `SocketConfig` (which reads `config/socket_config.json`) — not hardcoded.

### SHOULD

- Prefer `logger.debug()` for routine I/O (send/recv bytes). Use `logger.info()` only for connection state changes and errors.
- Use `SocketConnectionPool` for patient-list/report queries. Use `SocketDicomClient` for downloads.
- Use `ConnectionHealthMonitor` metrics to adapt download behavior (batch size, parallelism).
- Use `DicomGrpcClient` with `_ensure_stub()` for thumbnail operations — it auto-reconnects.

### MUST NOT

- Do NOT hardcode server IP addresses in source code — use config or environment variables.
- Do NOT use `socket.send()` — always `sendall()`.
- Do NOT use bare `socket.recv(4)` for framing — use `_recv_exact(4)`.
- Do NOT add retry logic to Login endpoint calls.
- Do NOT create `PatientListSocketClient` directly in UI code — go through `SocketService`.
- Do NOT use `print()` for network error logging — use `logging.getLogger(__name__)`.
- Do NOT use `grpc.insecure_channel()` without documenting why TLS is not needed (private LAN justification).
- Do NOT block the Qt event loop with synchronous socket calls — offload to background threads.

### Documentation triggers

- When changing socket protocol (framing, endpoints, auth), update this file.
- When changing retry constants, update the retry table in this file and in `docs/pipelines/download-pipeline.md`.
- When changing gRPC service definition, regenerate `_pb2.py` / `_pb2_grpc.py` and update the gRPC section here.
- When adding new socket endpoints, add them to the endpoint table in this file.
- When changing `SocketConfig` defaults, update the TCP tuning and config tables here.
