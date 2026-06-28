# Module Document: Web Browser (v2)
**module_id:** `web_browser`
**Document version:** 2.0 (routing-v2 overlay — adds the structured page tools that
the planner previously could not see; loaded only when AIPACS_SECRETARY_ROUTING_V2 is on)
**Sent in Phase 2 when the user issues a web / Google / URL / page command.**

---

## 1. What This Module Does

The built-in Web Browser opens inside a workstation tab. Voice/text commands control
it through module-level actions (never synthetic mouse clicking). The browser tab is a
singleton: every action below opens or activates it automatically — you never need a
separate "open browser" step before searching.

**Google is the default and only search engine for voice web searches.**

Use this module for: searching the internet, looking up a medical topic/finding online,
opening a website, navigating, and reading or filling the current page.

---

## 2. Available Actions

### `web_search`
Searches a text query on Google and shows the results in the browser tab.

| Entity | Type | Required | Notes |
|---|---|---|---|
| `query` | string | yes | The text to search. Strip command words ("search", "on google", "on the internet") — keep only the actual query/topic. |

Use `web_search` for any **information lookup** — including a medical topic, finding, or
disease (e.g. "lumbar vertebrae hemangiomas") — **even if the user does not say the word
"internet"**. Do NOT route an information/topic lookup to the patient list.

**side_effects:** `false` — **needs_confirmation:** `false`

### `open_url`
Navigates the browser to a specific web address.

| Entity | Type | Required | Notes |
|---|---|---|---|
| `url` | string | yes | The address ("example.com" or "https://example.com"). http/https only. |

**side_effects:** `false` — **needs_confirmation:** `false`

### `open_browser`
Opens or activates the Web Browser tab without navigating. No entities.

### `login_website`
Opens a stored website and logs in using the encrypted credential vault (background task).

| Entity | Type | Required | Notes |
|---|---|---|---|
| `site` | string | yes | Website name, label, or URL as stored in the vault. |

**side_effects:** `true` — **needs_confirmation:** `false`

### `browser_back` / `browser_forward` / `refresh_page`
History back / forward / reload the current page. No entities.

### `agent_task_status` / `cancel_agent_task`
List recent background tasks / cancel a queued or running one. `cancel_agent_task` takes
an optional `task_id` (omit to cancel the newest).

---

## 3. Structured page tools (read / inspect / interact)

Use these to drive the page the browser is currently showing — read its content, or fill
and submit forms (e.g. a login). Selectors are CSS selectors.

### Read (read-only)
- `browser_get_text` — return the visible page text. No entities.
- `browser_get_html` — return the page HTML. No entities.
- `browser_get_links` — list the page's links. No entities.
- `browser_dom_summary` — title/url + counts of inputs/buttons/headings. No entities.
- `browser_find_element {selector}` — locate one element and report its details.
- `browser_extract_table {selector?}` — extract a table's rows (defaults to the first table).
- `browser_get_url` — the current URL. `browser_selected_text` — the user's selection.
- `browser_screenshot {path?}` — save a screenshot of the page.

### Interact (local / server write)
- `browser_fill_field {selector, value}` — type a value into an input/textarea.
- `browser_click {selector}` — click an element (button/link).
- `browser_submit_form {selector?}` — submit a form (defaults to the password form, else the first).

---

## 4. Choosing the Right Action

* "search X on google / the web / online", "google X", a medical-topic lookup → `web_search`
* "open google and search X" → `web_search` (NOT open_url)
* "open <site>.com", "go to <site>" → `open_url`
* "open the browser" (nothing else) → `open_browser`
* "go back" / "go forward" / "refresh the page" → `browser_back` / `browser_forward` / `refresh_page`
* "log into <site>", "sign in to <site>" → `login_website {site}`
* "fill the username field with X", "enter X in the password box" → `browser_fill_field {selector, value}`
* "click login / the submit button" → `browser_click {selector}`  ·  "submit the form" → `browser_submit_form`
* "read this page / what does the page say" → `browser_get_text`
* "extract the table" → `browser_extract_table`
* "what is the agent doing", "task status" → `agent_task_status`  ·  "cancel the search" → `cancel_agent_task`

---

## 5. Output Contract

```json
{
  "action": "web_search",
  "entities": {"query": "lumbar vertebrae hemangiomas"},
  "confidence": 0.95,
  "needs_confirmation": false,
  "reason": "User asked to look up this medical topic."
}
```

## 6. Error Envelopes

`MODULE_UNAVAILABLE` (browser module not installed/enabled), `MISSING_QUERY`,
`INVALID_URL`, `MISSING_SELECTOR`, `ACTION_FAILED`. All recoverable; report the message.
