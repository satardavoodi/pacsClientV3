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

## 3. Choosing the Right Action

* "search X on google / the web", "google X" → `web_search` with `query=X`
* "open google and search X" → `web_search` (NOT open_url)
* "open <site>.com", "go to <site>" → `open_url`
* "open the browser" (nothing else) → `open_browser`
* "go back" → `browser_back`; "go forward" → `browser_forward`
* "refresh / reload the page" → `refresh_page`
* "log into <site>", "sign in to <site>" → `login_website` with `site=<site>`
* "what is the agent doing", "task status" → `agent_task_status`
* "cancel the search/task" → `cancel_agent_task`

`web_search`, `open_url` and `login_website` run as BACKGROUND tasks:
the browser opens immediately, the agent then waits for the page, reads
its text to verify the result, saves a screenshot, and reports through
the module icon badge + the notification inbox. The user keeps working
the whole time.

## 4. Output Contract

```json
{
  "action": "web_search",
  "entities": {"query": "rotator cuff tear MRI grading"},
  "confidence": 0.95,
  "needs_confirmation": false,
  "reason": "User asked to search this phrase on Google."
}
```

## 5. Error Envelopes

`MODULE_UNAVAILABLE` (browser module not installed/enabled),
`MISSING_QUERY`, `INVALID_URL`, `ACTION_FAILED`. All recoverable; report
the message to the user.
