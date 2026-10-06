# Secretary Ask download diagnostics

The failed Ask request reached authenticated Eagle Eye but retained no answer. The client masked its failure with MODE_RESPONSE_REQUIRED. The original server failure detail was not retained, so its exact cause cannot be reconstructed. Question context omitted download state and log evidence.

The client now captures shared read-only download counts on the GUI thread and projects bounded log tails on the planning worker. Only aggregate counts, sampling scope and timestamps leave the client. Raw log text is excluded. One snapshot and bounded tails cannot establish throughput or exclude earlier errors or stalled transfers.

Fixed safe server error codes survive to the visible reply. Ask and Guide retry one quick recognized planning failure on the same authenticated server. Act, Help Ticket, authentication and slow failures are not retried by this change. No new provider route or server deployment was introduced.

## Verification

Three initial guards failed before implementation. The offscreen widget guard verifies GUI state capture, worker evidence collection and preplanning, and return to rendering. An authenticated corrective Ask returned an assessment from safe real aggregates: the sampled download tail contained zero errors and 130 warnings. Live download progress was explicitly unavailable; this is not full download-health acceptance.

Native source GUI acceptance remains pending because the documented Test Control endpoint is unavailable in the running session. Offscreen verification is not a native GUI pass. Changed planner and orchestrator payload mirrors match; unrelated pre-existing mirror drift remains outside this change.
