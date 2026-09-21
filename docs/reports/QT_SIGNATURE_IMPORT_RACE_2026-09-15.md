# Qt signature import race and separate exit faults — 2026-09-15

## Scope and evidence

This is a bounded OPT-60 stability follow-up, with OPT-29 ownership history retained.
It does not close the native-crash or full performance acceptance gates.

The September 15 main-process log records an unhandled `KeyError` at 12:08:10,
PID 1148168, in `shibokensupport/signature/mapping.py`, `Reloader.update`, referring
to a transient optional keyring backend module. Windows records the same PID at
12:08:11 with `c0000409` in `ucrtbase.dll`. The exception is reproduced separately
from any real credentials using the installed Python function's code object and a
synthetic module registry that removes an entry after `copy()`.

Installed PySide6 is 6.10.2. Its bytecode copies the keys but subscripts the live
`sys.modules` during candidate validation. A failed concurrent import can remove
the provisional key between these operations. The
[upstream Qt implementation](https://raw.githubusercontent.com/pyside/pyside-setup/6.10.2/sources/shiboken6/shibokenmodule/files.dir/shibokensupport/signature/mapping.py)
contains the same lookup pattern. This is not evidence that the clinical image
decoder, server, or credential values caused the failure.

Two **different** Windows faults at 10:57:23 (PID 1116020) and 11:04:36 (PID 1142872)
are `c0000005`, `shiboken6.abi3.dll`, offset `0x26f20`. Both follow
`mainwindow_close_programmatic` and the normal shutdown lock-release records.
Their current-thread dumps end at `main.py:1539`, corresponding to the pre-edit
hard-exit call in the current source. They are exit-time faults, not demonstrated
image-open faults. The exact native destructor/ownership cause remains unresolved.
Do not claim the signature adapter fixes these or substitute an earlier
patient-table releaseWrapper diagnosis merely because the DLL offset matches.
Google/poller frames in the dumps describe other threads, not the faulting frame.

A further 12:11:35 Qt6Core `c0000409` belongs to PID 1124728, not matched to these
app-log sessions. Do not silently attribute it to the main workstation session.
Four attachment-not-found incidents are separate; their relation to any crash is
unproven. No attachment policy or credential storage behavior changes here.

## Bounded correction

`PacsClient/utils/pyside_signature_guard.py` installs before AppHandler import in
`main.py`. It is limited to the reviewed PySide6 version and existing binding shape.
It validates name/value pairs from one registry snapshot, skips candidates removed
or replaced before import, and preserves the existing reloader owner/count fast
path, initializer application and PySide-module registration. Both mapping and
parser's cached bound entry points change together. Repeated installation is a
no-op; unreviewed versions/bindings are left unchanged with a warning.

This is an application-owned compatibility adapter, not an edit to site-packages,
a dependency upgrade, a new thumbnail path, or an exception-suppression hook.
Initializer errors and Qt argument TypeErrors still propagate normally. Existing
module-validity filesystem checks remain unchanged; this is not their performance
fix. There are no new locks, workers, retries, credential reads, configuration
families or changes to Fast/Advanced/VTK ownership.

The new core helper has a static import from main and uses the existing embedded
PySide6 support namespace. It is not a new optional/licensed product module: no
MODULE_CATALOG entry, installer component or plugin payload is appropriate. No
runtime source in this slice has a plugin mirror. Source and frozen use the same
bootstrap call; simulated frozen Qt smoke is not an actual installer acceptance.
Review/remove this adapter when updating PySide6; do not broaden its version gate
without testing the new library implementation.

## Thumbnail observability, not a scheduling fix

The 12:25 source session (PID 1153108) records a six-thumbnail scan of 2.23 ms but
`prepare_wait_ms=1035.99` at 12:36:40. Existing fields cannot attribute the remainder.
`_pw_pipeline.py` now records `queue_ms` (submission to worker entry), `scan_ms`
(worker entry to completion), and `delivery_ms` (worker completion to GUI resume).
The total uses that resume timestamp, before owner-validation/application. Grouped
skip records zero queue/scan/delivery. The same executor, immutable tuple, owner
guards and rendering/routing decisions remain unchanged. No server-latency or
executor-saturation conclusion is justified before fresh split measurements.

## Verification and acceptance

- Fail-before: actual installed mapping code raised two synthetic KeyErrors;
  one unchanged-count test passed. Direct pytest exit 1.
- After correction: 12 signature guards, including real isolated Qt signature,
  argument-error and queued-event smoke with source/simulated frozen markers.
- Timing guard failed before missing `queue_ms`; after change checks exact
  100 ms queue / 2 ms scan / 298 ms delivery / 400 ms total with a synthetic clock.
- Focused adjacent suite: **72 passed, six existing SWIG warnings, exit 0**,
  7.82 s, direct pytest `-p no:debugging --reruns 0`. Includes preparation,
  table ownership, deleted-object, overlay, import/layout and startup guards.
- Separate shutdown/startup cleanup selection: **10 passed, exit 0**, 0.87 s.
  Scoped diff and new-file whitespace/conflict checks passed.
- Expanded run including builder parity: **85 passed, one failed**, exit 1.
  The failure is existing staged configuration parity: `echomind_settings.json`
  and `printing_config.json` differ from sanitized expectations. The check reads
  stage/config assets, not these edited runtime files. No staged output or those
  configuration files was changed or rebuilt by this task. No release pass claimed.
- Read-only mirror verification: **463 pairs match**, zero plugin-only files.
- Fresh source GUI **pending**. Existing MCP tool inventory has no connector and
  documented client ping cannot reach the test server. The source process started
  12:25:45, before these changes; do not hot reload it or count it as acceptance.

## Next gate and rollback

Human closes the old source app, launches once with `AIPACS_TEST_SERVER=1`, and
signs in outside clinical reading. Verify `[QT_SIGNATURE_GUARD]` activation,
normal Home/patient open, exact series/pixels/counts, Local and grouped cases,
normal close/reopen, new preparation split timings, and normal application exit.
Use the documented MCP plus actual affected GUI input. Neither a code pass nor
the running pre-edit process closes this gate.

Native exit faults need native shutdown evidence before changing teardown order,
GC policy, process termination, or bypassing DLL finalization. Preserve current
download/decode cleanup and explicit exit controls. Remaining startup/row-render
stalls and attachment errors stay separate work items.

Rollback only the main bootstrap import/call and this helper; separately remove
the added preparation timing fields and corresponding worker timestamp return.
Keep the preceding asynchronous preparation, identity and ownership fixes intact.
