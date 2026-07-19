# Remote connectivity architecture — mobile ⇄ workstation, anywhere

**Status:** investigation + recommendation (2026-07-17). Supersedes nothing; it is the
target architecture for `modules/agent_gateway`'s `transport: "relay"` path.
**Question:** how do Claude Cowork / ChatGPT-Codex desktop connect a phone to a desktop
app with no static IP, no port forwarding, no user network configuration — and what
should AI-PACS implement on the AIPACS cloud?

---

## 1. TL;DR

The pattern is **outbound-only persistent connection + cloud rendezvous + end-to-end
encryption**, and it is what every comparable product uses.

1. The **desktop never becomes reachable**. It has no public endpoint, no forwarded
   port, and its IP is irrelevant. It *dials out* to a cloud relay and keeps that
   connection open.
2. The **cloud addresses the workstation by a stable logical ID**, never by IP:port.
3. The **phone dials the same cloud** and asks to be joined to that ID.
4. The relay **forwards opaque encrypted bytes**; the desktop and phone hold the keys.

This works behind NAT, CGNAT, corporate firewalls, hotel Wi-Fi and mobile data,
because virtually every network permits *outbound* HTTPS/443.

> **Your assumption was close, and the correction makes it simpler.** You proposed
> that when the IP changes, the desktop notifies the cloud of its *new endpoint* and
> the phone reconnects to that endpoint. In the real designs there **is no endpoint to
> publish**. The desktop's connection is the only path, and it is always outbound. If
> the network changes, the desktop just re-dials and re-attaches to the same session
> ID. The cloud never stores an IP, so there is nothing to update, and no NAT/port
> discovery is ever needed. Removing "endpoint tracking" from the design removes an
> entire class of failure.

---

## 2. What the reference systems actually do

### Claude Code / Cowork Remote Control
Publicly described behaviour ([Claude Code docs][cc-docs], [analysis][cc-dispatch]):

- The QR encodes a **short-lived pairing token** that authorises the link.
- **"Every connection is outbound from your machine. Claude Code never opens an
  inbound port."** It establishes an outbound HTTPS connection to Anthropic's API,
  **which acts as a message relay**; the phone connects to the same endpoint from the
  other side.
- Desktop and phone perform an **X25519 key exchange when they pair**; payloads are
  encrypted with **XSalsa20-Poly1305** before leaving either device, so **the relay
  only forwards opaque encrypted blobs**.
- Explicitly described as *"the same pattern used by Tailscale and ngrok tunnels…
  works behind NAT, corporate firewalls, and home routers without any configuration
  changes."*

### ChatGPT / Codex remote control
Setup is: enable remote on the host → host shows a **QR** → phone scans it → confirm
the same account + MFA ([OpenAI docs][oai-remote]). The relay is described as the
layer that *"keeps the host reachable from your phone without exposing it to the
public internet, and keeps session state synced across your signed-in devices."*
Same shape: pairing token in a QR, cloud relay, work executes on the desktop, phone is
a remote control.

### Cloudflare Tunnel (the same idea, productised)
`cloudflared` **initiates an outbound-only connection** from the origin to Cloudflare;
traffic then flows both ways over it. A tunnel is **a persistent object identified by a
UUID** — the logical link, not an address. Because the daemon dials out, the setup
**adapts to dynamic IP changes with no manual configuration** and needs **no inbound
ports** ([Cloudflare docs][cf-tunnel]).

### Tailscale (the most sophisticated variant)
A **coordination server** distributes identity/keys and a relay map. **All connections
start relayed through a DERP relay, then Tailscale tries to upgrade them to a direct
connection** via STUN + hole punching, falling back to the relay when NAT is too hard.
DERP relays **cannot decrypt** — private keys never leave the device, so the relay
blindly forwards already-encrypted WireGuard packets ([Tailscale docs][ts-derp],
[how NAT traversal works][ts-nat]).

### Why "just do peer-to-peer" is not enough
WebRTC-style hole punching works for many networks but not all: roughly **75% of NATs
are traversable with STUN**, and about **30% of connections still need a TURN relay**
in restrictive/corporate networks ([WebRTC NAT traversal guide][webrtc-ice]). A
hospital network is exactly the restrictive case. So a relay is mandatory *anyway* —
direct connection is only ever an optimisation on top.

**Conclusion:** every one of these converges on the same primitive — *the endpoint
that cannot be reached dials out and stays connected*. The differences are only in
what rides on top (message relay vs. IP-level overlay) and whether a direct-path
upgrade is attempted.

---

## 3. Design space

| Option | No static IP? | No port-forward? | Works on mobile data? | PHI exposure | Effort |
|---|---|---|---|---|---|
| **A. Cloud relay, outbound WS, E2E encrypted** ← recommended | ✅ | ✅ | ✅ | none (opaque blobs) | medium |
| B. VPN (WireGuard) — already working here | ✅ | ✅ | ✅ | none | low, but per-device enrolment |
| C. Direct P2P (WebRTC/STUN) + TURN fallback | ✅ | ✅ | mostly | none if E2E | high (still needs a relay) |
| D. Port-forward + DDNS | ❌ needs DDNS | ❌ | ✅ | inbound attack surface | low, **not advised** |
| E. Third-party tunnel (Cloudflare/ngrok) | ✅ | ✅ | ✅ | **plaintext at the vendor** unless E2E | low |

**B is the best answer for a single clinic that already has WireGuard** (this
workstation does — see `docs/pipelines/agent-gateway.md`), and it should stay
supported. **A is the answer for a product** you ship to many centres, because it
requires zero network skill from the customer: install, scan, done.

---

## 4. Recommended architecture

Three independent layers. Only layer 2 is new infrastructure.

```
┌── Layer 3: APPLICATION (already built, unchanged) ─────────────────┐
│  MCP JSON-RPC  →  GatewayCore  →  CommandBus  →  the workstation   │
└────────────────────────────────────────────────────────────────────┘
┌── Layer 2: TRANSPORT (build this on AIPACS) ───────────────────────┐
│  Workstation ──outbound WSS──► AIPACS relay ◄──WSS── Phone         │
│  routed by workstation_id; relay forwards SEALED frames only       │
└────────────────────────────────────────────────────────────────────┘
┌── Layer 1: IDENTITY & PAIRING (AIPACS session registry) ───────────┐
│  who owns which workstation · which phones are paired · revocation │
└────────────────────────────────────────────────────────────────────┘
```

### Layer 1 — identity & pairing (AIPACS)

The registry stores **relationships, not endpoints**:

```
workstations(workstation_id, owner_user_id, display_name, pubkey, last_seen, status)
devices(device_id, owner_user_id, workstation_id, device_pubkey, name, mode, revoked)
pairing_tokens(token, workstation_id, expires_at, used_at)     -- single use, short TTL
```

Flow: workstation registers once (bound to the centre's AI-PACS account) → gets a
permanent `workstation_id` + credential. To pair a phone the workstation asks AIPACS for
a **short-lived pairing token**, renders it in the QR together with its **X25519 public
key**; the phone redeems the token, posts **its own public key**, and both sides derive
a shared secret. The registry records the pair. Revocation = delete the row.

**Note there is no IP anywhere in this schema.** That is the whole point.

### Layer 2 — transport (AIPACS relay)

- **Workstation → relay:** one persistent **WSS (TLS 443)** connection, opened at
  startup, authenticated with the workstation credential, re-dialled forever with
  exponential backoff + jitter. Heartbeat ping/pong (~30 s) so both sides detect a dead
  path quickly; a network change simply looks like a disconnect.
- **Phone → relay:** WSS while the app is in the foreground; the relay routes by
  `workstation_id` after checking the device is paired and not revoked.
- **Relay responsibilities (deliberately minimal):** authenticate both sides, match
  them, forward frames, expose `workstation_online: bool`. It should be a **conduit,
  not a store** — no message persistence beyond what is in flight (this also keeps it
  on the right side of the privacy analysis in §6).
- **Offline behaviour:** if the workstation is not connected, the relay answers the
  phone immediately with `workstation_offline` rather than queueing. The phone shows
  "workstation is offline" — honest and simple. (Queue-and-deliver is a v2 option and
  materially changes the privacy story, because queued data is *stored*.)

### Layer 3 — application (unchanged)

The frames carry exactly the MCP JSON-RPC already implemented. `GatewayCore.handle()`
is transport-agnostic by design, so **nothing in the command/permission/audit path
changes** — the relay is just another way to reach it. This is why the existing
`GatewayCore` / `pairing` / `mcp_bridge` code survives intact.

### The crypto that makes a cloud hop acceptable

Adopt the pattern the reference systems use:

1. At pairing, workstation and phone exchange **X25519** public keys (via the QR and
   the redeem call).
2. Derive a shared secret (HKDF) → a symmetric session key per direction.
3. **Seal every payload** with an AEAD (**XChaCha20-Poly1305**, libsodium
   `crypto_secretbox`/`crypto_box`) *before* it goes to the relay, with a nonce and a
   monotonic counter to prevent replay/reorder.
4. The relay sees only `{workstation_id, device_id, nonce, ciphertext}`.

Result: **AIPACS operators — and anyone who breaches the relay — cannot read patient
data.** The relay is a routing fabric, not a trusted party. TLS protects the hop;
the sealed payload protects the content.

### Optional later: direct-path upgrade

Follow Tailscale's model — start relayed (always works), then *try* to upgrade to a
direct connection on the same LAN (mDNS/known LAN address) or via STUN hole punching,
and silently fall back. For AI-PACS this is a **latency optimisation only**: command
frames are tiny. **Do not build it in v1.** (If image/pixel streaming is ever added,
revisit — that is when relay bandwidth starts to matter.)

---

## 5. Wire protocol sketch

```jsonc
// workstation → relay, once per connection
{"t":"hello","role":"workstation","workstation_id":"ws_…","auth":"<credential>","v":1}
// relay → workstation
{"t":"ready","session":"…"}

// phone → relay
{"t":"hello","role":"device","device_id":"dev_…","workstation_id":"ws_…","auth":"<device token>"}
{"t":"status"}                      → {"t":"status","workstation_online":true}

// either side, carrying a SEALED MCP frame
{"t":"msg","rid":"r-17","nonce":"<b64>","ct":"<b64 ciphertext>"}
// relay forwards verbatim to the peer; response comes back with the same rid
{"t":"msg","rid":"r-17","nonce":"<b64>","ct":"<b64>"}

// liveness + failure
{"t":"ping"} / {"t":"pong"}
{"t":"error","code":"workstation_offline"|"unpaired"|"revoked"|"unauthorized"}
```

`rid` correlates request/response; the plaintext inside `ct` is exactly today's MCP
JSON-RPC, so the mobile client guide (`AGENT_MOBILE_CLIENT_GUIDE.md`) stays valid — only
the envelope changes.

---

## 6. Security & privacy analysis

- **No inbound exposure.** The workstation never listens on a public port, so the
  internet-facing attack surface of a clinical machine stays **zero**. This is strictly
  safer than the port-forward option.
- **The relay cannot read PHI** (§4 crypto). Even a full compromise of AIPACS leaks
  routing metadata (which workstation talked to which phone, when, how much), not
  patient data. Metadata minimisation is worth a design pass.
- **Self-hosted matters.** Because AIPACS is *your own* infrastructure rather than a
  third-party CSP, the vendor-relationship question largely disappears. If you ever
  put a third-party tunnel (Cloudflare/ngrok) in this path, note it terminates TLS and
  would see plaintext unless you keep the E2E layer.
- **Regulatory note, not legal advice:** where HIPAA applies, US guidance is explicit
  that a cloud provider that *maintains/stores* ePHI is a business associate requiring a
  BAA **even if it cannot decrypt** the data; the "conduit exception" is narrow and
  covers transmission-only services with transient storage ([HHS guidance][hhs-cloud],
  [conduit exception][hipaa-conduit]). This is a strong technical argument for keeping
  the relay a **pure conduit that does not persist messages**, and for self-hosting it.
  Confirm the obligations for your own jurisdiction with counsel.
- **Authorisation is unchanged and still enforced on the workstation**: the per-device
  mode (`full` / `assistant` / `read_only`) runs through the existing CommandBus
  permission gate. The relay grants reachability, never authority.
- **Revocation must be two-layer**: delete the device in the AIPACS registry (it can no
  longer be routed) *and* keep the workstation-side device token check (it can no
  longer be authorised). Either alone is sufficient; both is correct.

---

## 7. What exists today vs. what to build

Already implemented (`modules/agent_gateway/`, live-verified 2026-07-17):

- ✅ `GatewayCore` — transport-agnostic request handling, bearer auth, single-use pairing
- ✅ MCP JSON-RPC bridge over the real CommandBus (77 live actions)
- ✅ QR pairing payload + device store + per-device permission modes
- ✅ A **relay client + reference relay server** (`tools/agent_relay/`) — correct shape,
  but **HTTP long-poll**, no identity registry, no E2E sealing, no resume

Phased plan:

| Phase | Work | Outcome |
|---|---|---|
| **P1** | AIPACS: `workstations` / `devices` / `pairing_tokens` tables + register/pair/revoke REST endpoints | stable identity, no IPs |
| **P2** | AIPACS: WSS relay endpoint (`/agent/ws`), route by `workstation_id`, heartbeat, online-status | reachability from anywhere |
| **P3** | Workstation: replace long-poll with a persistent WSS client + backoff/resume (`relay_transport.py`) | survives IP changes, sleep, roaming |
| **P4** | Both ends: X25519 at pairing + XChaCha20-Poly1305 sealing of every frame | relay is zero-knowledge |
| **P5** | Android: WSS client, foreground session, optional FCM push to wake | the "install → scan → works" UX |
| **P6 (opt)** | Direct-path upgrade (LAN/STUN) with relay fallback | lower latency on-site |

`GatewayCore`, `mcp_bridge`, `pairing`, `device_store` and the whole permission/audit
path are **untouched** by all of this — the change is confined to the transport and to
AIPACS.

### Mobile-side reality check

A phone cannot hold a socket open indefinitely; both reference products accept this.
Design for it: the app connects when foregrounded, reconnects instantly, and (optional
P5) uses a **push notification to wake** for long-running results. A remote *control*
UX does not need a permanently live socket.

---

## 8. Risks / open questions

- **Relay availability becomes clinical-adjacent.** If AIPACS is down, remote control is
  down (local/LAN and VPN paths are unaffected). Keep the LAN + VPN transports as
  first-class fallbacks — never make the cloud the only way in.
- **Metadata at the relay.** Connection timing/volume is visible. Consider padding and
  short log retention.
- **Key loss / re-pair.** Losing the phone must be a one-click revoke; re-pairing must
  rotate keys, not reuse them.
- **Do not let the relay accumulate state.** Every feature that "just queues a bit" moves
  it from conduit toward store — with real privacy consequences (§6).
- **Clock/replay.** Use per-direction counters, not wall-clock, for replay defence.

---

## 9. Recommendation

Build **A (cloud relay on AIPACS, outbound WSS, E2E encrypted)** as the shipping default
for customers, and **keep VPN (B) and LAN as supported transports** — VPN is already
working here and is the most private option for a single well-run clinic. Implement in
the P1→P5 order; the application layer is already done and does not change.

---

### Sources

[cc-docs]: https://code.claude.com/docs/en/remote-control
[cc-dispatch]: https://www.digitalapplied.com/blog/claude-dispatch-phone-desktop-remote-control-cowork-guide
[oai-remote]: https://learn.chatgpt.com/docs/remote-connections
[cf-tunnel]: https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/
[ts-derp]: https://tailscale.com/docs/reference/derp-servers
[ts-nat]: https://tailscale.com/blog/how-nat-traversal-works
[webrtc-ice]: https://webrtc.link/en/articles/stun-turn-servers-webrtc-nat-traversal/
[hhs-cloud]: https://www.hhs.gov/hipaa/for-professionals/special-topics/health-information-technology/cloud-computing/index.html
[hipaa-conduit]: https://www.hipaajournal.com/hipaa-conduit-exception-rule/

- Claude Code Remote Control — <https://code.claude.com/docs/en/remote-control>
- Claude Dispatch phone→desktop analysis — <https://www.digitalapplied.com/blog/claude-dispatch-phone-desktop-remote-control-cowork-guide>
- OpenAI ChatGPT/Codex remote connections — <https://learn.chatgpt.com/docs/remote-connections>
- Cloudflare Tunnel (outbound-only model) — <https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/>
- Tailscale DERP servers — <https://tailscale.com/docs/reference/derp-servers>
- Tailscale: how NAT traversal works — <https://tailscale.com/blog/how-nat-traversal-works>
- WebRTC STUN/TURN/ICE traversal rates — <https://webrtc.link/en/articles/stun-turn-servers-webrtc-nat-traversal/>
- HHS guidance on HIPAA & cloud computing — <https://www.hhs.gov/hipaa/for-professionals/special-topics/health-information-technology/cloud-computing/index.html>
- HIPAA conduit exception — <https://www.hipaajournal.com/hipaa-conduit-exception-rule/>
