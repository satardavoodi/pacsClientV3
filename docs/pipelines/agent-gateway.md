# Agent Gateway — as-built (2026-07-17)

Mobile / MCP connectivity for the workstation: an external agent client (the
Android AI-PACS agent app, or any MCP client) pairs with and drives this
workstation. **Second transport onto the existing EchoMind `CommandBus`** — it
does NOT fork the command registry, adapters, or permission gate. Default OFF,
flag-gated, GUI-thread-safe, no clinical-path change.

Wire protocol for clients: `docs/for-future-agents/AGENT_MOBILE_PAIRING_PROTOCOL.md`.
Reference relay server: `tools/agent_relay/`.

## Where it lives

- `modules/agent_gateway/` — the whole feature. NOT plugin-mirrored.
  - `feature_flags.py` / `config_store.py` — env→config→default OFF; roaming
    settings (`config/agent_gateway/agent_gateway.json`).
  - `pairing.py` (pure) — QR payload build/encode/decode, pairing codes, device
    tokens (opaque; only the SHA-256 hash is stored).
  - `device_store.py` — paired devices, hashed tokens, per-device mode, revoke.
  - `mcp_bridge.py` (pure) — MCP JSON-RPC subset (initialize/tools/resources).
  - `core.py` — `GatewayCore`: transport-agnostic routing + bearer auth +
    single-use pairing. Both transports call `core.handle(method, path, headers,
    body)`.
  - `tls_identity.py` — self-signed cert (via `cryptography`) + pinning
    fingerprint.
  - `net_utils.py` / `qr.py` — LAN IP discovery / QR render (`segno`, soft dep).
  - `docs_resources.py` — operational docs + live function catalog as MCP
    resources.
  - `gui_dispatch.py` — marshal `bus.execute` from a background thread onto the
    Qt GUI thread (one command per event-loop turn) with a timeout.
  - `http_gateway.py` — LAN transport (`ThreadingHTTPServer` + TLS on a daemon
    thread).
  - `relay_transport.py` — relay transport (outbound long-poll client, `requests`).
  - `service.py` — `AgentGatewayService` lifecycle + the Settings-tab control
    surface (`install_service`/`get_service` app singleton).
- `PacsClient/pacs/workstation_ui/settings_ui/agent_settings.py` — the Settings
  ▸ Agent tab. Registered in `settings_ui.py` (`_add_lazy_tab('Agent', …)`).
- Boot: `home_ui/home_panel/widget.py` — `install_service(lambda: self.command_bus)`
  + `start_if_enabled()` right after the Test Control Server, stored on
  `QApplication._agent_gateway_service`.
- Shutdown: `main.py` `finally` — `app._agent_gateway_service.stop()` **before**
  the `os._exit(0)` failsafe (so no listener thread lingers, same rationale as
  the download-subprocess kill).

## Invariants (do not break)

- **Reuse the bus, don't fork it.** The gateway obtains the already-built
  `command_bus` via the injected getter and adds a transport. All isolation /
  multi-study / permission behaviour is inherited. If you need a new capability,
  add a CommandBus adapter action — never a parallel command path here.
- **GUI thread never blocks.** Network I/O runs on daemon threads; only the fast
  `bus.execute` runs on the GUI thread, marshalled via `gui_dispatch`
  (`QMetaObject.invokeMethod(..., QueuedConnection)` + a `threading.Event` the
  caller waits on with a timeout). This mirrors the Test Control Server's
  "one command per event-loop turn" model for a cross-thread caller.
- **Default OFF; nothing binds until enabled.** `install_service` is cheap (no
  threads/ports). `start_if_enabled()` starts only when
  `agent_gateway_enabled()`. Env `AIPACS_AGENT_GATEWAY` (=1 force / =0 kill)
  wins over the config `enabled` flag.
- **Auth is mandatory past `/pair`.** `/health` + `/pair` are unauthenticated;
  everything else needs a valid bearer device token. Pairing codes are
  single-use + short-lived. The permission gate (`permissions.py`) maps
  `full→qa`, `assistant→assistant`, `read_only→read_only` and still enforces
  confirmation/denial — the gateway adds no policy of its own.
- **No baked-in secrets.** Device tokens live hashed in the roaming profile
  (`<roaming config>/agent_gateway/devices.json`), NEVER in the shipped repo.
  TLS key material is generated at runtime in the same roaming dir. The config
  template ships with `enabled:false` and empty relay fields; the sanitizer
  blanks `relay_base_url` / `relay_auth_token` / `relay_workstation_id` and the
  leak scanner would fail the build on any non-empty `*_token`.
- **Relay is a dumb pipe.** Device-token auth is validated end-to-end on the
  workstation. The relay authenticates only the workstation (`relay_auth_token`)
  and forwards opaque bytes; a compromised relay cannot call functions.
- **The full agent docs are MCP resources, not Settings UI.** The tab shows only
  connection info + a one-line pointer; `docs_resources.py` serves the operational
  docs + a live function catalog to connected clients.

## Reaching the workstation FROM OUTSIDE (remote access)

A private LAN address can never be dialled from the internet. There are exactly
three ways to reach this PC remotely, in order of preference for a PHI-handling
clinical box:

1. **VPN (recommended, and already in use here).** The reference workstation is a
   member of a private **WireGuard** network (`W8a23u41`, `192.168.24.0/24`, own
   address `192.168.24.41`). The gateway binds `0.0.0.0`, so it is ALREADY served
   on that tunnel — verified live: `https://192.168.24.41:8760/health` → ok.
   Add the phone as a peer on the same WireGuard network and it reaches the
   workstation from anywhere, with **no inbound port forwarding** and **no third
   party** in the path. Then set *Advertise address* to the tunnel IP (below).
2. **Relay / outbound rendezvous** (`transport: "relay"` + `relay_ws_url`) —
   **IMPLEMENTED 2026-07-17**, and the option that needs no network skill from
   the customer. The workstation holds ONE persistent **outbound WebSocket** to
   the AIPACS relay (`tools/agent_relay/aipacs_relay.py`), which routes by a
   stable `workstation_id` — **never by IP**. A changing IP, a new Wi-Fi, sleep,
   or mobile tethering is just a reconnect (exponential backoff + full jitter).
   Every frame is **sealed end-to-end** (X25519 → HKDF → ChaCha20-Poly1305,
   `secure_channel.py`), so the relay forwards opaque ciphertext and cannot read
   patient data. Client: `relay_ws.py` (soft dependency on `websocket-client`;
   falls back to the long-poll `relay_transport.py` when absent).
   Design + rationale: `docs/plans/architecture/REMOTE_CONNECTIVITY_ARCHITECTURE_2026-07-17.md`.
   Verified end-to-end by `tools/agent_relay/integration_check.py`.

   **Invariants that make it work — do not break these:**
   - **A `SecureChannel` is SESSION STATE and must be cached per device**, never
     rebuilt per request: it holds the nonce counter and the replay high-water
     mark, so recreating it restarts the counter at 1 and the peer correctly
     rejects the next frame as a replay. Cached in BOTH `service._channel_for`
     and `relay_ws._channel` (defence in depth — a naive provider can't break it).
   - **Seal → send must be atomic** (`with channel.lock:`). Requests are handled
     on a worker pool; the receiver enforces strictly increasing counters, so the
     counter order must equal the byte order on the wire (one WS + TCP preserves it).
   - **The first `/pair` frame travels in clear** — it carries only a pairing code
     and a public key (no clinical data), because the workstation cannot know the
     device's key yet. Everything after pairing is sealed.
   - **The relay must never store messages.** It answers `workstation_offline`
     instead of queueing; queueing clinical traffic would turn a conduit into a store.
   - **The relay's device id and the workstation's device id are DIFFERENT id
     spaces.** The relay adds `relay_device_id` and must not overwrite the
     client's `device_id`, which is what selects the E2E channel on the workstation.
   - **No IP/endpoint/port column may ever enter the relay schema** — identity is
     a stable id. A guard test asserts this.
3. **Port-forwarding + DDNS** — NOT recommended. It exposes an inbound port on a
   clinical workstation to the internet and often fails behind CGNAT anyway.

### `advertise_host` — which address the QR offers FIRST

**A multi-homed PACS box breaks naive address discovery.** The reference machine
has **12** IPv4 addresses: ten static IPs on one NIC (one per modality subnet)
plus VirtualBox and the WireGuard tunnel. Two defects came out of this and are
fixed:

- **Discovery missed tunnel adapters.** `all_lan_ipv4()` used
  `socket.getaddrinfo(hostname)`, which on Windows omits WireGuard/VPN adapters —
  so `192.168.24.41`, the ONLY address a remote phone can reach, was never in the
  QR and the app reported *"you are out of local network"*. It now enumerates
  per-adapter via `psutil.net_if_addrs()` (fallback: the old hostname method) and
  filters loopback/link-local.
- **Order matters.** The phone tries endpoints in order; the reachable one must
  lead. `advertise_host` (Settings ▸ Agent ▸ *Advertise address*, or the config
  key) is placed FIRST, ahead of the default-route address. It accepts a hostname
  (DDNS / relay name), not just an IP. Empty = auto (previous behaviour).

`ensure_identity` now also **regenerates the TLS cert when a requested SAN is
missing** (e.g. a tunnel address appears later) — otherwise a strict TLS client
rejects the cert for the address it dialled.

**Security note:** `advertise_host` is centre-specific and is blanked by the build
sanitizer; `enabled` is **force-set to `false`** at packaging (see below).

## Build-system wiring (release-parity compliant)

- Config family: `CONFIG_FAMILY_VERSIONS["agent_gateway/agent_gateway.json"] = 2`
  (`aipacs_runtime.py`) + the template under `config/agent_gateway/`. **Bump the
  version whenever the template gains a key** (v2 added `advertise_host`).
- **The build, not the dev tree, guarantees ship-OFF.** In a SOURCE build
  `roaming_config_root()` IS the repo `config/` dir, so enabling the gateway in
  the app rewrites the shipped template. The sanitizer therefore **`force`s
  `enabled: false`** (a new `force` op: dotted path → literal the shipped file
  must carry) and blanks `advertise_host` + the relay fields. Guard tests assert
  the CODE default and the SANITIZER behaviour rather than the mutable on-disk
  template.
- Feature-flag file registered in
  `tests/code/builder/test_release_parity_guards.py::FEATURE_FLAG_CONFIG_FILES`.
- Sanitizer rule in `builder/config_sanitizer.py` blanks the relay fields.
- Dependency: `segno` added to `requirements.txt` (soft — QR falls back to a
  text URI if absent). Reuses `cryptography` (TLS) + `requests` (relay), already
  pinned.
- **Module is NOT in `MODULE_CATALOG`** — like `modules/network`,
  `modules/storage`, it ships in the core engine bundle (an un-catalogued
  `modules/` folder trips no parity guard; discovery is catalog-driven, not
  directory-driven). Promote to the catalog only if an installable per-module
  enable toggle is later wanted. Freeze tools include it because it is statically
  imported from `home_panel/widget.py`, `main.py`, and the Settings tab.

## Flags

- `AIPACS_AGENT_GATEWAY` — master env override (unset ⇒ config `enabled`, default
  OFF).
- Config (`config/agent_gateway/agent_gateway.json`): `enabled`, `transport`
  (`lan`|`relay`), `bind_scope`, `port` (8760), `tls_enabled`, `mcp_path`,
  `default_device_mode` (`full`|`assistant`|`read_only`), `pairing_ttl_seconds`,
  relay fields.

## Tests

- `tests/code/agent_gateway/test_agent_gateway.py` (28) — pairing, device store,
  MCP bridge, `GatewayCore` routing/auth/single-use pairing/mode mapping, relay
  framing, TLS identity, config/flags. Offscreen, no Qt/network.
- `tests/code/agent_gateway/test_agent_gateway_wiring.py` — source-pins the
  Settings-tab registration, the boot start hook, the shutdown stop-before-exit
  hook, the config family / feature-flag / sanitizer entries, and the docs
  resources.

## Live-verify checklist (source build, NOT done yet)

1. *Settings ▸ Agent* → enable → Save & Apply → status shows "Running", a port,
   and a TLS fingerprint. No GUI freeze.
2. Generate Pairing QR → a QR renders; `curl -k https://<lan-ip>:<port>/health`
   returns the summary; `POST /pair` with the shown code returns a device token;
   reusing the code returns 403.
3. `POST /mcp` with `Authorization: Bearer <token>` → `initialize`, `tools/list`,
   and a read-only `tools/call` (e.g. `list_patients`) succeed; an unauth call
   returns 401.
4. Set a device to `read_only` → a `download_patient` call returns
   `PERMISSION_DENIED`; set `assistant` → returns `CONFIRM_REQUIRED`, then
   `confirmed:true` runs it.
5. Relay mode: deploy `tools/agent_relay/`, set the relay URL/token, confirm the
   workstation registers and a phone reaches `/client/<id>/health`.
6. Close the app → no lingering `python.exe`/listener thread (the shutdown hook
   ran).

## Staged / not done

- Android client app (separate deliverable; this repo is the server + spec).
- Relay server hardening (the reference in `tools/agent_relay/` is minimal — add
  rate limiting, per-workstation quotas, and TLS termination via your reverse
  proxy for production).
- Optional server-initiated SSE stream on `GET /mcp` (v1 is request/response).
- Token rotation / expiry enforcement (`device_token_ttl_days` is stored but not
  yet enforced).
