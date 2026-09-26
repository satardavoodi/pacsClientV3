"""Source-development SCM entry. Install through service_admin, never at import."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

if __name__ == '__main__':
    if len(sys.argv) != 2 or not Path(sys.argv[1]).is_absolute():
        raise SystemExit('Supply one absolute Eagle Eye server configuration path.')
    from modules.ai_imaging.eagle_eye_remote.service_host import run_windows_service
    run_windows_service(sys.argv[1])
