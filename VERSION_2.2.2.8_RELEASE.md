# AIPacs Version 2.2.2.8 Release
**Date:** February 24, 2026  
**Tag:** `v2.2.2.8`  
**Branch:** `DR.vahid`  
**Status:** Stable Release

## Summary
Version **2.2.2.8** is published from the current `DR.vahid` codebase with:
- required upstream merge work included,
- EchoMind AI server IP alignment completed,
- dynamic-path compliance verified for newly added/changed parts.

## Included Git History (key points)
- Merge with `origin/DR.vahid` completed.
- Required release commits are included:
  - `37e338899358b154643796a87d6816fbef42e005`
  - `c8b2ae6162ec481a813a1aae6ea1536a1fed135a`
- EchoMind IP fix commit included:
  - `d710f7b` — `EchoMind: update AI server IP to 185.239.2.153`

## EchoMind AI Connection Update
### Root cause
EchoMind had inconsistent AI base URL values across modules.

### Applied fix
- Updated `EchoMind/ai_chat_config.py`
  - from: `http://87.236.166.66:8002`
  - to: `http://185.239.2.153:8002`
- Verified alignment with:
  - `PacsClient/pacs/patient_tab/viewers/ai_chat_config.py`

## Dynamic Path / Connection Verification (Mandatory)
Scope was focused on **newly added and recently changed** files in this release candidate.

### Verification result
✅ No hardcoded local absolute machine paths were found (no `C:\...`, `C:/...`, `/Users/...`, `/home/...` literals) in changed/new runtime files.

### New/recent modules checked
- `EchoMind/secretary/config.py`
- `PacsClient/zeta_download_manager/workers/download_subprocess.py`
- `PacsClient/zeta_download_manager/workers/subprocess_worker.py`
- `main.py`
- plus all other modified/new files in current working set

### Dynamic strategy confirmed
- Uses runtime-relative path resolution (e.g., `Path(__file__).resolve().parent/...`).
- Uses application config/constants instead of hardcoded install-drive paths.
- Uses PyInstaller-aware runtime handling (`sys._MEIPASS`, `freeze_support`) where needed.

## Notes
- The STT error `SpeechRecognition is not installed.` is a dependency/runtime issue, independent of the server-IP mismatch.
- No benchmark metrics are claimed in this release document because no controlled benchmark suite was executed in this specific session.

## Tag/Publish Intent
This release is intended to be published as:
- Branch: `DR.vahid`
- Tag: `v2.2.2.8`
- Remotes:
  - `https://github.com/satardavoodi/PacsClientV2`
  - `https://github.com/Vahid-INO/ai-pacs`

---
**Prepared for stable publication on Feb 24, 2026**
