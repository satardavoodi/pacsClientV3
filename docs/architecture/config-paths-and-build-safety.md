# Config Paths & Build Safety Reference

**Last updated:** v2.4.2-patch3 (2026-04-23)

This document is the canonical reference for how each settings/config file is located
in both developer mode (VS Code / `python main.py`) and the installed build
(`C:\Program Files\AIPacs\`).  It also contains the checklist to run before every
build to ensure these structures never break again.

---

## Path Roots

| Symbol | Dev value | Installed (frozen) value |
|--------|-----------|--------------------------|
| `PROJECT_ROOT` (`_project_root.py`) | `repo/` | `engine/` (= `sys._MEIPASS`) |
| `BASE_PATH` (`config.py`) | `repo/` | `engine/` |
| `SOCKET_CONFIG_PATH` (`config.py`) | `repo/config/` | `%APPDATA%\AIPacs\config\` |
| `roaming_config_root()` | `repo/config/` (non-frozen) | `%APPDATA%\AIPacs\config\` |
| `bundled_config_root()` | `repo/config/` | `engine/config/` |
| `user_data_root()` | `repo/user_data/` | `%LOCALAPPDATA%\AIPacs\user_data\` |
| `program_data_config_root()` | `repo/config/` | `C:\ProgramData\AIPacs\config\` |

> **Key:** `os.chdir(sys._MEIPASS)` in `main.py` means CWD == `engine/` in the installed
> app, so relative paths like `Path("Qss/...")` accidentally work — but **do not rely on
> this for config files that users write to**.  Only `SOCKET_CONFIG_PATH` or
> `roaming_config_root()` must be used for writable user config.

---

## Config File Registry

| Config file | Read/Write | Owner module | Path strategy | Notes |
|-------------|-----------|--------------|---------------|-------|
| `servers.json` | R/W | `utils.py` | `SOCKET_CONFIG_PATH / "servers.json"` | PACS server list; dev falls back to root `servers.json` if config/ is empty |
| `servers_address.json` | R/W | `servers_config.py` | `SOCKET_CONFIG_PATH / "servers_address.json"` | AI service URLs (breast/boneage/seg) |
| `socket_config.json` | R/W | `socket_config.py` | `SOCKET_CONFIG_PATH / "socket_config.json"` | Socket host/port for DM |
| `external_pacs_servers.json` | R/W | `external_pacs_settings.py` | `SOCKET_CONFIG_PATH / "external_pacs_servers.json"` | Third-party PACS; **fixed v2.4.2-patch3** |
| `echomind_settings.json` | R/W | `settings_store.py` | `roaming_config_root() / "echomind_settings.json"` | Always roaming (both dev & installed) |
| `lightviewer_settings.json` | R/W | `lightviewer_settings.py` | `roaming_config_root() / "lightviewer_settings.json"` | Always roaming |
| `filter_settings.json` | R/W | `filter_config.py` | `SOCKET_CONFIG_PATH / "filter_settings.json"` | Image filter presets |
| `filter_presets.json` | R/W | `filter_config.py` | `SOCKET_CONFIG_PATH / "filter_presets.json"` | User-saved filter presets |
| `offline_cloud_servers.json` | R/W | `offline_cloud.py` | `roaming_config_root()` | Offline cloud PACS entries |
| `application_config.json` | R only | `config_manager.py` | `SOCKET_CONFIG_PATH / "application_config.json"` | Viewer config; defaults used if absent; **fixed v2.4.2-patch3** |
| `installation_profile.json` | R only | `aipacs_runtime.py` | `program_data_config_root()` (frozen), `bundled_config_root()` (dev) | Module enable/disable |

---

## Seeding on First Launch

`seed_user_config_defaults()` (in `aipacs_runtime.py`) runs **once per file** (skips if
already exists) on first frozen launch.  It copies all files from `engine/config/` to
`%APPDATA%\AIPacs\config\`.

Files that must exist in `config/` folder to be seeded (and not `.gitignore`d):

```
config/servers.json                 ← empty []  (seeded; user fills via Settings)
config/servers_address.json         ← empty services {}  (seeded)
config/socket_config.json           ← default host/port  (seeded)
config/external_pacs_servers.json   ← empty server list  (seeded)
config/filter_settings.json         ← default filters    (seeded)
config/filter_presets.json          ← default presets     (seeded)
config/echomind_settings.json       ← N/A (echomind uses roaming_config_root directly, creates own defaults)
config/lightviewer_settings.json    ← N/A (lightviewer uses roaming_config_root directly)
```

> `installation_profile.json` is **excluded** from seeding (it's system-written by the installer).

---

## EchoMind Settings

`modules/EchoMind/settings_store.py` uses `roaming_config_root()` unconditionally (both
dev and frozen).  In dev mode, `roaming_config_root()` returns `bundled_config_root()`
= `repo/config/`.  All EchoMind settings are written to `%APPDATA%\AIPacs\config\echomind_settings.json`
in the installed app and `repo/config/echomind_settings.json` in dev mode.
Missing file → `_defaults()` applied automatically.  No user action needed.

API key validation is hardcoded in `modules/EchoMind/api_manager.py` (`CENTERS` list).
The `api_usage.json` file goes to `user_data_root() / "echomind" / "api_usage.json"`.

---

## Module Packages

Module packages are installed at runtime to `C:\ProgramData\AIPacs\module_packages\`
(frozen Windows) or `repo/generated-files/module_packages/` (dev).

`aipacs_runtime.activate_optional_module_runtime()` is called from `main.py` and:
1. Reads each installed package's manifest for `python_paths`
2. Inserts those paths into `sys.path` and `modules.__path__`
3. Adds DLL directories via `os.add_dll_directory()`

**Healthcheck imports** per module (called during load; crash = module disabled):
| Module | healthcheck_import |
|--------|--------------------|
| education | `modules.education.education_main_widget` |
| stitching | `modules.stitching` |
| offline_cloud | `modules.offline_cloud_server.service` |
| printing | `modules.printing.ui.printing_widget` |
| cd_burner | `modules.cd_burner.cd_burn_dialog` |
| web_browser | `modules.web_browser` |
| echomind | `modules.EchoMind.settings_store` |

> **Known issue:** `modules.printing.data` does not exist (see copilot-instructions.md).
> Printing module fails its healthcheck import.  Do NOT enable printing by default until fixed.

---

## Build-Safety Checklist (run before every release build)

### 1. No new relative config paths
Run this search in VS Code or terminal before building:

```
grep -rn "Path([\"']config/" PacsClient/ modules/
grep -rn "open([\"']config/" PacsClient/ modules/
```
**Expected:** zero matches.  Any match = potential broken path in installed app.

### 2. All new config files are in `config/` and not gitignored
If a settings widget was added that reads/writes a new JSON file:
- Add the default file to `config/`
- Ensure `config/` is in `builder/spec/spec_utils.py` `common_app_datas()` (it already is)
- Verify `.gitignore` doesn't suppress it (check `!config/filename.json` if needed)

### 3. New PacsClient subpackages auto-bundled
The spec's `collect_submodules` loop covers `["modules", "database", "PacsClient"]`.
New submodules are auto-discovered.  Only check this if you add a new **top-level package**.

### 4. New top-level imports need `suggested_hiddenimports`
If you add `import new_package` at the top of any module, add `new_package` to
`builder/inventory/imports_summary.json` → `suggested_hiddenimports`.

### 5. Verify seeded defaults
For any new config file that a settings widget writes:
- The default file must live at `config/<filename>.json`
- It must parse without error (`json.JSONDecodeError` check in loader)
- Format must match what the widget's loader expects

### 6. Test in dev mode before building
```powershell
python main.py
```
Open Settings → each tab should load without error.  Add a test server, save, reopen → server must persist.

### 7. After build — smoke test the installer
1. Install to a fresh Windows user profile (or VM)
2. Launch → Settings → Server Settings → add "razi" → save
3. Close → reopen → "razi" must still appear
4. Settings → AI Servers → add URLs → save → reopen → URLs must persist
5. Settings → External PACS → add entry → save → reopen → entry must persist
6. Settings → EchoMind → enter API key → save → reopen → key must show masked

---

## Anti-Patterns (Never Do These)

```python
# ❌ WRONG — relative path breaks in installed app
CONFIG_PATH = Path("config/my_settings.json")

# ❌ WRONG — CWD is not reliable (even with os.chdir in main.py, don't depend on it for writes)
config_dir = Path.cwd() / "config"

# ✅ CORRECT — use SOCKET_CONFIG_PATH (dev: repo/config/, installed: %APPDATA%\AIPacs\config\)
from PacsClient.utils.config import SOCKET_CONFIG_PATH
CONFIG_PATH = Path(SOCKET_CONFIG_PATH) / "my_settings.json"

# ✅ CORRECT — for settings that should always go to roaming profile (both dev and installed)
from aipacs_runtime import roaming_config_root
CONFIG_PATH = roaming_config_root() / "my_settings.json"
```
