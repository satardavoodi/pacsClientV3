# Secretary Echo Mind: MCP, image understanding and mobile review

Date: 2026-10-01. Scope: source review and focused automated verification; no runtime changes or deployment.

## Current architecture

Secretary records/transcribes through the shared VoiceTranscriptionService, requests company route/plan/repair from the authenticated Eagle Eye Server, validates the returned proposal locally, and executes through SecretaryExecutor/CommandBus/adapters. The external test MCP and production Agent Gateway expose the same execution spine. Secretary does not need a stdio MCP loopback to control its own application.

The September 30 routing decision supersedes older references to client-owned company prompts and direct GapGPT planning in the July unified-entrypoint document and June instruction map. These historical documents also describe capture/measurement capabilities as missing even though the current factory registers them.

## Function coverage found in source

| Area | Current action examples | Boundary |
|---|---|---|
| Home | list/search/read/select/open/download patients | Requires live Home adapter and authoritative study identity |
| Viewer | change_series, switch_tab, change_layout, scroll_slices | Registered when viewer-write wiring is enabled |
| Observation | query_viewport_state, get_viewport_context, get_series_info | Read state and identity before actions |
| Images/tools | capture_viewport, activate_tool, measure_distance, get_measurements | Tool activation and distance placement currently require FAST Qt viewport |
| Downloads | list/status/pause/resume/cancel/statistics | Device policy and confirmation still apply |
| Modules | MPR, Eagle Eye, printing, education, browser, reporting | Availability depends on registered launchers/adapters; an action name is not proof of live support |

Evidence: modules/EchoMind/secretary/bus_factory.py; adapters/viewer_write_adapter.py; tools/testing/aipacs_control_mcp/server.py. Discover actual actions from the running bus rather than assuming every module is installed.

## Image understanding gap

get_viewport_context reads slice metadata, geometry and viewport transforms. capture_viewport grabs a viewport or patient tab, saves a PNG under the local EchoMind agent-artifact directory, and returns a local path, viewport and study UID. It does not return a correlated immutable image/context bundle. Capture currently saves synchronously in its adapter; future work must split GUI capture from worker encoding/storage/upload.

The production McpBridge serializes action results as text JSON. It does not turn a capture path into an MCP image content block or authenticated remotely readable image resource. A phone cannot obtain pixels merely from a Windows path.

The current /v1/secretary/plan schema is text-only and rejects additional fields. Existing capture tools and server-side viewer instructions do not establish a functioning multimodal analysis loop. No complete point/ROI-to-image-to-server-analysis flow was established by this review. Existing Eagle Eye imaging features need separate capability qualification before reuse here.

Required next slice: an authenticated server-owned image-analysis contract, bounded pixel transfer, and one shared local action for Secretary and MCP. Bind each request to study/series/SOP identity, frame/slice, viewport/domain, render revision, orientation, pixel spacing, window/level and transform. Bind a user point or ROI to that snapshot in image coordinates. Reject stale results after navigation; do not infer what “here” means without a selected point/ROI or clarification. Capture/context must represent the same revision. Keep prompts/models/provider credentials server-owned and preserve the explicit personal OpenAI exception.

Remote image delivery should use bounded authorized image content or an opaque short-lived resource, not arbitrary filesystem access. Define overlay redaction, image size/count bounds, retention and access scope. Distinguish rendered appearance from original DICOM pixels and diagnostic analysis from OCR. Preserve Fast, Advanced and each VTK execution domain.

## Mobile and Settings

Settings Agent UI is implemented in PacsClient/pacs/workstation_ui/settings_ui/agent_settings.py: enable/status, LAN/relay selection, advertised endpoint, TLS, QR pairing, device permission selection and revocation. GatewayCore authenticates devices; McpBridge implements initialize/tools/resources and dispatches through GUI dispatch to the shared bus. Production remote access is distinct from the opt-in local Test Control Server.

Pairing uses a short-lived single-use code and certificate fingerprint; stored tokens are hashed. Relay code implements encrypted transport and reconnect behavior. These implementations do not prove a currently connected mobile app, deployed relay, or a shared Secretary conversation. The inspected gateway calls actions, not the Secretary natural-language planner; a server-planning mobile workflow must be qualified separately and must honor the Eagle Eye routing authority.

Acceptance should cover phone pairing, tools/list, read-only context, image retrieval, a selected point/ROI, server analysis, stale-study rejection, confirmed actions, reconnect/retry with operation identity, and device revocation. Report each outcome separately. Never substitute a /health response or tools/list for the complete workflow.

## Verification

No aipacs-control tool is exposed in this session inventory. The documented client.py ping failed with an unavailable local named socket. No app restart, launch flag change, login, pairing, clinical action, screenshot or external inference was performed. Live Secretary/image/mobile acceptance remains unverified.

Focused automated verification: 71 passed, exit 0 (Secretary unified entrypoint, remote planner, Agent Gateway, command lifecycle and viewport capture). Three existing TLS datetime deprecation warnings were reported. This review and its companion skill introduce documentation only; automated tests qualify the inspected existing source, not new runtime behavior.

## Later implementation receipt

The same-day settings and shared-action candidate supersedes the initial missing-allowlist and false-launch findings in source. See [the implementation receipt](SECRETARY_SETTINGS_IMPLEMENTATION_2026-10-01.md) for actual scope, tests, mirrors and pending GUI/server deployment. Image analysis, remote pixels and Advanced Analysis execution are not thereby completed.
