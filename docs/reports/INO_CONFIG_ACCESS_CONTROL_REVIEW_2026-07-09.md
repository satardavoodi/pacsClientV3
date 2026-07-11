# INO Reception — Config, Auth & Access-Control Review

**Date:** 2026-07-09
**Scope:** Server-Settings "Reception / Workflow API" configuration, authentication usage, hard-code
audit, and INO role/permission handling in AI-PACS.

---

## 1. Server Settings — "Reception / Workflow API" configuration

**Location:** Settings → Server Settings → **Reception / Workflow API** card
(`settings_ui/server_settings.py::_build_reception_api_card`).

* **What it stores:** a single **base URL** (`http://host:port`) edited in `_reception_api_edit`, with
  **Test / Save / Load** buttons. Save → `ReceptionApiConfig.set_base_url(normalized, save_to_file=True)`
  → persisted to `config/reception_api_config.json` (fields `reception_api_base_url` +
  synced `scheme`/`host`/`port` + `request_timeout`), then `reload_reception_api_config()`.
* **Center-specific config is supported** two ways:
  1. The shared base URL above (per install).
  2. **Per server profile** (multi-center): `server_profiles.py` exposes a `reception_api` module
     endpoint per profile; `get_reception_api_base_url()` returns the **active profile's** reception
     endpoint when profiles are enabled (`("reception_api", "Reception / Workflow API", 8800, True)`
     is the profile slot). Switching center (Razi ↔ Mehr) switches the reception endpoint too, with
     an independent circuit breaker per base URL.
* **Resolution precedence** (`reception_api_config.get_reception_api_base_url`): env override
  (`AIPACS_RECEPTION_BASE_URL` / `RECEPTION_API_BASE_URL`) → active server profile → config file →
  hard-coded default. Timeout via `get_reception_api_timeout()`.

**Minor findings (not bugs):**
* The **default** host constant is a specific center's IP (`_DEFAULT_HOST = "81.16.117.196"`, port
  8080) — a fallback for installs with no config. Other centers simply set their own URL in Settings.
  Consider making the shipped default blank/neutral so a mis-configured new center fails loudly rather
  than silently hitting another center's server.
* The profile-slot default port shown is **8800** while the standalone default is **8080** — cosmetic
  inconsistency; the actual value always comes from config/profile.

---

## 2. Hard-code audit — connection details

**Result: no INO call-site hard-codes the address/port.** Every reception call resolves the base URL
from `get_reception_api_base_url()`:

* `modules/data_analysis/admission_api.py`, `modules/network/ino_report_workflow.py`,
  `ai_imaging/.../reception_data_service.py` (→ `reception_data_tab`), `EchoMind/.../ai_chat_pages.py`,
  `home_ui/patient_table_widget.py` (comment sync) — all use the resolver.

The only literal `81.16.117.196` occurrences in shipped code are: the **configurable default constant**
in `reception_api_config.py`, doc/comment strings, a commented-out `#base_url` in
`ai_chat_interactorstyle.py`, and test fixtures. Nothing else pins the address at a call site.

---

## 3. Authentication — logged-in user's credentials

* **Same credentials as the user's normal login.** The workstation login (physician/user
  username+password) authenticates over the socket channel and yields a **JWT**, stored once in
  `SocketTokenManager`. Every INO REST call attaches that same JWT as `Authorization: Bearer <token>`.
  No separate reception credentials exist, and no password is stored by the reception layer.
* **Token refresh.** Most paths treat `401` as "session expired → log in again" (e.g. the Report
  Editor shows exactly that). The Data-Analysis client additionally does a single silent re-login from
  saved "remember me" credentials. There is no background token-refresh timer; the token's ~24 h
  lifetime is renewed by re-login. (Recommendation: a shared silent-reauth-on-401 for all reception
  calls would smooth day-boundary expiry — currently only the admission client has it.)
* All requests use the **configured** server address/port (§2) and the **logged-in** user's token
  (§3) consistently.

---

## 4. INO roles & access control (live-observed)

INO implements **role-based access control**:

* The login `user.roles` object = `{ _id, Name: "administrator", PermisionsID: [ …ObjectIds… ] }` —
  a role name plus a list of permission ids the role grants.
* INO's own web app **gates actions client-side** with `permissions.includes(<permissionId>)` (approve
  / edit / status buttons are shown/enabled only when the role holds the matching permission id).
* INO **enforces server-side** at least for workflow rules: the status endpoint
  `PATCH …/workflow/report/status` returns **HTTP 400** for an illegal transition
  (`"تغییر وضعیت … مجاز نیست"`). Physician-approval and secretary-approval are **distinct** flags
  (`physicianApproved` / `secretaryApproved`) set via `PATCH …/workflow/report/approval-flags`, and are
  conceptually separate permissions.

**Not conclusively verified (needs INO confirmation):** whether the **approval-flags** and
**update-report** endpoints reject a call from a role that lacks the permission (i.e. server-side role
enforcement, not just client-side button-hiding). This could not be tested here because the available
account is `administrator` (holds every permission). **This is the key open question** — see §6.

---

## 5. How AI-PACS handles permission errors (reviewed + improved)

* **Report save (update-report)** already surfaces access errors clearly:
  `reception_data_tab._save_report_to_api` shows dedicated dialogs for **401** ("Invalid or expired
  token…"), **403** ("You don't have permission for this operation."), and **404**. EchoMind shows the
  server `message` on failure. ✅ No bypass — AI-PACS calls the same endpoint with the user's token and
  reflects INO's decision.
* **Approval-flags sync (new).** Previously fire-and-forget: a rejection was only logged. **Fixed**
  (`ino_report_workflow.py`):
  * `_classify_error()` tags responses as `permission` (HTTP 403 or a Persian/English "not
    allowed / no access / forbidden / unauthorized" message), `auth` (401), or `http`.
  * On a permission/auth rejection it **logs clearly**
    (`[ino-approval] PERMISSION DENIED by INO …`) **and emits a Qt signal** (`get_notifier().sync_failed`)
    that a GUI-thread listener (`install_ui_notifier()`, wired where the "Change Report Status" UI is
    built) turns into a **user dialog** ("شما مجاز به انجام این عملیات (تأیید گزارش) نیستید"). So a user
    whose role can't approve now **sees** INO's rejection instead of the change silently not taking.
  * AI-PACS never overrides the result — a failed PATCH leaves the flags as INO decided.
* Tests: `tests/code/network/test_ino_report_workflow.py` (classification, permission-denied
  notification, success-no-notify) + `test_report_status_approval_flags.py`.

---

## 6. Recommendations / open items

1. **Confirm server-side role enforcement with the INO team** for `update-report`,
   `…/workflow/report/status`, and `…/workflow/report/approval-flags`. If INO only gates client-side,
   AI-PACS (which calls the API directly) would bypass the button-hiding — in that case AI-PACS must
   add **proactive permission checks** (see #2). If INO enforces server-side (expected), the current
   design is correct: AI-PACS attempts the action and surfaces the rejection.
2. **Optional proactive gating (mirror INO's UI):** resolve the role's `PermisionsID` to action names
   and disable/hide the physician-approve / secretary-approve / complete choices in the status dropdown
   when the user lacks the permission — matching INO's own web UI. This needs the permission-id →
   action-name map from INO (the web app references `/rolesPermissions` and
   `/usersPermissionsSettings`; the exact resolved permission constants weren't retrievable with the
   admin account here). Track as a follow-up once INO provides the permission catalog.
3. **Distinct physician vs secretary approval permissions:** the flags are separate; when proactive
   gating is added, gate each independently (a secretary must not be offered "Physician Approved").
4. **Neutral shipped default** for `reception_api_config` host (§1) so a new, unconfigured center can't
   silently reach another center's INO.
5. **Shared silent re-auth on 401** across all reception calls (currently admission-only) for smoother
   token expiry handling.

### Verdict
Config is centralised and center-specific (Settings + per-profile); no hard-coded connection details;
the logged-in user's credentials/token are used consistently; permission errors are now handled and
shown clearly (report save already did; the approval sync now does too). The one thing to **confirm
with INO** is whether the workflow/approval endpoints enforce roles server-side — that answer decides
whether the optional proactive permission-gating (#2) is required to fully honour INO's access rules.

_Related: `docs/pipelines/ino-reception-connection.md`,
`docs/reports/AINO_RECEPTION_STATUS_SYNC_REVIEW_2026-07-09.md`._
