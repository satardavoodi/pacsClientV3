# Secretary English display policy (2026-10-07)

The supplied screenshot showed non-English clarification questions/options. The client previously forwarded auto/fa as output language and server completion had no global policy overriding that preference.

The client now sends English output preference while preserving the original user input. The server-owned common completion prompt requires English answers, reasons, confirmation prose and clarification questions/options for every mode and phase. Executable identifiers must remain unchanged. This is a source correction, not proof of target server deployment or native acceptance.

A meaningful server guard failed before the fix. Final focused verification: 32 passed, zero failures, direct pytest exit 0; six existing SWIG warnings. Client-wire guards cover auto/fa/en and unchanged input, without actual provider calls. The owned remote-planner mirror was synchronized. Native source Test Control was unavailable in the latest probe; no app restart or server deployment occurred in this slice.
