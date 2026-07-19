# AI-PACS Agent Gateway — Mobile Pairing & MCP Wire Protocol

> Audience: the Android AI-PACS agent app team, anyone building an AI/MCP client
> for the workstation, and whoever deploys the relay server. Implemented
> 2026-07-17. Source: `modules/agent_gateway/`. This is the exact contract — the
> workstation implements the server side; this document is what the phone must
> speak.

## 1. What this is (and what it is NOT)

The Agent Gateway lets an external agent client **pair with and drive a specific
Windows AI-PACS workstation**. The phone becomes a remote control / AI cockpit
for the workstation: it can list and open patients, drive the viewer, read
viewport state, trigger downloads, etc. — every function is the SAME production
CommandBus action the in-app voice assistant uses, so all clinical isolation and
multi-study guards stay enforced.

It is **not** a VPN and **not** a tunnel you configure at the OS level. Two
reachability modes:

- **LAN** (default): the phone and the PC are on the same network. The phone
  talks HTTPS directly to the workstation at the LAN address in the QR.
- **Relay** (off-network): the workstation dials OUT to a rendezvous server you
  host; the phone reaches the workstation through that relay. No inbound
  firewall port is opened on the clinic PC.

Both modes present the **identical** application protocol (pairing + MCP). The
only difference is the base URL the phone uses.

## 2. Security model (read this first)

- **Feature is OFF by default.** Nothing listens until the operator enables it in
  *Settings ▸ Agent* (or sets `AIPACS_AGENT_GATEWAY=1`).
- **TLS with certificate pinning.** The workstation serves a self-signed
  certificate. Its SHA-256 fingerprint is inside the QR (`tls_fp`). The phone
  MUST pin exactly that certificate and refuse any other — this defeats
  man-in-the-middle without a public CA. (If TLS is disabled by the operator,
  `tls_fp` is absent and the endpoints are `http://`.)
- **Bearer device tokens.** Pairing yields a long-lived opaque device token. The
  phone sends `Authorization: Bearer <token>` on **every** request after pairing.
  The workstation stores only the token's SHA-256 hash; the raw token is shown to
  the phone exactly once (at pairing) and never persisted server-side.
- **Single-use, short-lived pairing codes.** The code in the QR is valid for a
  few minutes and for one pairing only.
- **Per-device permission mode.** Each device is `full`, `assistant`, or
  `read_only`. The operator can change or revoke any device at any time. The
  CommandBus permission gate enforces the mode server-side (see §7).
- **The relay is a dumb pipe.** In relay mode, device-token auth is still
  validated end-to-end on the workstation. The relay never holds a valid device
  token; a compromised relay cannot call functions, only observe ciphertext
  metadata and deny service.

## 3. The pairing QR

The QR encodes a single URI:

```
aipacs-agent://pair?d=<base64url(JSON payload)>
```

Decoded payload (`modules/agent_gateway/pairing.py::build_pairing_payload`):

```jsonc
{
  "v": 1,
  "typ": "aipacs-agent-pair",
  "code": "ABCD2345",                     // single-use pairing code
  "transport": "lan",                     // "lan" | "relay"
  "endpoints": [                          // try in order
    "https://192.168.1.20:8760",
    "https://10.0.0.9:8760"
  ],
  "tls_fp": "sha256:2F:1D:89:...",        // pin this cert (absent if TLS off)
  "mcp": "/mcp",                          // MCP endpoint path
  "name": "Clinic Room 3 PC",
  "iat": 1752710400,
  "exp": 1752710700,                      // payload/code expiry (epoch seconds)
  "relay": {                              // present only when transport=="relay"
    "url": "https://relay.example.com",
    "id":  "clinic-room-3"
  }
}
```

The phone: decode → pick a reachable `endpoints[i]` → (LAN) pin `tls_fp` → run
the pairing exchange (§4) → store `{base_url, device_token, tls_fp}` for reuse.
After the first pairing, no QR is needed again unless the device is revoked.

## 4. Pairing exchange

`POST <base_url>/pair`  (no auth; the `code` is the credential)

Request body:
```json
{ "code": "ABCD2345", "device_name": "Vahid's Pixel" }
```

Success `200`:
```json
{
  "ok": true,
  "device_id": "dev_1a2b3c4d5e6f7a8b",
  "device_token": "K7f...<opaque>...",    // store this; shown ONCE
  "mode": "full",
  "mcp_path": "/mcp",
  "server": { "name": "aipacs-agent-gateway", "version": "1.0.0" }
}
```

Failure `403` — invalid/expired/already-used code:
```json
{ "ok": false, "error": "invalid or expired pairing code" }
```

## 5. MCP endpoint

`POST <base_url><mcp_path>`  (bearer required) — JSON-RPC 2.0, one object or a
batch array per request. This is the Streamable-HTTP shape (request/response over
POST). `GET <mcp_path>` returns `405` — v1 does not offer a server-initiated SSE
stream.

Required header: `Authorization: Bearer <device_token>` (or
`X-AIPACS-Device-Token: <token>`). Missing/invalid ⇒ `401` with a JSON-RPC error.

Supported methods (`modules/agent_gateway/mcp_bridge.py`):

| Method | Purpose |
|---|---|
| `initialize` | Handshake; returns `serverInfo`, `capabilities`, `instructions`. |
| `notifications/initialized` | Client → server notification (no response). |
| `ping` | Liveness. |
| `tools/list` | Every CommandBus action as an MCP tool. |
| `tools/call` | Invoke an action. |
| `resources/list` | Operational docs + the live function catalog. |
| `resources/read` | Read a doc / the catalog. |

### 5.1 `tools/call`

```json
{ "jsonrpc":"2.0", "id":3, "method":"tools/call",
  "params":{ "name":"open_patient",
             "arguments":{ "entities":{ "patient_id":"12345" }, "confirmed":false } } }
```

- `name` = the action (from `tools/list`).
- `arguments.entities` = the action's parameters. (A flat `arguments` object with
  no `entities` key is accepted and treated as the entities.)
- `arguments.confirmed` = `true` re-issues a server-write/destructive action that
  the device's mode requires confirmation for (see §7).

Result (MCP tool result; the CommandResult JSON is in the text content):
```json
{ "content":[{ "type":"text", "text":"{\"ok\":true,\"action\":\"open_patient\",\"data\":{...}}" }],
  "isError": false }
```

`isError:true` + an error envelope in the text means the action was denied,
needs confirmation, or failed — parse the `error_code` (`PERMISSION_DENIED`,
`CONFIRM_REQUIRED`, `UNKNOWN_ACTION`, `GUI_TIMEOUT`, `NO_BUS`, …).

### 5.2 Resources — where the agent learns the workstation

- `aipacs-agent://functions` — a live JSON catalog of every action on THIS build
  plus a `how_to_call` note. Read it first.
- `aipacs-agent://docs/guide` — the operational control/testing guide.
- `aipacs-agent://docs/pairing` — this document.

This is deliberate: the **full operational documents are served to the agent via
MCP resources**, not rendered in the workstation's Settings UI. An agent that
wants to know which functions exist and how workflows operate reads the
resources; a human sees only the connection info in Settings ▸ Agent.

## 6. `/health`

`GET <base_url>/health` (no auth) → liveness + non-secret capability summary:
```json
{ "ok":true, "server":"aipacs-agent-gateway", "version":"1.0.0",
  "mcp_path":"/mcp", "transport":"lan", "tls":true, "actions":31,
  "paired_devices":2 }
```

## 7. Permission modes (device → CommandBus agent_mode)

| Device mode | agent_mode | Reads | Server-write / destructive |
|---|---|---|---|
| `full` | `qa` | run | run, **no confirmation** (audited) |
| `assistant` | `assistant` | run | **`CONFIRM_REQUIRED`** → re-call with `confirmed:true` |
| `read_only` | `read_only` | run | **`PERMISSION_DENIED`** |

The gate is the existing `modules/EchoMind/secretary/permissions.py`, enforced at
`registry.AdapterRegistry.dispatch`. The gateway adds no parallel policy — it
only maps the device's mode onto `state['agent_mode']`. Every dispatch is
audited.

## 8. Relay wire protocol (for the relay host)

The relay is a small stateless forwarder you deploy on a host both the
workstation and the phone can reach (e.g. a $5 VPS with HTTPS). A runnable
reference implementation is in `tools/agent_relay/` (stdlib only). Endpoints:

**Workstation → relay (outbound, long-poll):**
- `POST /agent/register` `{ "workstation_id": "clinic-room-3" }` — claim/refresh
  the channel. `Authorization: Bearer <relay_auth_token>`.
- `GET /agent/poll?ws=<id>&wait=<sec>` — long-poll; returns
  `{ "requests": [ { "rid","method","path","headers","body_b64" }, ... ] }`
  (empty after `wait` seconds).
- `POST /agent/respond` `{ "rid","status","headers","body_b64" }` — return a
  response for a forwarded request.

**Phone → relay (public):**
- `ANY /client/<workstation_id><path>` — the relay enqueues the request onto the
  workstation's channel (as an `rid`), waits for the matching `/agent/respond`,
  and returns it verbatim. So the phone uses base URL
  `https://relay.example.com/client/<workstation_id>` and speaks the exact same
  `/pair` + `/mcp` protocol as LAN.

Because device-token auth and (optionally) an app-layer TLS body are validated on
the workstation, the relay needs no knowledge of device tokens — it authenticates
only the workstation (via `relay_auth_token`) and forwards opaque bytes.

## 9. Android implementation checklist

1. Scan QR → `decode_pairing_uri` equivalent (base64url → JSON).
2. Choose transport: `endpoints[0]` (LAN) or the relay `/client/<id>` URL.
3. Pin `tls_fp` (LAN/relay HTTPS). Reject any other server cert.
4. `POST /pair` with the `code` → store `device_token` in the Android Keystore.
5. MCP session: `initialize` → `tools/list` → `resources/read
   aipacs-agent://functions` → drive with `tools/call`.
6. Handle `CONFIRM_REQUIRED` by prompting the user, then re-calling with
   `confirmed:true`.
7. On `401`, the device was revoked — re-pair with a fresh QR.

## 10. Versioning

`payload.v = 1`, MCP `protocolVersion = "2025-06-18"` (negotiated in
`initialize`). Additive changes bump the payload `v`; the phone should tolerate
unknown payload keys.
