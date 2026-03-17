# Plugin Package Workspace

This folder is the source-of-truth workspace for AIPacs plugin packaging.

## Purpose

- Keep every current module represented as a package definition.
- Let the release builder stage installable plugin packages without copying ad-hoc rules into multiple places.
- Prepare a stable SDK-style contract so future store packages can target the current workstation safely.

## Structure

- `definitions/<module_id>/plugin_package.json`
  - Builder metadata for one module package.
- `packages/<module_id>/`
  - Materialized package folders for the current modules.
- `sdk-template/`
  - Starter files for future external plugin authors.

## Package Characteristics

Each plugin package definition should declare:

- `module_id`
  - Stable runtime identifier. Must match `aipacs_runtime.MODULE_CATALOG`.
- `tier`
  - `basic` for core-bundled modules or `optional` for installable modules.
- `package_kind`
  - `core`, `bundled_unlock`, or `runtime_payload`.
- `build_strategy`
  - `source_tree` for Python packages copied from the repo, or `runtime_payload` for external runtimes such as Advanced MPR.
- `source_paths`
  - Source folders/files that become package payload content.
- `python_paths`
  - Relative payload roots that should be added to `sys.path` after installation.
- `healthcheck_import` or `healthcheck_path`
  - Minimal verification target used after installation.
- `integration_points`
  - Current software touch-points the package needs to satisfy.
- `install_channels`
  - How the package can arrive in the workstation: installer, Settings, or future store delivery.
- `sdk_entrypoint_group` and `sdk_entrypoint_name`
  - Reserved for future packaged SDK discovery.

## Current Packaging Model

- Builder definitions stay here.
- `python builder/materialize_plugin_packages.py` materializes the current module packages into `packages/`.
- `builder/build_release.py` turns optional definitions into staged package directories and distributable archives.
- The Windows installer can ship selected staged packages.
- On first launch, the app bootstraps installer-selected bundled packages into the existing runtime module area.

## Runtime Payload Note

Large external runtimes such as Advanced MPR are not duplicated into `packages/` by default.

- The package folder is still created.
- The manifest is still written.
- A `PAYLOAD_NOT_MATERIALIZED.txt` marker is added with the source runtime path.
- If you really want the full payload copied into the workspace, run:

```powershell
python builder/materialize_plugin_packages.py --include-runtime-payloads
```

## Compatibility Goal

Packages built from this folder must be safe for both:

- install-time selection inside workstation setup
- post-install delivery through Settings or a future in-app store
