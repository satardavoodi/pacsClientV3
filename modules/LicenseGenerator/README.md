# LicenseGenerator structure

This is the existing AI-PACS licensing module, including the company generator.
The 2026-10-07 renewal implementation preserves its canonical entry point and
its `run.bat` / `build.bat` paths.

| File | Responsibility | Customer build |
| --- | --- | --- |
| `license_generator.py` | Company GUI: inspect customer request, verify purchased product/order, issue signed response | Excluded |
| `license_generator_gui.py` | Compatibility entry point to the same company GUI | Excluded |
| `license_manager.py` | Stable device fingerprint and read-only legacy verification; symmetric generation retired | Included for migration |
| `legacy_proof.py` | Read-only legacy proof parsing; company-record approval still required | Included |
| `renewal.py` | Current entitlement, additive renewal, request/base binding, protected atomic state and interprocess locking | Included |
| `signed_license.py` | Bounded canonical codecs and public-key signature verification | Included |
| `signing_trust.py` | Pinned public verification roots; never private keys | Included |
| `protection.py` | Windows DPAPI storage wrappers | Included |
| `manage_dialog.py` | Client / Server license management and renewal preview | Included |
| `license_dialog.py` | First-install activation and responsive startup admission | Included |
| `async_ui.py` | Owned Qt worker bridge | Included |
| `code_files.py` | Bounded request/license file I/O used by workers | Included |

The company signing backend is `tools/licensing/issuer.py`, deliberately outside
the customer runtime package. It is imported only by the company GUI. Its private
key and order ledger are outside this repository in the protected company Windows
account store. `tools/licensing/generator_gui.py` remains a compatibility wrapper.

Run this folder's `run.bat` or the repository's `run_license_generator.bat`; both
open this folder's `license_generator.py` using the project's `.venv` regardless
of current working directory. `build.bat` retains the existing company tool name
and local `dist` / `build` directories, pins the project import path and refuses
implicit dependency installation. It does not bundle the external private store
or ledger. No company frozen build was run during implementation.

Customer Client/Server packaging follows the repository `BUILD.md` / `RELEASE.md`
only. Both backends exclude the two company entry points and `tools.licensing`.
The company tool can verify old proofs but cannot grant old balance without an
explicit company-approved expiry. The runtime cannot issue new symmetric keys.

Full workflow, key custody, legacy/offline limitations and current verification:
[Signed renewal implementation](../../docs/modules/LICENSE_RENEWAL.md).
