# Browser Control Tools (Secretary e Command ↔ Web Browser)

**Date:** 2026-06-27
**Module:** `modules/web_browser` (controller API) + `modules/EchoMind/secretary/adapters/browser_command_adapter.py` (bus actions)
**Status:** Implemented. Reachable on every bus transport — the voice/text Secretary, the
in-app CommandBus, the Test Control Server, and the external FastMCP server
(`tools/testing/aipacs_control_mcp`, via `list_actions` / `raw_command` and any dedicated
`@mcp.tool` wrappers).

The Secretary e Command agent drives the embedded Web Browser through **structured commands**,
not synthetic mouse/keyboard. Each tool is a CommandBus action handled by `BrowserCommandAdapter`,
which resolves the live `WebBrowserWidget` (opening/activating the browser tab when needed) and
calls its controller method. Page reads run a sandboxed, self-contained JavaScript snippet
(`modules/web_browser/page_tools.py`) through a **bounded** synchronous helper (`_run_js_sync`,
hard 2.5–3.5 s timeout) so a tool can never hang the UI.

## How it flows

```
Secretary brain / MCP client
   → CommandBus.execute(CommandPlan(action, entities))
   → registry.dispatch (permission gate: permissions.py)
   → BrowserCommandAdapter.<handler>(plan, state)
   → WebBrowserWidget.<controller method>      ← real app code path
   → CommandResult(ok, message, data={...})
```

`CommandResult.data` carries the page content/result; `ok` + `error_code` + `message` report
status. When the module is disabled/closed every tool degrades to a typed
`MODULE_UNAVAILABLE` envelope (never a silent failure or exception).

## Tool reference

`entities` is the `CommandPlan.entities` dict. The **action** is the bus action id; the
**alias** column is the conceptual `browser.*` name from the integration request.

| Action (bus id) | Alias | Entities | Returns (`data`) | Side-effect |
|---|---|---|---|---|
| `open_browser` | `browser.open` | – | `widget_class` | UI nav |
| `browser_navigate` / `open_url` | `browser.navigate` | `url` | `url` | server write |
| `browser_go_back` | `browser.go_back` | – | – | UI nav |
| `browser_go_forward` | `browser.go_forward` | – | – | UI nav |
| `browser_reload` / `refresh_page` | `browser.reload` | – | – | UI nav |
| `web_search` | – | `query` | `query`, `engine` | server write |
| `browser_get_url` | `browser.get_current_url` | – | `url` | read-only |
| `browser_get_title` | `browser.get_page_title` | – | `title` | read-only |
| `browser_get_text` | `browser.get_page_text` | – | `text`, `length`, `url` | read-only |
| `browser_get_html` | `browser.get_page_html` | – | `html`, `length`, `url` | read-only |
| `browser_dom_summary` | `browser.get_dom_summary` | – | `summary` (title/url, counts, headings, inputs, buttons) | read-only |
| `browser_dom_snapshot` | `browser.get_dom_snapshot` | `max_elements` | compact rendered DOM elements | read-only |
| `browser_accessibility_tree` | `browser.get_accessibility_tree` | `max_nodes` | role/name/native-control tree | read-only |
| `browser_find_element` | `browser.find_element` | `selector` (CSS) | `element` (found/tag/id/name/type/text/href/visible) | read-only |
| `browser_get_inputs` | `browser.get_inputs` | `max_inputs` | `inputs[]`, `count` | read-only |
| `browser_get_buttons` | `browser.get_buttons` | `max_buttons` | `buttons[]`, `count` | read-only |
| `browser_fill_field` | `browser.fill_field` | `selector`, `value` | `selector` | local write |
| `browser_type_text` | `browser.type_text` | `text`, `selector?` | `selector`, `length` | local write |
| `browser_click` | `browser.click_element` | `selector` | `selector` | local write |
| `browser_scroll` | `browser.scroll_page` | `delta_x`, `delta_y`, `x`, `y` | scroll position | UI nav |
| `browser_scroll_state` | `browser.get_scroll_state` | – | scroll position + document size | read-only |
| `browser_submit_form` | `browser.submit_form` | `selector` (optional) | – | server write |
| `browser_selected_text` | `browser.get_selected_text` | – | `selected_text` | read-only |
| `browser_selected_element` | `browser.get_selected_element` | – | active/focused element | read-only |
| `browser_extract_table` | `browser.extract_table` | `selector` (optional) | `table.found`, `table.rows[][]` | read-only |
| `browser_structured_data` | `browser.extract_structured_page_data` | – | metadata, JSON-LD, forms, tables, cards | read-only |
| `browser_get_links` | `browser.get_links` | – | `links[]` (`text`,`href`), `count` | read-only |
| `browser_network` | `browser.read_network_responses` | – | recent PerformanceResourceTiming entries + captured fetch/XHR response bodies | read-only |
| `browser_clear_network` | `browser.clear_network_responses` | – | clears the capture buffer | read-only |
| `browser_screenshot` | `browser.take_screenshot` | `path` (optional) | `path` | read-only |

When `submit_form` / `extract_table` are called with no `selector`, they target the form that
holds a password (else the first form) and the first `<table>` respectively.

## Preferred Agent Read Hierarchy

The browser agent should not depend on screenshots/OCR as its first source. Use
this order:

1. Structured data and DOM/API-derived state:
   `browser_structured_data`, `browser_dom_snapshot`, `browser_get_inputs`,
   `browser_get_buttons`, `browser_get_links`, `browser_extract_table`,
   `browser_network`.
2. Accessibility-like tree:
   `browser_accessibility_tree`.
3. Visible text:
   `browser_get_text`.
4. Screenshot/OCR:
   `browser_screenshot`, then OCR only when structured access is unavailable.

`browser_network` returns browser performance/resource metadata and captured
fetch/XHR response bodies. The capture is implemented by injecting a main-world
script at document creation that wraps `fetch` and `XMLHttpRequest`. It captures
calls made after the script is installed, stores a bounded recent buffer, and
caps text/JSON-like bodies. Binary responses, opaque responses, navigations that
happen before injection, service-worker-internal traffic, and browser-level
requests outside page JS may still only appear as timing/resource metadata.
Use `browser_clear_network` before a workflow when a clean capture buffer is
needed.

Network response-body capture is default-on. Set
`AIPACS_BROWSER_NETWORK_CAPTURE=0` only when the capture wrapper must be disabled
for debugging or compatibility.

## Safety / permission model

Classification lives in `modules/EchoMind/secretary/permissions.py` (`ACTION_SIDE_EFFECTS`) and is
enforced at the single dispatch choke point. Reads are `READ_ONLY` (allowed even in a read-only
session); `fill_field`/`click_element` are `LOCAL_WRITE`; `browser_navigate`/`browser_submit_form`
are `SERVER_WRITE` (network egress) and require confirmation in `assistant` / `server_write` modes,
matching `open_url`. The gate is **inert** for the default/unscoped caller and for `qa` mode, so
existing behaviour is unchanged. Kill switch: `AIPACS_AGENT_PERMISSIONS=0`.

Selectors and values are **JSON-encoded into the JavaScript** (never string-concatenated), so a
hostile selector/value cannot break out of the JS literal, and every snippet is wrapped in
try/catch returning a safe default.

## Examples

Read the current page as text:

```json
{ "action": "browser_get_text", "entities": {} }
→ { "ok": true, "message": "Read 4213 characters of page text.",
    "data": { "text": "...", "length": 4213, "url": "https://..." } }
```

Inspect, fill, and submit a login form:

```json
{ "action": "browser_dom_summary", "entities": {} }
{ "action": "browser_fill_field", "entities": { "selector": "#username", "value": "drsmith" } }
{ "action": "browser_fill_field", "entities": { "selector": "#password", "value": "•••" } }
{ "action": "browser_submit_form", "entities": {} }
```

Extract a results table:

```json
{ "action": "browser_extract_table", "entities": { "selector": "table.results" } }
→ { "ok": true, "data": { "table": { "found": true, "rows": [["Name","Date"], ["...","..."]] } } }
```
