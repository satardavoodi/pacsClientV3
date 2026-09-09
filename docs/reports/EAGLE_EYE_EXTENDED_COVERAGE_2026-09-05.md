# Eagle Eye extended acquisition coverage

The developer-run connection succeeded through GapGPT, but the anatomy gate rejected
a seven-group response whose first group was labelled T11-T12. Local validation required
every group to have a unique identity while allowing only six lumbar diagnostic levels.
This made legitimate extended coverage impossible to represent. The label itself has
not been independently clinically adjudicated.

## Correction

Pipeline 8.4.0, atomic contract 2.5.0 and anatomy-card schema 1.9.0 separate anatomical
coverage from lumbar diagnostic scope. All groups retain their exact model-assigned
labels, immutable frame ranges, representative roles and membership audit. Recognized
thoracic disc levels and S1-S2 are preserved as context-only groups outside the lumbar
diagnostic range. Their full source-tile metadata and original atlas images are retained.

The five lumbar screening cards contain only the mapped lumbar groups. Extra groups
are explicitly listed as not assessed, cannot enter lumbar pathology findings, and are
not counted as missing lumbar assignments in the final numbering audit. The coverage
notice remains visible through the existing review-required report mechanism. No
out-of-scope finding is silently called normal and no lumbar level is shifted.

Duplicate or unknown labels, uncertain numbering, incorrect frame bounds, missing
source members and conflicting role assignments still stop the gate. A context-only
study with no mapped lumbar group is refused. This change does not introduce thoracic
diagnostic support or establish that a model's numbering is correct.

## Verification

The initial synthetic seven-group regression run failed 3 tests and passed 5, exit 1.
Twelve focused guards now cover seven-group normalization, preserved context membership,
screening handoff, unknown/duplicate labels, missing members, prompt scope, old-response
compatibility, absence of lumbar coverage, exclusion of context pathology and the final
numbering/coverage review. The focused anatomy/atomic/registry/analysis selection passed
159 tests with exit 0 before the broader imaging gate.

The exact saved Gemini response from the failed developer run was replayed locally,
without a new model request or alteration of the source response. It passed Gate 1 and
generated all five screening cards. The six lumbar assignments retained their original
group identities and frame ranges; the seventh group was retained as context. Replay
artifacts remain in the ignored private benchmark directory, outside committed fixtures.

The broader imaging tests exposed seven old injected-transport cases that relied on
implicit direct-model defaults removed in the preceding provider fix. They now declare
synthetic model choices explicitly; transport remains injected. No production model
fallback was restored to accommodate those tests.

Final AI Imaging gate: **1,012 passed, 8 existing expected failures, 6 existing
SWIG warnings**, exit 0 (33.52 seconds). The frozen application and live clinical
lanes were not run.

Plugin mirror verification passed: all 462 pairs match, with no plugin-only files.
The synchronization check required no changes for this fix.

## Operational state

The source application must be restarted by the operator to load the changed modules;
Re-analyze can reuse saved captures. No installed application, original capture session,
provider setting, clinical database or service was modified. No build, deployment or
new LLM inference was run. Full live screening/diagnosis after restart remains pending.

Rollback is a scoped source/build reversal preserving unrelated changes. There is no
bypass for uncertain anatomy and no automatic anatomical relabeling. Canonical item:
OPT-55. Guard: `tests/code/ai_imaging/test_eagle_eye_extended_coverage.py`.
