# Operations, logs and diagnosis

The following read-only commands can run in PowerShell on Razi:

```powershell
Get-ScheduledTask -TaskName 'AI-PACS Eagle Eye Development' | Select-Object TaskName,State
Get-NetTCPConnection -State Listen -LocalPort 8042
Get-Content -LiteralPath 'D:\Eagle Eye Server\deployment.json'
Get-ChildItem -LiteralPath 'D:\Eagle Eye Server\logs' | Sort-Object LastWriteTime -Descending
& 'D:\Eagle Eye Server\runtime\Scripts\python.exe' -m pip check
```

For authenticated health, read config/pilot.token only into process memory and pass
it as the Authorization Bearer header to GET http://127.0.0.1:8042/v1/capabilities.
Do not print the token, put it into a URL/command-line argument, or send it in chat.
Also verify unauthorized requests return401 and GET /v1/jobs is owner-scoped.

Start only when stopped, using Start-EagleEye.ps1 or Start-ScheduledTask with the
documented task name. The task has no startup trigger; Windows reboot does not
currently promise automatic restoration. The listener binds loopback only. Remote
testing uses a separately owned SSH tunnel; no persistent tunnel is currently installed.
Direct LAN deployment requires TLS/certificate validation and explicit client setup.

## Shutdown and recovery: known limitation

Stop-ScheduledTask was observed to stop its wrapper but leave the Python listener
alive. It is NOT verified graceful shutdown. Before model testing, implement owned
stop/drain and prove descendant cleanup. Do not merely start another instance.

For the currently empty pilot, the tested manual recovery procedure was: retrieve
the authenticated job inventory and require it empty; stop the named task; resolve
the unique8042 listener; verify its executable and full command line refer exactly
to this workspace's serve.py and config/server.json; only then stop that exact PID.
Recheck the port is free before starting the task. If identity differs or jobs exist,
do not terminate anything. Never kill by process name, arbitrary stale PID or port
number alone. config/process.json from the FIRST failed SSH launch is historical
and must not be used as current process identity.

## Logs and rollback

server-*.out.log / .err.log contain process output. Job directories contain private
source staging, states and worker logs; restrict access and do not copy them into
documentation. Correlate by opaque job/revision IDs and redact patient content.
Slicer diagnostics: slicer-probe.*, native-version.* and the VC143 candidate receipt.
No retention policy is installed yet; monitor disk growth before longer tests.

Rollback means restoring the LAST QUALIFIED revision/environment/runner together.
The preserved pre-VC143 runner and original20260923 Slicer fail startup on Razi;
they are historical evidence, not a recommended functional rollback. Keep the
working VC143 candidate when reverting unrelated Python changes.

| Symptom | First action |
|---|---|
| Connection refused | Check task, own listener and latest error log; avoid duplicates |
|401|Check credential file selection privately; do not disable authentication|
|429|Check global/client admission and queue; do not blindly raise limits|
|Source outside configured roots|PACS mapping is unfinished; validate exact roots, not all of D:|
|Missing model or changed manifest|Provision/verify the intended asset revision; no client fallback|
|Slicer exit0xC0000142 / Win321114|Check resolved runtime and app-local CRT receipt; preserve System32|
|Slicer EGL warning|Headless probe warning alone is not a failure; require exit/result receipt|
|Interrupted after restart|Current recovery behavior; do not claim checkpoint resume|
