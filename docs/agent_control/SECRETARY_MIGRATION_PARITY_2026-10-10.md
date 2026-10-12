# Secretary migration parity review

The Windows implementation is the reference for migration behavior. Company
execution moves to authenticated Eagle Eye; client validation, confirmation and
execution stay local. This slice does not change prompt text or select a new model.

## Reproduced and corrected boundaries

Native `parser_llm._extract_json_block` accepts fenced or balanced JSON with a
prose prefix, respecting escaped quotes and braces inside strings. Hosted
`Secretary._completion` previously decoded the entire output after only removing
leading fences. Two synthetic native-valid outputs failed before the correction.
The hosted headless extractor now preserves that native behavior. JSON decoding,
object-only results, exact mode keys, typed proposal validation and tutorial target
validation remain mandatory. Malformed/truncated JSON and arrays fail closed;
there is no additional model call, arbitrary code execution or prose-to-answer
conversion. The actual failed Guide response was not retained, so its exact
syntax is unknown; this establishes a migration defect, not reproduction of that
unseen response.

Six additional guards failed on model/budget drift. Hosted company defaults now
match native `config.py`: `gpt-5.2`, no reasoning override. Explicit administrator
configuration still wins; personal credentials and model preferences are unchanged.
Host-private configuration migration and activation belong to the coordinator.

| Stage | Native reference | Hosted corrected behavior |
| --- | --- | --- |
| Routing | 256 tokens, 20 seconds | Same; 1024 tokens when conversation metadata is requested |
| Action planning | 512 tokens, 30 seconds | Same |
| Repair | 25 seconds | 512 tokens, 25 seconds |
| Ask / Guide / Help Ticket | No separate pre-migration local mode implementation | Existing 2000-token answer budget retained; 30 seconds |
| Session sources | No pre-migration local extraction equivalent | Existing 6000-token content budget retained; 30 seconds |

The larger conversation budget accommodates the additional bounded title/topic/
goal/summary JSON fields. Answer modes need explanatory text rather than a compact
action envelope. Source requests include extracted documents and image evidence.
These are existing explicit feature extensions, not a new model-selection policy.

## Prompt and catalog evidence

Prompt instructions were not rewritten. The hosted action prompt and patient-viewer
document now recover the exact native Unicode base, retaining their preexisting
hosted safety additions byte-for-byte after UTF-8 newline normalization. Two
asset guards failed before the repair and now check both recovered base and
preserved safety hashes. Byte comparisons found the catalog
identical, 14 shared module documents, and these remaining reconciliation issues:

- Hosted router v2 has additional settings/current-page and ambiguity rules absent
  from the native prompt. Preserve those reviewed safety additions during owner
  reconciliation; copying either direction blindly would change behavior.
- Hosted action prompt and patient-viewer encoding drift was repaired using the
  native originals, without changing the native prompt assets.
- Homepage document differs in trailing whitespace; session-files document differs
  only in line endings after UTF-8 text normalization.
- Hosted `phase2_prefix.txt` and request-time safety/context instructions remain
  in place. Full constructed-prompt byte parity is not claimed.

The sanitized per-file hash receipt is in the ignored developer receipt directory
`generated-files/eagle-eye/secretary-slot2-20261010/assets-parity.json`.

## Verification and limitations

`test_secretary_server.py` contains native extraction comparison, invalid-output,
default model, phase-budget and Unicode/safety guards. Together with remote-planner,
session-file and routing guards, 102 tests passed with reruns disabled; one
preexisting quarantined routing-document drift test remains xfailed. The changes do not introduce
response_format, provider retries or shared LLM adapter edits. The Secretary
snapshot manifest updates only this slice's service and two repaired asset hashes; unrelated receipt drift
must be reconciled by its owner. No matching packaged service mirror exists in
the plugin payload inventory, so no unrelated mirrors were copied.

No Razi activation, provider submission or native GUI acceptance was performed.
The coordinator owns immutable staging, private configuration reconciliation,
full parity and a separately serialized acceptance slot. Mobile contract behavior
is unchanged by the parser/default repair; mobile real-server acceptance remains
separate from Windows harness results.
