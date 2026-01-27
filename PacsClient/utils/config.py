import sys
from pathlib import Path

# ICON_PATH = './PacsClient/statics/Qss/icons/icons/feather/'
# ICON_PATH = './PacsClient/statics/Qss/icons/fefefe/feather/'
# ICON_PATH = './PacsClient/pacs/workstation_ui/Qss/icons/fefefe/feather/'
# JSON_PATH = './json-styles'
# ICON_PATH = './PacsClient/Qss/icons/fefefe/feather/'

#def find_project_root(start):
#     for p in [start, *start.parents]:
#         if (p / ".git").exists() or (p / "pyproject.toml").exists() or (p / "requirements.txt").exists():
#             return p
#     return start
from PacsClient.utils.utils import get_server_url

# Get base path - use PyInstaller's temp folder if running as executable
def get_base_path():
    """Get the base path for resources, works both in development and PyInstaller executable"""
    if getattr(sys, 'frozen', False):
        # Running as PyInstaller executable
        base_path = Path(sys._MEIPASS)
    else:
        # Running as script
        base_path = Path(__file__).resolve().parents[2]
    return base_path

BASE_PATH = get_base_path()
PROJECT_ROOT = BASE_PATH

ICON_PATH = BASE_PATH / 'Qss/icons/fefefe/feather/'
IMAGES_LOGIN_PATH = BASE_PATH / 'Qss/images/'

JSON_PATH = BASE_PATH / 'json-styles'
THUMBNAIL_PATH = BASE_PATH / 'thumbnails'
ATTACHMENT_PATH = BASE_PATH / 'attachment'

SOURCE_PATH = BASE_PATH / 'source'
SOCKET_CONFIG_PATH = BASE_PATH / 'config'

SEGMENTS_PATH = PROJECT_ROOT / "Segments"
SEGMENTS_PATH.mkdir(parents=True, exist_ok=True)

CLINICAL_CSV_PATH = PROJECT_ROOT / "data" / "clinical_notes.csv"
server_ip=str(get_server_url('segmentation'))
ip=server_ip
import re

match = re.search(r'http://(\d+\.\d+\.\d+\.\d+):\d+', server_ip)
if match:
    ip = match.group(1)
    print(ip)  
server_config = {
    # "SERVER_IP": "80.210.31.214",
    # "SERVER_IP": "81.16.117.196",
    "SERVER_IP": ip,
    "SERVER_PORT": 9000,
    "DEFAULT_OUT_DIR": None,
    "DICOM_FOLDER": None,
    "STUDY_UID": None,
    "DEFAULT_DICOM_FOLDER_CHANGED": False,
    "DEFAULT_SERIES_RULE": "largest",
    "DEFAULT_SEG_NAME": "SEG_From_Server",
    "DOWNLOAD_TO_CLIENT": True,
    "DEBUG_SEG": False,
    "SERIES_INDEX": None,
    "SERIES_UID": None,
    "SERIES_INDEX_CHANGED": False
}