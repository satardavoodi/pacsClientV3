# Secretary cleanup completion receipt (2026-10-07)

The reviewed local conversation ended at awaiting_local_confirmation with deleted_files null. This did not establish whether the subsequent local Storage interaction actually deleted files. No previous cleanup is replayed by this correction.

Single cleanup results in the Secretary async renderer now follow only get_storage_cleanup_status, bound to the client-created operation identifier. Awaiting local confirmation, preview, deletion and storage refresh are separate progress states. Completed receipts report actual worker deletion/database counts; failures, cancellations, changed receipt identity and a ten-minute pending bound do not claim completion or repeat deletion. A final safe completion receipt is written on a worker to the existing session log.

The Storage panel retains ownership until the forced folder/drive refresh finishes. If an older scan is in flight, its completion cannot terminate the operation while the fresh scan is queued. A scan failure preserves the actual deleted count with an explicit warning and storage_refreshed false. Zero-file/no-refresh outcomes never claim refreshed usage.

Two new receipt guards failed before implementation. Final focused verification: 33 passed, no failures, direct pytest exit 0; six existing SWIG warnings. Tests cover cached status polling, no deletion replay, changed/pending identity, queued fresh scans, refresh failure, actual worker-result counts and existing async panel/worker paths. Owned helper mirror equality passed. Source native Test Control ping remains unavailable; native acceptance is pending. The earlier deletion itself remains unverified, and no clinical files were deleted during this work.
