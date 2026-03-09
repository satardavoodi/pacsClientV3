# Version 2.2.2.8 Deployment Summary
**Date:** February 24, 2026  
**Release Type:** Stable  
**Primary Branch:** `DR.vahid`

## 1) Pre-release Gate: Dynamic Paths/Connections
Mandatory check completed against changed/new files in this version candidate.

### What was checked
- Hardcoded absolute local paths (Windows/macOS/Linux user-specific paths)
- New modules introduced in secretary/download-subprocess areas
- Runtime path construction strategy for portability

### Outcome
✅ Passed — changed/new runtime files use dynamic path resolution and config-driven values.

## 2) Functional Release Delta
- Integrated required upstream work into `DR.vahid`.
- Applied EchoMind server endpoint alignment to prevent stale-host connection failures:
  - `EchoMind/ai_chat_config.py` now points to `http://185.239.2.153:8002`.
- Maintained compatibility with existing dynamic app path strategy.

## 3) Git Release Information
### Recommended commit message (release snapshot)
`v2.2.2.8: stable release with dynamic-path verification and EchoMind endpoint alignment`

### Tag
`v2.2.2.8`

### Remotes
- `origin` → `https://github.com/satardavoodi/PacsClientV2`
- `vahid`  → `https://github.com/Vahid-INO/ai-pacs`

## 4) Publish Commands (reference)
```bash
git checkout DR.vahid
git pull --ff-only origin DR.vahid

git add -A
git commit -m "v2.2.2.8: stable release with dynamic-path verification and EchoMind endpoint alignment"

git tag -a v2.2.2.8 -m "AIPacs stable v2.2.2.8"

git push origin DR.vahid
git push origin v2.2.2.8

git push vahid DR.vahid
git push vahid v2.2.2.8
```

## 5) Post-publish Validation Checklist
- [ ] `git ls-remote --tags origin | findstr v2.2.2.8`
- [ ] `git ls-remote --tags vahid  | findstr v2.2.2.8`
- [ ] Launch app and open EchoMind chat
- [ ] Verify AI call path reaches `185.239.2.153:8002`
- [ ] Verify no machine-specific path assumptions after moving install directory

---
**This document is the release/deployment companion for `VERSION_2.2.2.8_RELEASE.md`.**
