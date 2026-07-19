# AI-PACS Agent Gateway — reference relay server

Deploy this when you want the mobile agent app to reach a workstation that is
**off the clinic network** (Reachability = Relay in *Settings ▸ Agent*). The
workstation dials OUT to this relay and long-polls it; the phone reaches the
workstation through the relay's public `/client/<workstation_id>/...` path. No
inbound firewall port is opened on the clinic PC.

`relay_server.py` is a **reference** — stdlib only, ~250 lines, no dependencies.
It is correct and runnable; for production add TLS (via a reverse proxy), rate
limiting, and per-workstation quotas.

## Run

```bash
# on your VPS / cloud host
python3 relay_server.py --port 9000 --token "$(openssl rand -hex 24)"
```

Put it behind HTTPS (nginx/Caddy) so both the workstation and the phone use
`https://relay.example.com`. The `--token` (or `AIPACS_RELAY_TOKEN`) authenticates
the **workstation** to the relay; set the same value in *Settings ▸ Agent ▸ Relay
auth token*.

## Security

The relay is a **dumb pipe**. It never sees a valid device token — device-token
auth is validated end-to-end on the workstation. A compromised relay can deny
service or observe metadata, but cannot call workstation functions. Still, run it
on a host you control, keep the relay token secret, and always terminate TLS.

## Protocol

See `docs/for-future-agents/AGENT_MOBILE_PAIRING_PROTOCOL.md` §8. The workstation
side is implemented in `modules/agent_gateway/relay_transport.py`.
