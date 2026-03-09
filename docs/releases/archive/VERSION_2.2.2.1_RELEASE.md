# AIPacs Release Notes

## Version
- **Tag:** `v2.2.2.1`
- **Branch:** `DR.vahid`
- **Release scope:** EchoMind + Advanced Analyses UI + Settings integration

## Summary
This release packages the latest integration work for:
- EchoMind module updates
- Advanced Analyses UI improvements/fixes
- New **Settings → EchoMind** section/tab and related settings flow

## Included changes

### 1) EchoMind module updates
- Updated core EchoMind UI flows and widgets
- Added/updated settings persistence helpers for EchoMind
- Added secretary-related integration components for EchoMind workflows

### 2) Advanced Analyses UI updates
- Refactor and fixes applied to Advanced Analyses flow
- UI-level updates for smoother integration with current patient/workstation context
- Added project docs for refactor, testing guide, and UI diagram:
  - `ADVANCED_ANALYSIS_REFACTOR.md`
  - `ADVANCED_ANALYSIS_TESTING_GUIDE.md`
  - `ADVANCED_ANALYSIS_UI_DIAGRAM.md`

### 3) Settings → EchoMind
- Added EchoMind settings module/tab under workstation settings
- Wired settings entry points into existing settings UI structure
- Added supporting settings storage and bridge components

## Compatibility notes
- Local machine-specific hardcoded paths remain replaced with dynamic path handling from prior release line.
- DICOM and cache/generated artifacts are excluded by repository ignore rules and are not part of this source release.

## Validation notes
- Merged code paths were validated for import/runtime stability on the local environment before release packaging.
- This release is intended as the consolidated branch snapshot for both configured GitHub remotes.

## Repositories
- `https://github.com/satardavoodi/PacsClientV2`
- `https://github.com/Vahid-INO/ai-pacs`
