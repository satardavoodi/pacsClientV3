# Secretary extended settings controls — 2026-10-03

Implemented shared actions: release_memory, get_viewer_preferences, set_viewer_preferences. Extended request_storage_cleanup with explicit local patient strategies all/delete_oldest_count/older_than_days and bounded count/day value.

RAM release uses Windows EmptyWorkingSet only on the current process, on a worker. Reports actual resident bytes before/after and whether trimming was accepted; does not delete files, close active cases, clear decoded caches or promise sustained free memory. Python garbage collection is deliberately not forced on the worker because Qt wrapper finalizers must not be run there.

Local patient cleanup reuses Storage's active-work guard, asynchronous preview, default-No local confirmation and worker/database consistency flow. Oldest count uses existing dated local activity order, not visual table position; undated patients are excluded by that strategy. All is explicitly local patient folders/database, not server PACS deletion. Duplicate assistant requests are blocked during preview/confirmation/work. Cancellation stops workflow continuation; success counters come from the cleanup worker.

Viewer preferences use existing persistence functions for backend and GPU boost on a worker, then read them back. Active viewers are not rebuilt; restart_required is reported. Personal AI configuration still uses local credential/prompt entry, save/test. Company models/prompts/credentials remain Eagle Eye-owned, with no client-direct company route.

MCP settings_control accepts typed strategy/value/backend/gpu_boost fields. The server validation snapshot, prompt catalog, operation-handle producers, client workflow capture/polling and mutation permissions are aligned. settings_operation_status is the terminal source for memory/viewer work; get_storage_cleanup_status is the terminal source for local cleanup.

Verification: 114 focused tests passed (direct pytest exit 0), including Storage consistency/filtered/async tests, synthetic deletion preview guards, off-thread viewer persistence, current-process-only RAM trimming with fake OS handles, permission checks, actual-handle capture and cancellation. No real patient data was deleted and no installed executable was launched. Fresh native client GUI acceptance remains pending because the current documented test socket is unavailable.

Server candidate: isolated 20261003-secretary-settings revision based on preserved 20261002-secretary-media, seven-file scoped overlay, existing private configuration and rollback retained. Activation evidence is recorded separately; do not treat staging as activation.

## Activated server receipt

The final isolated revision 20261003-secretary-settings-final is active on the existing Razi Eagle Eye service. Before transition, active model jobs and running EchoMind/Secretary requests were zero. Target 28 contract tests and dependency checks passed. Authenticated capability acknowledgment and existing EchoMind advertisement passed; a real synthetic planning request produced release_memory followed by settings_operation_status. No workstation action was executed by that request. Rollback metadata is in the target incoming/secretary-settings-final-20261003 directory. Client restart and native workflow acceptance remain outstanding.
