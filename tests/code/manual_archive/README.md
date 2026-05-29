# Manual Test Archive

This folder contains ad-hoc/manual scripts that are not part of automated CI-oriented test suites.

## Why this exists

- Prevent repository root pollution from one-off verification scripts.
- Keep automated test discovery focused on `tests/<suite>/test_*.py`.

## Current contents

- `root_ad_hoc/`: former root-level manual test scripts used during stack-order fixes.

## Usage rule

- Do not treat these scripts as canonical regression tests.
- When a manual check becomes stable and reusable, migrate it into a proper pytest under `tests/viewer/` or the relevant suite.
