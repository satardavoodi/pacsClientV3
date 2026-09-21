# OPT-22: user-initiated WebEngine opening status

## Scope and evidence

The September 15 source session started at 15:43:24. Its first browser opening
produced a 35,375.9 ms GUI-stall record. Samples span lazy WebEngine import,
browser construction, profile/network-capture setup, theme application and tab
insertion. Windows Application WER recorded `AppHangTransient` at 15:50:44.961;
this is temporal corroboration, not a PID match supplied by that event. The
application subsequently answered the documented Test Control Server ping.
This observation is not a fatal crash or proof of a slow remote server.

The user's requested correction is visible waiting feedback and protection from
repeated input. It does **not** remove the atomic Qt/native initialization cost.
The indicator can stop animating and Windows can still report an unresponsive
application during that interval. AV, disk and native-engine contributions have
not been isolated for this opening; no AV/proxy/Chromium settings were changed.

Read the preceding decisions:

- [72-second prewarm incident](FREEZE_72S_BROWSER_PREWARM_2026-08-16.md)
- [Warmup evaluation](WEBENGINE_WARMUP_EVALUATION_2026-08-16.md)

Warmup remains OFF unless explicitly opted in. Moving Qt widget construction to
a worker or restoring idle prewarm would violate the established boundary.

## Implementation and preserved contracts

`modules/web_browser/launch.py` owns a lightweight child status strip in the
existing application header. Home's `open_web_browser` retains its availability
check, delegates here and still returns the new/existing browser widget or None
synchronously. OAuth and Secretary CommandBus callers depend on this contract;
an asynchronous launcher returning a pending None is not equivalent.

Before the lazy engine import, the strip paints `Opening Web Browser - Please
wait`, an explanation and an indeterminate bar. There is no fabricated percent,
ETA or cancellation of an in-progress native constructor. A synthetic Qt probe
found zero pre-expose paints for a newly shown top-level dialog versus a paint
for a child of an already exposed shell. Accordingly this implementation uses
the latter and `repaint()`, never `processEvents()` or a nested dialog loop.
Actual compositor visibility still requires the source GUI gate below.

An application-local event filter temporarily consumes mouse/key/wheel/shortcut,
touch/tablet and drag/drop inputs and protects the parent window from Close while
construction is in progress. Paint, timers and asynchronous work are not broadly
disabled. A 150 ms **nonblocking** timer retains the input gate after return to
discard queued input; this is not a startup deadline or a guarantee about every
possible Windows input backlog. Previously disabled controls stay disabled.
The guard neither controls other Windows applications nor serializes arbitrary
programmatic commands. Recursive browser opening is coalesced while the notice
is active. An existing browser tab activates without a notice or reconstruction.

The parent owns the notice and its timer. Completion/error releases the filter
through the normal event loop and schedules notice deletion; native parent
deletion also retires the filter. Errors retain the existing None-return contract
and are logged. PHI-free `[WEB_BROWSER_LAUNCH]` markers distinguish opening,
ready with import/construct/total durations, and failure.

Unchanged: generic module-tab routing; browser profile/navigation; warmup flags;
OAuth policy; licensing; Fast/Advanced/VTK execution; DICOM grouping, decoding,
thumbnails, downloads, DB and clinical data. The new helper belongs to the existing
optional `web_browser` source tree and payload, not a new runtime module or flag.

## Verification receipt

- Before correction: initial guard selection **4 failed / 3 passed**, exit 1.
  It exposed missing pre-import status paint, recursive duplicate construction
  and absent input protection. The paint assertion also failed in the guard
  prohibiting unrelated nested event processing.
- Final new file: **12 real-Qt synthetic guards** covering paint order,
  reentrancy, restoration/retry, existing/disabled modules, queued input,
  indeterminate progress, Close protection, synchronous return, deleted owner,
  preserved disabled controls and no nested dispatch.
- Focused selection below: **160 passed, 7 warnings, exit 0**. Warnings are six
  SWIG notices and one existing QMouseEvent deprecation; no lint claim.
- Specific builder mirror guard: **1 passed, exit 0**. Mirror sync added only
  `web_browser/launch.py`; verification reports **465 matching pairs**, zero
  plugin-only files. This is not a release build or full installer acceptance.
- Final combined rerun: **161 passed, 7 warnings, exit 0** in 5.91 seconds;
  scoped tracked diff whitespace check passed. Pre-existing Home signal-relay
  and thumbnail changes were preserved.
- Synthetic strip screenshot checked for readable English text and unclipped
  layout using the installed Segoe UI font. The first offscreen platform preview
  lacked a usable default font; explicitly loading the installed font corrected
  that test-only preview. No application font/configuration was changed.

```powershell
$env:QT_QPA_PLATFORM = 'offscreen'
$env:PYTHONPATH = '.'
.\.venv\Scripts\python.exe -m pytest -p no:debugging --reruns 0 tests/code/web_browser tests/code/system/test_browser_prewarm_idle_gate.py tests/code/identity/test_oauth_surface_policy.py tests/code/identity/test_connect_button_routing.py tests/code/echomind/test_browser_education_adapters.py tests/code/system/test_overlay_reentrancy_crash.py tests/code/test_loading_overlay_liveness_guard.py tests/code/builder/test_plugin_package_registry.py -q
.\.venv\Scripts\python.exe -m pytest -p no:debugging --reruns 0 tests/code/builder/test_release_parity_guards.py::test_plugin_mirrors_are_fresh -q
```

## Remaining live gate

**Not live-verified.** The currently running source process predates this helper.
The existing MCP client ping/action discovery work, but they cannot validate new
code in the old process. No hot reload, duplicate instance, installed executable
or automated login is allowed. Follow section 0 of the agent control guide:

1. Human closes/restarts one source instance with `AIPACS_TEST_SERVER=1`, accepts
   the observed disk-space notice with OK and signs in outside clinical reading.
2. Discover ping/actions via existing `aipacs-control` or its documented client.
3. Use actual GUI input to open Web Browser on its first use. Verify the strip is
   visible before the engine wait, repeated clicks/keys do not launch other
   actions or duplicate browsers, and controls recover after construction.
4. Verify existing-tab activation, close/reopen, normal browser navigation and
   unaffected Home/patient behavior. Do not automate authentication for OAuth.
5. Correlate new phase timings with session-scoped stalls and Windows events.
   A ready marker means widget construction/tab activation returned, **not** that
   a remote page finished loading. Do not claim a cold-time improvement or native
   crash closure from this UX change. Check failure recovery in code guards;
   do not sabotage the live browser to force it.

## Rollback and engineering references

Revert only this launch delegation and remove its new helper/payload if rollback
is needed. Preserve the unrelated signal-relay and thumbnail edits already in
`_hp_modules.py`. Keep guards/docs to record the decision; do not reset that file
wholesale. The original synchronous opening contract can be restored without
changing engine settings, patient data or package topology.

Qt documents [repaint](https://doc.qt.io/qt-6/qwidget.html#repaint) and
[application/object event filters](https://doc.qt.io/qt-6/qobject.html#installEventFilter).
Behavioral tests here verify the selected seam; they do not replace the native
Qt/WebEngine/Windows acceptance run.
