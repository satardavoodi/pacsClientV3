# Release records

Start at the [release and build documentation hub](../release-and-build/README.md).
The operational procedures live in [`../../RELEASE.md`](../../RELEASE.md) and
[`../../BUILD.md`](../../BUILD.md); files in this folder record scope and evidence.

- `RELEASE_NOTES.md`: cumulative user-facing release notes.
- `VERSION_<version>_RELEASE.md`: version-specific scope, evidence, blockers,
  rollback, and acceptance state.
- `VERSION_<version>_BUILD.md`: point-in-time build evidence when present.
- `RELEASE_TEMPLATE.md`: required template for a new version record.

The canonical current version comes from `pyproject.toml`. A version number in a
record does not by itself prove that Git publication, installer build, install QA,
or production acceptance succeeded. Read the record's status and evidence.
