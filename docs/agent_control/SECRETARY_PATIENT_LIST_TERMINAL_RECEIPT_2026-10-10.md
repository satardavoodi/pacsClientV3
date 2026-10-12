# Secretary patient-list terminal receipts

The canonical patient search executes advanced_search_patients and verifies read_patients. Only an actual successful ready probe with a nonnegative integer count establishes completion. Workflow StepResult.receipt and its orchestrator projection retain only state, count and source (local, server or unknown). Patient rows, handles and raw provider prose are excluded.

Patient-list desktop summaries and native mobile response.message, text and captured history use aggregate summaries. Pending, absent-count and unverified searches cannot claim completion. Zero ready results explicitly report no matches. A later unverified search cannot reuse an earlier ready receipt. Metadata availability never proves image download completion.

The GUI-owned native runtime retains at most 256 private aggregate receipts keyed by the original mobile request UUID. Confirmation UUIDs remain aliases in the existing command-result protocol; the private receipt stays under the original UUID. These receipts are not added to mobile DTOs or public endpoints. An unverified successful pipeline has completion_unknown status.

## Explicit source QA inspection

The existing source-only AIPACS_TEST_SERVER=1 Test Control Server advertises secretary_terminal_receipt. Its thin MCP wrapper sends exact request_id, session_id and runtime_instance entities. Lookup requires the current owner, GUI thread, current session and runtime, a canonical original UUID and a retained ready receipt. Missing callbacks, foreign/expired requests and identity mismatch return NOT_FOUND without raw exceptions. The Home callback reads its existing Secretary widget only; it does not create a runtime or search other windows. Production defaults and frozen-build refusal remain unchanged. Human source launch/login is required before this inspection can be used.

Date provenance is captured separately from actual resolved advanced_search_patients date_from/date_to entities. Both bounds must be calendar-valid YYYYMMDD values in ascending order. Only a successful ready read_patients verifier with an executor-only list_id binds those dates. A subsequent read retains provenance only for the exact same verified list boundary; new searches and new workflows clear prior proof. Missing bounds, missing list identity, unverified probes and unrelated lists do not prove dates. No planner or clock behavior changes.

Safe internal workflow projections carry these separate bounds to the native runtime, which retains them privately under the same bounded original UUID/session correlation. The QA lookup adds date_from/date_to only when verified provenance exists. Public mobile response, text and history remain aggregate-only. Missing dates explicitly mean date verification is unavailable; no current-clock fallback is used. A verified count for the wrong executed date remains the wrong date and cannot establish today's-list acceptance.

## Verification and deployment status

Synthetic guards cover actual probe projection, unverified and zero counts, later-search invalidation, native text/history privacy, bounded original UUID retention, confirmation alias correlation, strict QA lookup, missing callback and source gates. Existing Files/session_sources work is preserved. Source test results and frozen hashes are recorded in generated-files/eagle-eye/secretary-patient-aggregate-20261010/frozen-receipt.json.

No provider call, GUI test, service transition or activation was performed by this slice. Fresh native workflow acceptance, both mobile implementations and complete local/Razi source parity must be recorded separately before completion.
