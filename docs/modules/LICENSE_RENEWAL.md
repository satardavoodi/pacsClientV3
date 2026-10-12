# Signed activation and additive license renewal

Implementation date: 2026-10-07. Applies to Standard/ARM Client and Eagle Eye
Server. This is source implementation and build-input evidence, not a release,
installed acceptance or deployed-server receipt.

## User workflow

The Welcome license badge is a keyboard-accessible button. `Manage License`
shows product, current expiry and remaining days. The user generates a request,
copies or exports it, and sends it to company support using an existing support
channel. Nothing is transmitted automatically. The response can be pasted or
imported; signature, product, device, request and previous-entitlement checks run
before a preview enables `Apply Renewal`. Editing the response invalidates its
preview. Closing a management dialog preserves sign-in and the active license.

The first-install admission dialog uses the same UI. It checks storage/hardware
in an owned worker and admits the application only after validation or successful
activation. License badge refresh, import/export, verification and persistence
also run off the Qt GUI thread. A dialog cannot close during a bounded operation
that could still save a response; its worker owns no widgets.

Server Settings includes `Manage Server License` when launched with the server
deployment configuration. The desktop and the service resolve the same explicit
`license_directory`. If omitted, the directory is `licensing` beside `job_root`.
Server storage never uses the interactive user's Client license file. The server
directory must be provisioned with restricted ACLs allowing its LocalService
account and the authorized administrator to read/write the license and lock file.
Machine-scoped DPAPI alone is not an access-control boundary.

## Credit and identity contract

The company issuer computes:

`expires_at = max(verified_previous_expiry, company_UTC_issue_time) + purchased_days`

An unexpired 30-day balance plus 360 purchased days produces 390 remaining days
when issued/applied immediately. An expired license starts from issue time.
Delayed application does not move the signed expiry forward. Remaining-day
display rounds a positive partial day upward, consistently with the exclusive
UTC expiry instant. Legacy expiry retains its local-midnight meaning and is
displayed as its corresponding UTC instant.

`AIR3` requests contain only product, device fingerprint, unique request ID,
creation time, previous license proof and its previous fingerprint. They contain
no patient, account password, clinical image, prompt or report. Treat request and
response files as customer support artifacts; do not log their full contents.
Requests are reused while their base is unchanged and are valid for 30 days.

`AIP3` entitlements have an Ed25519 signature over a domain-separated canonical
payload: issuer key ID, entitlement ID, revision, device, product, request ID,
previous-proof digest, issue/expiry instants and added days. The runtime contains
public verification roots only. It neither imports the issuer nor exposes the
retired symmetric `generate_license_key` operation. The existing company GUI
remains `modules/LicenseGenerator/license_generator.py`; its protected issuance
backend lives in `tools/licensing/issuer.py`. Both generator entrypoints are
company-only and explicitly excluded from customer builds.

Applying the same response again is idempotent. A subsequent response must match
the persisted request and current base, preserve entitlement identity, use the
next revision and extend expiry. Atomic replacement and an OS byte-range/file
lock serialize service/desktop operations across processes. DPAPI protects the
entire new state: CurrentUser for Client, LocalMachine for the service. Older
unprotected JSON is accepted only as legacy Client state, never signed state.
Clock rollback beyond a five-minute allowance fails closed; the signed store
updates its observed UTC time at most hourly.

The company SQLite ledger serializes issuance with `BEGIN IMMEDIATE`. It binds
each unique order and request to one response, and keeps the latest issued
response for each product/device. The same order and exact inputs recover the
same response. Another order using the same request, a stale base, or a reused
order with changed inputs is rejected. Back up the ledger together with the
protected signing store; losing or reverting the ledger defeats its issuance
deduplication guarantees.

## Company tool and current key custody

Run `run_license_generator.bat` on the authorized company computer. It uses this
checkout's `.venv` and opens `modules/LicenseGenerator/license_generator.py`.
The folder's existing `run.bat` launches that same implementation independent of
working directory; `license_generator_gui.py` is a compatibility entrypoint.
Select the
protected signing store, enter the unique paid order reference, select the
purchased product and additional days, import/paste the request, inspect it, then
issue and copy/export the response. Editing any order input requires inspection
again. No customer runtime executable is used to issue licenses.

The first real root was provisioned on this workstation using Windows DPAPI:

- Protected store: `%LOCALAPPDATA%/AI-PACS Company Licensing/issuer-2026-10.key`.
- Ledger, created on first issuance: the same directory, `issuer-2026-10.sqlite`.
- Public export: the same directory, `public_verification.py`.
- Pinned public root: `modules/LicenseGenerator/signing_trust.py`.

The dedicated directory ACL grants this Windows account and SYSTEM access.
Unlock and public-root matching were verified; no real customer license was
issued, no live Client license was changed, and no existing service was restarted
or deployed by this implementation. The private key was never printed or stored
in Git. Copying the protected store to another Windows account does not authorize
that employee: DPAPI depends on this account/profile. Provision additional
authorized issuer roots separately on their company accounts and distribute
their public roots through a reviewed application update. A customer Eagle Eye
Server never receives a company signing private key.

For an additional root on a company Windows account, use distinct new paths in
a dedicated empty directory outside the repository:

```powershell
.\.venv\Scripts\python.exe tools\licensing\issuer.py provision `
  --private-store <absolute-company-directory>/issuer-new.key `
  --public-output <absolute-company-directory>/public_verification.py
```

Retain required existing public roots when incorporating the new public export
into `signing_trust.py`. The issuer refuses real issuance until its public root
is pinned. A CLI alternative to the UI is:

```powershell
.\.venv\Scripts\python.exe tools\licensing\issuer.py issue `
  --private-store <absolute-company-store.key> `
  --request-file <customer-request.aipreq> --output <new-response.aiplic> `
  --product client --days 360 --order-id <unique-paid-order>
```

Outputs cannot overwrite the key, ledger or request. The CLI refuses existing
output files; use the same order and a new destination to recover a response.
Protected key backup requires preservation of the authorized Windows profile /
DPAPI recovery material; this implementation does not export plaintext keys or
silently provision a replacement for a lost key.

## Legacy migration and offline limits

Existing valid Client licenses continue to start. Legacy initial activation
remains available, but new legacy issuance and legacy replacement/renewal are
retired. A migration request includes the previous proof. The company operator
must supply `approved_legacy_expiry` in UTC, checked against company sales records;
the issuer caps it at the old proof expiry. The old symmetric secret already
distributed to customers is not reliable commercial evidence. Migration uses
the approved remaining balance and the newly purchased days. Once signed state
is present, the normal save path refuses legacy keys.

Legacy compatibility remains a security gap: an adversary with full control of
an offline computer can restore/delete old state, spoof inputs, change clock
state or patch application code. DPAPI, hardware binding, file locks and freezing
do not make offline software uncrackable or prevent filesystem/VM snapshot
rollback. This is an offline issuer with OS account custody and a local ledger,
not a central authenticated issuance API, online revocation authority or HSM.
A later company-authority service and an explicit legacy cutoff are required
for stronger cross-device revocation, time and rollback guarantees. These must
not be represented as already implemented. Existing unrelated committed API
credential remediation remains the readiness report's separate release blocker.

## Eagle Eye admission

Default `create_server` always supplies the signed Server license authority.
Before authenticated new analysis, EchoMind or Secretary POST work, the handler
checks the current shared store. Missing, invalid, expired or unreadable licensing
returns HTTP 403 without executing paid work. There is no runtime bypass flag.
Capabilities, history/case reads, cancellation and completed-result downloads
remain available; expiry does not interrupt previously admitted jobs. Applying
a signed renewal through the local administration UI takes effect on the next
request without restarting the service. Remote paired Client tokens cannot
apply or issue Server licenses through the HTTP listener.

Before deploying this source to an existing server, provision its store/ACL and
signed Server entitlement; old unscoped Client keys are not Server entitlements.
An existing source/frozen pilot is not qualified by these synthetic tests.

## Verification and next-build handoff

The pre-change HEAD generator was evaluated in an isolated temporary module with
synthetic hardware: replacing a 30-day license with 360 days lost the 30-day
balance. The new contract initially failed collection because signed renewal
did not exist. Guarded cases now cover additive/expired/delayed credit, duplicate
orders/responses, stale bases, tampering, product/device isolation, migration
approval, clock rollback, corrupt/unprotected state, storage denial, Qt worker
ownership and cross-process locking.

Source UI preview: `C:/Temp/aipacs-license-renewal-preview-20261007.png`, generated
with a synthetic manager and explicit Segoe UI font registration for the Windows
offscreen platform. This is layout evidence, not a live Welcome acceptance pass.

Current automated receipts are recorded in the regression catalog and test index.
Live source GUI: pending; the documented control client's `ping` could not reach
the local test listener. Human fresh source bootstrap has been requested. No
authentication automation, second workstation instance or installed executable
was launched. Native badge click, existing-balance display, copy/import/preview,
cancel and successful real signed renewal remain separate acceptance gates.

Core licensing has no optional plugin payload mirror. Mirror dry-run proposed
zero writes; verifier checked 513 matching pairs. PyInstaller monolithic/staged
specs and Nuitka explicitly exclude company issuer modules; Nuitka explicitly
includes the core verification package. Public roots are compiled Python data,
so no customer-config trust file, optional module catalog/profile writer or
feature flag is introduced. `cryptography` was already a root dependency and is
now explicit in the licensing requirements. Builder guards check runtime import
boundaries, key-generation absence, valid pinned public roots and exclusion
parity. No installer or release build was run.

Next canonical builds: four Client candidates (Standard/ARM, both backends) and
two Eagle Eye Server candidates use these core inputs. Staff issuer is N/A in
every customer artifact. Frozen clean-host/service-account/ACL acceptance and
installed renewal remain pending under `BUILD.md` / `RELEASE.md`. An authorized
rollback must preserve and explicitly restore a compatible license store; old
binaries cannot read new DPAPI state. Do not downgrade source alone after real
signed licenses have been applied.


### Final source verification - 2026-10-07

After preserving the original LicenseGenerator folder entrypoint, isolating the
company UI import graph from PACS runtime, adding the partial-POST denial guard
and updating the local launch/build helpers, the final direct pytest selection
passed **109 tests, exit 0**, with three existing SWIG deprecation warnings, in
30.45 seconds (`--reruns 0`). The selection covered all licensing guards, builder
license-boundary and service-dependency guards, Eagle Eye reference/TLS/mTLS/role/
case/service tests and the Welcome server-picker guards. Plugin mirror verification
passed **513 matching pairs, exit 0**. Scoped `git diff --check` passed. Source
parsing and English-only checks passed for the licensing implementation and docs.
No live source GUI, real customer activation, company frozen tool, customer build
or deployed service acceptance is claimed.
