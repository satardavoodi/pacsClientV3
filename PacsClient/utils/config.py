import sys
from pathlib import Path

from PacsClient.utils.utils import get_server_url
from _project_root import PROJECT_ROOT as _ROOT

# ── Software-level paths (app code / resources) ───────────────────────────────
BASE_PATH: Path = _ROOT
PROJECT_ROOT: Path = _ROOT

ICON_PATH = BASE_PATH / 'Qss/icons/fefefe/feather/'
IMAGES_LOGIN_PATH = BASE_PATH / 'Qss/images/'
JSON_PATH = BASE_PATH / 'json-styles'
SOCKET_CONFIG_PATH = BASE_PATH / 'config'

# ── User data paths (downloaded / generated / cached) ─────────────────────────
# Canonical definitions live in data_paths.py; re-exported here for convenience.
from PacsClient.utils.data_paths import (                       # noqa: E402
    USER_DATA_ROOT,
    DICOM_IMAGES_DIR   as SOURCE_PATH,
    ATTACHMENTS_DIR    as ATTACHMENT_PATH,
    THUMBNAILS_DIR     as THUMBNAIL_PATH,
    EDUCATION_COURSES_DIR   as EDUCATION_STORAGE_PATH,
    EDUCATION_ASSETS_DIR    as EDUCATION_ASSETS_PATH,
    EDUCATION_MY_COURSE_DIR as EDUCATION_MY_COURSE_PATH,
    CASE_OF_DAY_DIR         as CASE_OF_DAY_STORAGE_PATH,
    SEGMENTS_DIR       as SEGMENTS_PATH,
    CLINICAL_CSV_FILE  as CLINICAL_CSV_PATH,
    DATABASE_FILE      as DATABASE_PATH,
    LOGS_DIR,
    ECHOMIND_MEMORY_DIR,
    ECHOMIND_LOGS_DIR,
    ZETA_BOOST_CACHE_DIR,
    RECEPTION_REPORTS_DIR,
)
server_ip=str(get_server_url('segmentation'))
ip=server_ip
import re

match = re.search(r'http://(\d+\.\d+\.\d+\.\d+):\d+', server_ip)
if match:
    ip = match.group(1)
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
