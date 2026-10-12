# Explicit Eagle SCM shutdown boundary

Owner policy 2026-10-12 permits interrupting unfinished Eagle work during the login-triggered owned-service restart. This is an explicit emergency SCM path, not certified idle. It never replays a request and does not authorize arbitrary process termination or PACS/Reception changes.

The prior supervisor could retain its owned Job indefinitely while waiting for an unknown private drain receipt. Its synchronous stop notification could also block before the stop budget began. Explicit SCM stop now bypasses that private-receipt wait; a stop arriving during an existing wait is observed within its one-second polling interval. Cooperative transitions still retain uncertain resources and require their existing certificates.

Stop notification uses a daemon writer bound to the captured old child generation. The supervisor's timed wait and owned Job close continue independently of a blocked notification. Buffered streams still held by a sender or reader are left to host process exit rather than reacquiring a potentially blocked stream lock. Existing Job ownership, kill-on-close and exact child cleanup remain unchanged.

This does not guarantee recovery of a completely hung supervisor, blocked Python execution, operating-system failure or blocked SCM reporting. The privileged fixed-service coordinator must refuse/no-retry when its stop deadline is exceeded and must not start a second generation. No broad user process privileges or arbitrary PID kill fallback are introduced.

Three guards failed before the change. Five new synthetic guards plus existing service host/private control tests passed: 36 tests, exit 0. No installed-service operation occurred. Live GUI login-triggered recovery, immutable Razi synchronization and installed qualification remain pending. Frozen evidence is under `generated-files/eagle-eye/emergency-scm-stop-20261012`.
