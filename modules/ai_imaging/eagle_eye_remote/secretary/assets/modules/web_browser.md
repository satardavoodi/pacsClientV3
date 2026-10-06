# Module Document: Web Browser
**module_id:** `web_browser`
**Document version:** 1.0
**Sent in Phase 2 when the user issues a web / Google / URL command.**

---

## 1. What This Module Does

The built-in Web Browser opens inside a workstation tab. Voice commands
control it through module-level actions (no UI clicking). The browser tab
is a singleton: every action below opens or activates it automatically —
you never need a separate "open browser" step before searching.

**Google is the default and only search engine for voice web searches.**

---

## 2. Available Actions

### `web_search`

Searches a text query on Google and shows the results in the browser tab.

| Entity | Type | Required | Notes |
|---|---|---|---|
| `query` | string | yes | The text to search. Strip command words ("search", "on google") — keep only the actual query. |

**side_effects:** `false` — **needs_confirmation:** `false`

### `open_url`

Navigates the browser to a specific web address.

| Entity | Type | Required | Notes |
|---|---|---|---|
| `url` | string | yes | The address ("example.com" or "https://example.com"). http/https only. |

**side_effects:** `false` — **needs_confirmation:** `false`

### `open_browser`

Opens or activates the Web Browser tab without navigating anywhere.

No entities. **side_effects:** `false` — **needs_confirmation:** `false`

### `login_website`

Opens a stored website and logs in using the encrypted credential vault
(background task; success is verified and reported by notification).

| Entity | Type | Required | Notes |
|---|---|---|---|
| `site` | string | yes | Website name, label, or URL as stored in the vault. |

**side_effects:** `true` (submits a login) — **needs_confirmation:** `false`

### `agent_task_status`

Lists the agent's recent background tasks (searches, logins) and their
states. No entities. **needs_confirmation:** `false`

### `cancel_agent_task`

Cancels a queued/running background task.

| Entity | Type | Required | Notes |
|---|---|---|---|
| `task_id` | string | no | Omit to cancel the newest active task. |

**needs_confirmation:** `false`

### `browser_back`

History back. No entities. **needs_confirmation:** `false`

### `browser_forward`

History forward. No entities. **needs_confirmation:** `false`

### `refresh_page`

Reloads the current page. No entities. **needs_confirmation:** `false`

---

## 3. Structured Page Tools

Use these when the user asks what is loaded in the browser, wants page data, or
asks the agent to interact with forms/buttons. Prefer structured access over
screenshots/OCR.

Read-only:

* `browser_get_url`, `browser_get_title`
* `browser_structured_data` — metadata, JSON-LD, forms, tables, cards
* `browser_dom_snapshot {max_elements?}` — compact rendered DOM elements
* `browser_accessibility_tree {max_nodes?}` — role/name/native-control tree
* `browser_get_text`, `browser_get_html`
* `browser_get_links`, `browser_get_buttons`, `browser_get_inputs`
* `browser_find_element {selector}`, `browser_extract_table {selector?}`
* `browser_selected_text`, `browser_selected_element`
* `browser_scroll_state`
* `browser_network` — resource timing entries and captured fetch/XHR response bodies
* `browser_clear_network` — clear the captured fetch/XHR response-body buffer
* `browser_screenshot {path?}` — use after structured reads or when DOM access is insufficient

Interact:

* `browser_fill_field {selector, value}`
* `browser_type_text {text, selector?}`
* `browser_click {selector}`
* `browser_scroll {delta_y?, delta_x?, x?, y?}`
* `browser_submit_form {selector?}`

Preferred read hierarchy:
1. structured page data / DOM / table/input/button/link actions
2. accessibility-like tree
3. visible text
4. screenshot + OCR only when structured access is unavailable

---

## 4. Choosing the Right Action

* "search X on google / the web", "google X" → `web_search` with `query=X`
* "open google and search X" → `web_search` (NOT open_url)
* "open <site>.com", "go to <site>" → `open_url`
* "open the browser" (nothing else) → `open_browser`
* "go back" → `browser_back`; "go forward" → `browser_forward`
* "refresh / reload the page" → `refresh_page`
* "read this page" → start with `browser_structured_data` or `browser_get_text`
* "what fields/buttons are here" → `browser_get_inputs` / `browser_get_buttons`
* "click/fill/type/submit" → inspect first, then use `browser_click`, `browser_fill_field`, `browser_type_text`, or `browser_submit_form`
* "log into <site>", "sign in to <site>" → `login_website` with `site=<site>`
* "what is the agent doing", "task status" → `agent_task_status`
* "cancel the search/task" → `cancel_agent_task`

`web_search`, `open_url` and `login_website` run as BACKGROUND tasks:
the browser opens immediately, the agent then waits for the page, reads
its text to verify the result, saves a screenshot, and reports through
the module icon badge + the notification inbox. The user keeps working
the whole time.

## 5. Output Contract

```json
{
  "action": "web_search",
  "entities": {"query": "rotator cuff tear MRI grading"},
  "confidence": 0.95,
  "needs_confirmation": false,
  "reason": "User asked to search this phrase on Google."
}
```

## 6. Error Envelopes

`MODULE_UNAVAILABLE` (browser module not installed/enabled),
`MISSING_QUERY`, `INVALID_URL`, `ACTION_FAILED`. All recoverable; report
the message to the user.
