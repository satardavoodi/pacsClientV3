# Secretary and MCP module coverage

Date: 2026-10-01. Source review only; no runtime edits. Owner-confirmed terminology: EGLI and spoken variants of Eagle Eye refer to Eagle Eye (the workstation's Eagle Eye module).

| Module | Direct shared-bus MCP coverage | Secretary planning coverage | Limits |
|---|---|---|---|
| Education | Open module, courses, Case of the Day, consultation, consultant directory, library search; background education search | Navigation/search actions are present in client and server allowlists | No complete authoring, import/export, slide navigation or presentation-control action surface established; search/navigation return does not prove content loaded |
| Browser | Navigation/search, DOM/accessibility inspection, text/HTML, fields/click/submit/scroll, tables/links/network and screenshot | Browser actions are present in both allowlists | Requires actual WebEngine readiness and callback/result qualification; these tests do not certify every real-page interaction |
| Advanced Analysis | No dedicated adapter or Home launcher registration found for advanced_analysis; run_analysis/export_report are not registered by current bus_factory | Both action names absent from client and server allowlists | Catalog module describes capabilities beyond executable control. Runtime lives under modules/mpr/advanced_3d_slicer and has its own resident-process protocol; that protocol is not itself a connection to the shared MCP bus |
| Eagle Eye | eagle_eye_open/series/select_series/functions/run/status/inputs implemented and factory-registered; stdio and Gateway sharing tested | Detailed eagle_eye_* actions absent from both Secretary allowlists; legacy toggle_eagle is allowed | Direct MCP capability does not establish natural-language Secretary access, completed inference or all-modality support |

## Material findings

Production Home wiring registers eagle_ai, echomind, mpr, printing, education and web_browser launchers, but not advanced_analysis. Inspect PacsClient/pacs/workstation_ui/home_ui/home_panel/widget.py and modules/EchoMind/secretary/bus_factory.py.

EducationCommandAdapter implements five section/search actions and returns typed unavailable errors. It does not expose the entire Education UI. BrowserCommandAdapter exposes a much wider structured-page surface. Both are shared bus adapters and therefore available through production McpBridge when registered. Dedicated stdio wrappers are not required for production Gateway tools/list, which enumerates live bus actions.

EagleEyeCommandAdapter requires study identity, checks unique series/study linkage, requires ready series before function selection/run and exposes status/inputs. Existing focused tests cover study mismatch, wrong-series ROI, read-only denial, failed-job status and shared stdio/Gateway execution. Secretary client validator.py and server secretary/validation/validator.py do not allow these detailed actions. The same allowlist check also found get_viewport_context and capture_viewport absent, despite their bus registration. These gaps prevent claiming Secretary parity with direct MCP.

ModuleCommandAdapter._dispatch returns ok=True even if its launcher returns None, with data.opened=False. Callers must check opened and actual module state; treating ok alone as launch success is incorrect. This is an existing issue observed during review, not fixed here.

## Next implementation slices

1. Align detailed Eagle Eye and image-observation contracts across client/server validators, catalogs, schemas and executor routing, retaining action-specific permissions and study identity. Add fail-before guards and separate live acceptance.
2. Add explicit Advanced Analysis actions through its owned runtime service, without borrowing Fast/Advanced viewer internals. Define readiness, selected source, operation identity, status, cancellation and bounded result retrieval before advertising analysis tasks.
3. Extend Education only for concrete requested workflows, with result observation as well as navigation. Verify Browser DOM reads and mutations on actual loaded pages rather than using command acceptance as completion.
4. Guard launcher failure and readiness semantics; preserve concurrent work and follow repository regression/mirror rules for any future fix.

## Verification

Focused pytest selection: test_browser_education_adapters.py, test_module_adapter.py, test_eagle_eye_mcp_commands.py and test_agent_gateway_wiring.py: 63 passed, exit 0. These tests exercise existing synthetic adapters/wiring, not a live complete module workflow.

Synthetic import-based checks confirmed client/server allowlist membership for open_courses and browser_dom_snapshot, and absence for eagle_eye_open, eagle_eye_run, run_analysis, export_report, get_viewport_context and capture_viewport.

Documented client.py ping failed with unavailable local test socket. Live action inventory and module acceptance could not be obtained. No launch/restart, login, pairing, clinical action, model call or settings mutation was performed. No current mobile or deployed-server acceptance is claimed.

## Later implementation receipt

The same-day settings and shared-action candidate supersedes the initial missing-allowlist and false-launch findings in source. See [the implementation receipt](SECRETARY_SETTINGS_IMPLEMENTATION_2026-10-01.md) for actual scope, tests, mirrors and pending GUI/server deployment. Image analysis, remote pixels and Advanced Analysis execution are not thereby completed.
