# Eagle Eye Server development workspace

Updated: 2026-09-23. Deployment root: `D:\Eagle Eye Server` on Razi Reception.

This workspace develops the server edition of AI-PACS Eagle Eye. Standard clients
control analyses and review results; server workers obtain source images from PACS
and execute AI models. Heavy weights and inference environments belong on the server.

**Current milestone: full workstation source/UI transferred; human sign-in succeeded,
but GUI acceptance FAILED with a native Advanced fault.** DICOMs reached the local
cache, but rendered output and complete study acceptance are not certified. The
independent service responds on 8043; the original 8042 pilot remains preserved.
Model deployment/import checks do not establish clinical inference qualification.

## Start here

**Latest:** [Full workstation source and UI deployment](docs/FULL_WORKSTATION.md).

[Automatic Windows service and PACS account settings](docs/SERVICE_AUTH.md).
The independent service runs on 8043; the original 8042 pilot remains unchanged.

1. [Current state and installed components](docs/CURRENT_STATE.md)
2. [Architecture and client/server responsibilities](docs/ARCHITECTURE.md)
3. [Development workflow and code map](docs/DEVELOPMENT.md)
4. [Operation, logs, diagnosis and recovery](docs/OPERATIONS.md)
5. [Test plan and acceptance evidence](docs/TESTING.md)
6. [Ordered remaining work](docs/BACKLOG.md)
7. [Decisions and change history](docs/HISTORY.md)
8. [Developer and agent agreement](AGENTS.md)

Open this directory in VS Code. The full UI source is
`revisions/20260923-workstation/source`, with its own `.venv`. The existing
8042 pilot still uses `revisions/20260923-dev/source` and `runtime/Scripts/python.exe`. Read the development workflow before changing an
executing revision. The source snapshot is a reviewed subset, not a complete Git
checkout or a complete portable model bundle.

`deployment.json` and `Run-EagleEye.ps1` describe the selected revision/runtime.
`docs/DOCS_MANIFEST.json` identifies this documentation snapshot. Update these docs
after each meaningful change; do not leave stale success claims or unresolved
failures hidden in chat history. Do not put credentials or patient data in docs.

No restart, endpoint change or model run is required to read these documents.
