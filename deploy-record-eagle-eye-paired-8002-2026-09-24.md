# Eagle Eye paired 8002 test deployment receipt

Scope: owner-authorized replacement of legacy Mammography listener for client/server
connection testing; not complete clinical-model qualification or a release build.

- Authorized: explicit user request to replace the service on8002 and pair both sides.
- Backup/rollback: six source files and both pre-cutover configurations retained;
  exact rollback instructions are in the development FULL_WORKSTATION runbook.
- Tested: 36 focused code checks, synthetic TLS job/artifact round trip, actual paired
  server-desktop and control-client authentication, rejection of absent certificate,
  incorrect token and untrusted server. Mirrors:471 match.
- Privacy: private keys/tokens outside source, bounded identity-only receipts, no
  patient traffic or credentials printed. Client private key never left its host.
- Clinical boundaries: viewer and DICOM decoding untouched; PACS/Reception owners
  unchanged. Legacy Mammography intentionally stopped for requested test cutover.
- First cutover rolled back configuration after TLS failure; AKI/SKI correction
  passed before retry. Final listener8002 authenticated successfully;8043 closed.
- Outstanding: human fresh source GUI, PACS service account, real study/result
  acceptance, deferred Breast classification and independent external-network test.

Test transport gate: PASSED. Complete clinical production qualification: NOT CLAIMED.
