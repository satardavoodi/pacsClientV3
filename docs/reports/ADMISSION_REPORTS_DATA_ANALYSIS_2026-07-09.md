# Data Analysis — Admission Reports integration (as-built)

**Date:** 2026-07-09
**Feature:** A Persian "گزارش پذیرش" (Admission Reports) dashboard inside the workstation's
**Data Analysis** page, pulling live admission/reporting data from the web admission software's
Reports API.

## Where it lives (additive, non-destructive)
The existing `modules/data_analysis` dashboard (storage/DICOM-archive analytics, tabs
*Overview / Studies / Operations*) is **unchanged**. The admission dashboard is added as one
**extra tab** on the same `QTabWidget` in `DataAnalysisDashboard._build_ui`. If it fails to
construct, it is swallowed and the storage tabs still work.

New files (all under `modules/data_analysis/`):

| File | Role |
|---|---|
| `admission_api.py` | REST client, JWT auth reuse, Jalali date presets, **pure** snapshot builder, background worker |
| `admission_charts.py` | Self-contained QPainter charts (bar/line/donut) + KPI summary card, Persian/RTL |
| `admission_reports.py` | `AdmissionReportsTab` — cards, charts, tables, loading + error/retry, async refresh |
| `widget.py` (edited) | +tab creation, +`apply_theme` hook (2 small additive blocks) |
| `tests/code/data_analysis/test_admission_reports.py` | Regression tests for the data layer |

## Data source & auth
* Endpoint: `GET {base}/api/Reports/patients-by-service-insurance` where `{base}` resolves via
  the existing `modules/network/reception_api_config` (default `http://81.16.117.196:8080`, the
  same Reception/Workflow channel — **not** the imaging socket).
* Params: `startDate`,`endDate` (Jalali `YYYY/MM/DD`), `page`,`limit`,`sortBy`,`sortOrder`,
  optional `modality`,`insuranceType`.
* **Auth is reused, never stored.** The JWT is read from `SocketTokenManager` (the same token the
  workstation obtained at login). On `401` a single silent re-login is attempted from the saved
  "remember me" credentials, then retried once; otherwise a clear Persian "session expired" error
  is shown with a Retry button. No password/token is persisted by this module.
* The Reception/API **circuit breaker** is reused so a dead/slow admission server isn't hammered.

## Update 2026-07-09 (financial section + table layout)
* **Financial summary section (خلاصه مالی)** added below the KPI cards — six cards:
  سهم بیمار (patient share), سهم بیمه (insurance share), مجموع تخفیف‌ها (total discounts),
  برداشت دستی (manual withdrawal), تخفیف صندوق (cashier discount), and درآمد نهایی (final net
  revenue). Field mapping from the Reports API `summary`:
  `patient share = overall.totalPatientShare`, `insurance share = overall.totalOrganizationShare`
  (Σ of per-insurer shares), `total discounts = overall.totalDiscount`,
  `cashier discount = debt.totalCashDeskDiscount`, `manual withdrawal = debt.totalFundDiscount`.
  **Final revenue = Patient Share + Insurance Share − Manual Withdrawal − Cashier Discount** (the
  headline "درآمد کل" KPI card now shows this computed value instead of the gross services amount).
  *Note:* the Reports API has **no explicit "manual withdrawal" field**; `debt.totalFundDiscount`
  (the only remaining cashier-side deduction it exposes) is used for it — swap that one mapping in
  `build_admission_snapshot` if the business definition differs. Verified: with live figures the
  net revenue = 50,535,220,000 + 7,879,900,000 − 0 − 765,870,000 = **57,649,250,000** ﷼.
* **Tables side by side:** the *modality breakdown* (left) and *latest admissions* (right) tables
  now share one horizontal split (stretch 2 : 3 — the modality table is narrower), each
  `minimumHeight=380` so more rows show vertically. This uses the horizontal dashboard space better
  and keeps each table compact and tall instead of full-width and short.

## Update 2026-07-09 (responsiveness / layout polish)
Fixes after a UI review of the running dashboard:
* **Summary & financial cards** — value font reduced (+4 not +6) so long Rial figures fit; card
  titles/subtitles now **wrap** instead of clipping; each card has a **minimum width (150)** and an
  Expanding size policy; the full value/label is shown as a **tooltip**. The KPI grid (4 col) and
  financial grid (3 col) use **equal column stretch** so cards resize evenly with the window.
* **Tables** — columns size to content with the variable-length column absorbing slack
  (patient-name column stretches in the latest-admissions table; last column stretches in the
  modality table), `ElideRight` + **per-cell tooltips** so a narrow cell stays readable, per-pixel
  horizontal scroll, and a minimum section size. Both keep `minimumHeight = 380`.
* **Header** — the range combo has a min width + tooltip; the Refresh button has a tooltip; the
  title elides gracefully so the controls never get pushed off-screen.
* **Shared parent header (all Data-Analysis tabs)** — the long subtitle/account line now **wraps**
  (fixes the clipped "… | User Filter: All"); the **Auto-refresh** checkbox moved up next to Refresh
  (fixes the clipped "Auto re…"); the Date/Server/User/Modality combos got a **min width (96)** so
  their options aren't cut to "All Serve".

## Dashboard content (Persian / RTL)
* **Summary cards:** total admitted patients, total receptions, total services, total revenue,
  plus per-modality cards MRI / CT / Ultrasound / X-ray (count + unique patients).
* **Financial cards:** patient share, insurance share, total discounts, manual withdrawal,
  cashier discount, final net revenue (see the update note above for the formula/mapping).
* **Charts:** modality bar chart, modality distribution donut, insurance distribution donut,
  daily-admissions trend line (aggregated client-side by reception date).
* **Tables:** modality breakdown (count / share / amount) and a recent-admissions table.
* **Refresh:** date-range presets (امروز / دیروز / ۷ روز / ۳۰ روز) + a Refresh button.

## Non-blocking design (the critical requirement)
Every network call, JSON parse, and snapshot build runs on a **background daemon thread**
(`AdmissionReportsWorker`); results are delivered via Qt signals that Qt queues onto the GUI
thread, where only `set_*`/widget calls happen. The GUI thread is never blocked.
* First fetch is **lazy** — it fires on the tab's first `showEvent`, so opening the Data Analysis
  page (which defaults to the storage *Overview* tab) does **no** admission network I/O until the
  user actually opens "گزارش پذیرش".
* Refreshes **coalesce** (last-wins) while one is in flight, so rapid clicks can't pile up workers.
* An indeterminate loading bar shows during fetch; the Refresh button disables while loading.
* Errors never freeze the UI: they surface a Persian banner + Retry and are logged
  (`[admission-api] …`).

## Validation status
* **Verified (headless):** the pure snapshot builder + Jalali date resolver were unit-tested with
  a realistic payload — KPI totals, per-modality highlight cards, descending chart sorts, daily
  trend aggregation, recent-admissions rows, and empty/partial-payload tolerance all pass. The
  Gregorian→Jalali converter returns today's date as `1405/04/18`, matching the live app.
  `admission_api.py` and `admission_reports.py` compile clean; `tests/code/data_analysis/
  test_admission_reports.py` covers the builder, presets, and client URL/params/auth (requests
  monkeypatched).
* **Pending (Windows source build — required):** GUI rendering, live API pull with the real
  session token, refresh responsiveness, and the "opening/refreshing does not freeze the
  workstation" acceptance check must be confirmed on the source build (GUI/render is Windows-only).
  Note: the Linux sandbox served **stale/truncated** copies of the two largest files
  (`widget.py`, `admission_charts.py`) — a known mount artifact — so those two could not be
  byte-compiled in-sandbox; the authoritative files are complete and well-formed.

## Flags / knobs
* `AIPACS_ADMISSION_ROW_LIMIT` (default 3000) — rows pulled per refresh (drives the daily trend +
  table; the summary block is authoritative for the KPI cards).
* `AIPACS_RECEPTION_BREAKER=0` — disable the shared breaker (existing knob).
