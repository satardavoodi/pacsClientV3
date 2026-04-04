import json
import os
import json
import re
import sys
from pathlib import Path

from aipacs_runtime import roaming_config_root, seed_user_config_defaults
from . import database
from .offline_cloud import get_all_offline_cloud_servers, get_offline_cloud_server

json_file = 'servers.json'
from _project_root import PROJECT_ROOT as _ROOT
if getattr(sys, "frozen", False):
    seed_user_config_defaults()
    CONFIG_DIR = roaming_config_root()
else:
    CONFIG_DIR = _ROOT / "config"
SERVERS_FILE = CONFIG_DIR / "servers_address.json"
_SERVERS_FILE_MISSING_WARNED = False


def _safe_print(*args, **kwargs):
    stream = sys.stdout or sys.__stdout__
    if not stream or getattr(stream, "closed", False):
        return
    try:
        print(*args, **kwargs)
    except Exception:
        pass




def extract_threshold_label(filename: str) -> str:
    """
    Examples:
      updated_csv_with_boxes_0.45.csv   -> 0.45
      updated_csv_with_boxes_0.45_2.csv -> 0.45_2
    """
    m = re.search(r"updated_csv_with_boxes_(.+)\.csv$", filename)
    return m.group(1) if m else ""



def load_mg_ai_runs(study_uid: str, attachments_path: Path):
    """
    Load all available MG AI runs from manifest
    and enrich them with UI-friendly threshold labels.

    Each run will have:
      - threshold_label (e.g. "0.45", "0.45_2")
    """
    try:
        manifest_path = attachments_path / study_uid / "mg_ai_manifest.json"
        if not manifest_path.exists():
            return None

        with open(manifest_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        available = data.get("available", [])
        active = data.get("active", {})

        enriched = []
        for run in available:
            det = run.get("detection", "")
            cls = run.get("classification")

            # ✅ UI label from filename (handles _2, _3, ...)
            threshold_label = extract_threshold_label(det)

            enriched.append({
                **run,
                "threshold_label": threshold_label
            })

        return {
            "available": enriched,
            "active": active
        }

    except Exception as e:
        print(f"[MG][UTILS] failed to load runs: {e}")
        return None



def load_mg_ai_manifest(
    study_uid: str,
    attachments_path: Path
):
    """
    Load MG AI manifest for a study if exists.

    Args:
        study_uid (str): Study UID
        attachments_path (Path): Base attachment path

    Returns:
        tuple[Path | None, Path | None]:
            (detection_csv_path, classification_csv_path)
            or (None, None) if not found / invalid
    """
    try:
        manifest_path = attachments_path / study_uid / "mg_ai_manifest.json"
        if not manifest_path.exists():
            return None, None

        with open(manifest_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        active = data.get("active", {})
        det = active.get("detection")
        cls = active.get("classification")

        if not det or not cls:
            return None, None

        det_path = attachments_path / study_uid / det
        cls_path = attachments_path / study_uid / cls

        if not det_path.exists() or not cls_path.exists():
            return None, None

        return det_path, cls_path

    except Exception as e:
        print(f"[MG][UTILS] failed to load manifest: {e}")
        return None, None


def get_server_url(name: str) -> str | None:
    """
    Return URL for a given AI service name (breast, boneage, segmentation).

    Supports multiple on-disk formats:
      1) {"services": {"breast": "...", "boneage": "..."}}
      2) [{"name":"breast","url":"..."} , ...]
    Adds http:// prefix automatically if missing.
    """
    global _SERVERS_FILE_MISSING_WARNED
    if not SERVERS_FILE.exists():
        if not _SERVERS_FILE_MISSING_WARNED:
            _safe_print("servers_address.json not found:", SERVERS_FILE)
            _SERVERS_FILE_MISSING_WARNED = True
        return None

    try:
        with open(SERVERS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)

        url = None

        # Case A: new format - dict with "services" mapping
        if isinstance(data, dict) and "services" in data and isinstance(data["services"], dict):
            url = data["services"].get(name)

        # Case B: list of {"name":..., "url":...}
        elif isinstance(data, list):
            for item in data:
                if isinstance(item, dict) and item.get("name") == name:
                    url = item.get("url")
                    break

        # Case C: maybe the top-level is already the mapping {name: url}
        elif isinstance(data, dict):
            if name in data:
                url = data.get(name)
            else:
                for k, v in data.items():
                    if isinstance(v, dict) and name in v:
                        url = v.get(name)
                        break

        # If no matching URL found
        if not url:
            return None

        # ---------------------------
        # Normalize URL:
        # Add http:// if scheme missing
        # ---------------------------
        url = url.strip()

        if not (url.startswith("http://") or url.startswith("https://")):
            url = "http://" + url

        return url

    except Exception as e:
        _safe_print("Error reading servers_address.json:", e)
        return None


def client_desktop_path():
    """Return a suitable Desktop path for saving downloads.

    Tries to resolve the user's Desktop directory in a cross-platform manner.
    If Desktop does not exist, falls back to the user's home directory.

    Returns:
        pathlib.Path: Path object pointing to Desktop or Home.
    """
    home = Path.home()
    desk = home / "Desktop"
    return desk if desk.exists() else home


def segment_path():
    return

# get special server
def get_server(server_name):
    if os.path.exists(json_file):
        with open(json_file, 'r', encoding='utf-8') as f:
            try:
                servers = json.load(f)
                server = next((s for s in servers if s['name'] == server_name), None)
                return server
            except json.JSONDecodeError:
                return []
    print('servers.json does not exist!!')
    return []


# get servers from servers.json
def get_all_servers():
    if os.path.exists(json_file):
        with open(json_file, 'r', encoding='utf-8') as f:
            try:
                return json.load(f)
            except json.JSONDecodeError:
                return []
    return []


def get_all_selectable_servers():
    servers: list[dict] = []
    for server in get_all_servers():
        if not isinstance(server, dict):
            continue
        server_copy = dict(server)
        server_copy.setdefault("server_type", "ai_pacs")
        servers.append(server_copy)
    servers.extend(get_all_offline_cloud_servers())
    return servers


def get_selectable_server(server_name: str):
    server_name = str(server_name or "").strip()
    if not server_name:
        return None

    server = get_server(server_name)
    if server:
        server = dict(server)
        server.setdefault("server_type", "ai_pacs")
        return server

    return get_offline_cloud_server(server_name)


def get_all_patients():
    return database.get_all_patients()


def search_patients_local(search_data: dict):
    """Search patients in local database with filters."""
    return database.search_patients_local(search_data)


class Singleton(type):
    _instance = None

    def __call__(self, *args, **kwargs):
        if self._instance is None:
            self._instance = super().__call__()
        return self._instance


class UpdaterDataFromServerToHome(metaclass=Singleton):
    '''
        add updater data from setting_server to home page (server selection)
    '''

    def set_combo_server(self, servers_combo):
        self.server_combo = servers_combo

    def update(self):
        if not hasattr(self, "server_combo") or self.server_combo is None:
            return
        if hasattr(self.server_combo, "load_servers"):
            self.server_combo.load_servers()
            return
        self.server_combo.clear()
        servers = get_all_selectable_servers()
        for server in servers:
            self.server_combo.addItem(server['name'])


class CallerTypes:
    SERVER = 'server'  # select patient from server
    IMPORT = 'import'  # load folder on pc
    LOCAL = 'local'  # from database


from typing import List, Union, Iterable, Optional


def list_files_in_folder(
    folder_path: Union[str, Path],
    recursive: bool = False,
    patterns: Optional[Iterable[str]] = None,
    as_str: bool = True,
) -> List[Union[str, Path]]:
    """
    مسیر یک فولدر را می‌گیرد و مسیر تمام فایل‌های موجود را برمی‌گرداند.

    پارامترها:
      folder_path : مسیر فولدر
      recursive   : اگر True باشد، زیر‌پوشه‌ها هم بررسی می‌شوند
      patterns    : الگوهای فایلی مانند ["*.png", "*.jpg", "*.dcm"].
                    اگر None باشد، همه‌ی فایل‌ها برگردانده می‌شوند.
      as_str      : اگر True باشد خروجی به صورت str است، وگرنه Path

    خروجی:
      لیستی مرتب از مسیر فایل‌ها
    """
    root = Path(folder_path).expanduser().resolve()
    if not root.is_dir():
        return []

    # انتخاب الگوها
    globs = list(patterns) if patterns else ["*"]

    files = []
    if recursive:
        for pat in globs:
            files.extend(root.rglob(pat))
    else:
        for pat in globs:
            files.extend(root.glob(pat))

    # فقط فایل‌ها (نه پوشه‌ها)، یکتا و مرتب
    file_paths = sorted({p for p in files if p.is_file()})

    return [str(p) for p in file_paths] if as_str else file_paths
