# AI-PACS vX.Y.Z release

Release date: YYYY-MM-DD
Release commit: resolved from the immutable annotated tag and Git synchronization receipt
Release tag: `vX.Y.Z`
Source branch: `beta-version`
Source publication status: BLOCKED
Production approval: NOT YET GIVEN

Change source publication status to `READY` only after the complete release
scope, evidence, exclusions, security findings, and rollback have been reviewed.
The release manager rejects a missing or blocked record.

## Outcome and scope

Describe the user-visible result and the exact subsystems included in this
release. Separate implemented behavior from proposed or clinically unvalidated
work.

## Compatibility, migration, and stored data

Record configuration migrations, database or DICOM behavior, external software
compatibility, upgrade behavior, and any retained backward compatibility.

## Verification evidence

| Gate | Command or evidence | Result |
|---|---|---|
| Version parity | Project, running application, Information panel, installer | PENDING |
| Focused automated tests | Direct pytest invocation and process exit code | PENDING |
| Plugin mirror parity | Mirror verification tool | PENDING |
| Secret scan | Path-only report; never copy values | PENDING |
| Developer Run | Named human acceptance | PENDING |
| Git synchronization | Receipt path and exact SHA | PENDING |
| Installer matrix | Six files, sizes, hashes, signatures | PENDING |
| Clean install / upgrade / rollback | Isolated Windows evidence | PENDING |

## Deliberate exclusions

List local or generated files, unfinished features, clinical data, and unrelated
work that is not part of the release.

## Known risks and blockers

List unresolved security, clinical, legal, packaging, platform, and operational
gates. Do not describe a local candidate as production-ready while any mandatory
gate remains open.

## Rollback

Describe the application and Git rollback. Shared branches are reverted with a
new reviewed commit; tags and published history are never moved or force-pushed.

## Approval

Source publication approved by: NOT YET GIVEN
Installer distribution approved by: NOT YET GIVEN
