# Web Admission — Authentication Token Test

**Date:** 2026-07-09
**Server:** `http://81.16.117.196` (API service on port **8080**)
**Credentials:** same as main software login (`vahid` / provided password)
**Method:** Live authenticated fetch tests against the API from the browser. No token values are printed anywhere in this report.

---

## Main result

**The authentication flow works reliably for getting a token, using it, and obtaining a fresh token on re-login.** The service uses **stateless JWT** auth: a login endpoint issues a 24-hour token, that token authenticates every API call as a `Bearer` header, and re-login always returns a new working token. There is **no functional server-side logout / refresh** on this service — "logout" is client-side (discard the token) and "refresh" means logging in again.

Mapping to the requested 9-step flow:

| Step | Result |
|---|---|
| 1. Connect to server (provided IP) | OK — API reachable at `:8080` |
| 2. Send login with username/password | OK — `POST /api/auth/login` |
| 3. Valid token returned | OK — JWT in response body, `success:true` |
| 4. Store/log token safely | Done — captured in memory only, never exposed |
| 5. Use token on an authenticated endpoint | OK — Reports endpoint returns `200` with the token |
| 6. Logout | No server endpoint (stateless JWT) — client-side discard only |
| 7. Old token invalidated? | **No** — token stays valid until its 24 h expiry |
| 8. Log in again | OK |
| 9. New token generated | OK — new token differs from the first and works |

---

## Login endpoint

```
POST http://81.16.117.196:8080/api/auth/login
Content-Type: application/json

{ "username": "vahid", "password": "<password>" }
```

- **Method:** `POST`
- **Required headers:** `Content-Type: application/json`
- **Body:** JSON `{ username, password }`
- **Auth base:** the SPA builds it as `http://{ip}:{port}/api` from its configured server settings; for this install that resolves to `http://81.16.117.196:8080/api`.

### Success response (`200`)

```jsonc
{
  "success": true,
  "message": "ورود موفقیت‌آمیز",     // "Login successful"
  "token":   "<JWT>",                // the bearer token
  "user":    { "id", "username", "full_name", "role", "permissions" }
}
```

### Token structure

- Format: **JWT** (`header.payload.signature`).
- Payload claims: `id`, `username`, `fullName`, `role`, `iat`, `exp`.
- **Lifetime: 24 hours** (`exp − iat`).
- Sent on every subsequent request as `Authorization: Bearer <JWT>`.
- In the running web app the same token is also kept in a browser cookie named `token` (non-HttpOnly).

---

## Using the token (verified)

```
GET http://81.16.117.196:8080/api/Reports/patients-by-service-insurance?startDate=1405/04/17&endDate=1405/04/17&limit=1
Authorization: Bearer <JWT>
```
→ `200 OK`. Without the header the same call returns `401`. Confirmed the freshly minted token authenticates real endpoints.

---

## Logout

- **No working logout endpoint on this service.** `POST /api/auth/logout` → `404` (also `/auth/logout`, and on port 80 → `404`).
- The frontend bundle references `/auth/check`, `/auth/logout`, `/auth/role`, but these return `404` on this backend build — they are either unused or belong to a separately-configured backend. Only `/api/auth/login` and `/api/Reports/*` are live on `:8080`.
- Because the JWT is **stateless**, logout is handled client-side by discarding the token/clearing the cookie. **The token itself is not revoked server-side** and remains valid until it expires — confirmed: after the (non-existent) logout call, the same token still returned `200` on the Reports endpoint.

## Refresh / re-login

- **No refresh endpoint** (`/api/auth/refresh` → `404`). To "refresh," call `/api/auth/login` again.
- **Re-login verified:** a second login with the same credentials returned `success:true` and a **new token that differs from the first**, and that new token authenticated successfully. Reconnecting cleanly with the same software credentials works reliably.

---

## Errors / notes observed

- `POST /auth/login` (without the `/api` prefix) → `401`. The correct path is `/api/auth/login`.
- All non-existent auth routes (`/api/auth/check|logout|role|me|verify|refresh`) → `404`.
- CORS: the API answers non-credentialed cross-origin requests (bearer-header style), so a server-side/agent client can call it directly.

### Security note
The token is a full-access bearer credential valid for 24 h and lives in a **non-HttpOnly `token` cookie** (readable by page scripts). Treat it as a secret: store it server-side/encrypted for any integration, never in URLs or logs. There is no server-side revocation, so a leaked token is usable until expiry.

---

## Deliverable summary

- **Login endpoint:** `POST http://81.16.117.196:8080/api/auth/login`
- **Request method:** `POST`, JSON body
- **Required headers/body:** `Content-Type: application/json`; `{ username, password }`
- **Token response structure:** `{ success, message, token (JWT, 24 h), user{id,username,full_name,role,permissions} }`; used as `Authorization: Bearer <JWT>`
- **Logout endpoint:** none functional — stateless JWT, client-side discard; token not revoked server-side (valid until expiry)
- **Does re-login work:** Yes — issues a new, distinct, working token every time
- **Auth issues:** none in the valid flow; only expected `401`/`404` on wrong path/method. No refresh endpoint (re-login instead).

**Conclusion:** the software can reliably get a token, use it, obtain a new one, and reconnect cleanly with the same credentials. The only caveats are that logout is client-side only (no server revocation) and tokens must be refreshed by re-login every 24 hours — both fully workable for an agent/PACS integration.
