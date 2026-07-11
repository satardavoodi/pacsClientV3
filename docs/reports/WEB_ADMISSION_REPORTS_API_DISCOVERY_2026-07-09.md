# Web Admission — Reports API Discovery

**Date:** 2026-07-09
**System:** Para-clinic web admission/reporting app at `http://81.16.117.196`
**Investigated page:** `http://81.16.117.196/report?type=serviceInsurance`
**Method:** Chrome DevTools Network capture + authenticated in-page fetch replay (already logged in as `administrator`).

---

## Main answer

**Yes — the Reports section is backed by a clean, self-documenting REST/JSON API, and it can be refreshed and queried programmatically and repeatedly.**

The web frontend (served on port 80) is a single-page app that pulls all report data from a separate REST API on **port 8080**. There is no server-rendered HTML for the data, no GraphQL, and no form POST — it is plain `GET` requests returning JSON.

---

## The endpoints

Base API: `http://81.16.117.196:8080/api/Reports/`

For the "Patients by Service & Insurance" report, two calls fire:

| Purpose | Method | Path |
|---|---|---|
| Row data (paginated) | `GET` | `/api/Reports/patients-by-service-insurance` |
| Aggregated summary | `GET` | `/api/Reports/patients-by-service-insurance/summary` |

Each is preceded by a CORS `OPTIONS` preflight (204), because the SPA origin (`:80`) and API (`:8080`) are cross-origin.

### Example request (verified working)

```
GET http://81.16.117.196:8080/api/Reports/patients-by-service-insurance
      ?startDate=1405/04/17
      &endDate=1405/04/17
      &page=1
      &limit=10
      &sortBy=Date
      &sortOrder=desc
Authorization: Bearer <JWT>
```

Response: `200 OK`, `Content-Type: application/json`.

---

## Query / filter parameters

The API returns its **own documentation** inside every response (`metadata.filters`). Confirmed parameters:

| Parameter | Meaning |
|---|---|
| `startDate` | Start date, Jalali format `YYYY/MM/DD` (e.g. `1405/04/17`) |
| `endDate` | End date, `YYYY/MM/DD` |
| `modality` | Section/modality code (e.g. `MRI`, `CT`, `US`); `همه` = all |
| `insuranceType` | `1`=Salamat, `2`=Tamin, `3`=Army, `4`=Free/Azad; `همه` = all |
| `page` | Page number |
| `limit` | Rows per page (the UI uses `limit=10000` to pull everything at once) |
| `sortBy` | `Date`, `totalAmount`, or `ReceptionID` |
| `sortOrder` | `asc` or `desc` |

Date range and filters are all driven by these query-string params — the UI date buttons (امروز / دیروز / هفته گذشته / ماه گذشته) just set `startDate`/`endDate`.

---

## Response format

```jsonc
{
  "success": true,
  "data": {
    "receptions": [ /* row objects */ ],
    "summary":    { "overall", "debt", "walletVsReception",
                    "byInsurance", "byModality", "byModalityAndInsurance" },
    "pagination": { "currentPage": 1, "totalPages": 22, "totalCount": 212,
                    "limit": 10, "hasNextPage": true, "hasPrevPage": false },
    "filters":    { "startDate", "endDate", "modality", "insuranceType" }
  },
  "metadata": { "reportName", "reportDate", "description",
                "fieldsDescription", "filters", "examples" }
}
```

**Pagination** is inside `data.pagination` (`currentPage`, `totalPages`, `totalCount`, `limit`, `hasNextPage`, `hasPrevPage`).

Each row in `data.receptions` includes: `_id`, `Date`, `Time`, `ReceptionID`, `modality`, `insuranceType`, `insuranceTypeLabel`, `totalAmount`, `paidAmount`, `patientShare`, `organizationShare`, `salamatInsuranceShare`, `taminInsuranceShare`, `armyInsuranceShare`, `supplementaryInsuranceShare`, `discountTotal`, `cashDeskDiscount`, `fundDiscount`, `settled`, plus nested `patientDetails`, `modalityDetails`, `physicianDetails`, `service`.

---

## Authentication

- Auth is a **JWT bearer token**. It is stored in a **readable (non-HttpOnly) cookie named `token`**; the SPA reads it and sends it as `Authorization: Bearer <JWT>`.
- Confirmed by test: request **without** the token → `401`; request **with** `Authorization: Bearer <token>` and *no* cookies (`credentials: omit`) → `200`. So the cookie value alone, used as a bearer header, authenticates.
- The JWT claims are `id`, `Name`, `username`, `iat`, `exp`.
- **Lifetime: 24 hours** (issued 2026-07-09 16:52 UTC, expires 2026-07-10 16:52 UTC). After expiry a fresh login is needed to mint a new token.
- Credentials are the same as the PACS login (`vahid`).

---

## Repeatability (verified)

| Test | Result |
|---|---|
| 3 rapid identical calls | All `200`, `success:true`, consistent `totalCount=212` |
| Different range (`1405/04/01`→`1405/04/18`), `page=2`, `insuranceType=2` | `200`, `totalCount=1046` — filtering + paging work |
| No `Authorization` | `401` |

The endpoint is stateless and safe to poll/refresh repeatedly.

---

## Deliverable summary

- **A usable API exists?** Yes — REST/JSON on `http://81.16.117.196:8080/api/Reports/…`, `GET`, query-param filtered, JSON response with pagination + summary + self-describing metadata.
- **Can authentication be reused safely?** Yes, for up to 24 h per token. Send the `token` cookie value as `Authorization: Bearer <JWT>`. The token expires daily, so any integration must re-authenticate (log in) to refresh it. Note the token sits in a non-HttpOnly cookie — handle/store it as a secret.
- **Can data be refreshed repeatedly?** Yes — idempotent `GET`, verified consistent across repeated and filtered calls.
- **Can it connect to the agent / PACS workflow later?** Yes. It's a straightforward HTTP+JWT integration. The two practical requirements: (1) a login step to obtain a fresh JWT (token endpoint not yet mapped — the current token was reused from the live session), and (2) CORS is `*` for non-credentialed requests, so a server-side/agent client (not a browser on the `:80` origin) can call it freely with the bearer header.

### Suggested next step (optional)
Map the **login/token endpoint** (likely `POST /api/.../login` on `:8080`) so an integration can mint its own 24-hour token from `username`/`password` instead of borrowing the browser session's cookie. I can capture that by watching the network during a fresh login if you want.
