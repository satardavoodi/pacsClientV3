# Release records

Start at the [release and build documentation hub](../release-and-build/README.md).
The operational procedures live in [`../../RELEASE.md`](../../RELEASE.md) and
[`../../BUILD.md`](../../BUILD.md); files in this folder record scope and evidence.

The current four-installer Standard Client request is recorded in
[the v3.7.1 release record](VERSION_3.7.1_RELEASE.md). The earlier
[v3.7.0 record](VERSION_3.7.0_RELEASE.md) is historical source publication;
its interrupted Nuitka run does not establish a complete matrix. Eagle Eye Server is not
part of this build. Earlier expanded Client/Server prerequisite work is recorded in
[the September 28 safety record](deploy-record-client-server-2026-09-28.md).
It is not a new installer, source-publication receipt or production approval.
The [v3.6.9 preparation record](VERSION_3.6.9_RELEASE.md) tracks the exact
six-installer request and its remaining release gates.

- `RELEASE_NOTES.md`: cumulative user-facing release notes.
- `VERSION_<version>_RELEASE.md`: version-specific scope, evidence, blockers,
  rollback, and acceptance state.
- `VERSION_<version>_BUILD.md`: point-in-time build evidence when present.
- `RELEASE_TEMPLATE.md`: required template for a new version record.

The canonical current version comes from `pyproject.toml`. A version number in a
record does not by itself prove that Git publication, installer build, install QA,
or production acceptance succeeded. Read the record's status and evidence.
