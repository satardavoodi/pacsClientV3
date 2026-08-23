"""One-off: is /api/v1/chat/* live on the configured backend yet?

401 = deployed and gating correctly (no token sent).
404 = the Laravel changes have not been deployed to that host.
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3]))

import requests  # noqa: E402

from modules.Identity.providers.aipacs_web import load_aipacs_web_config  # noqa: E402

BASE = (load_aipacs_web_config().get("base_url") or "").rstrip("/")
print("base_url:", BASE or "(not configured)")

for path in ("/api/v1/me", "/api/v1/chat/sync", "/api/v1/chat/pricing"):
    try:
        response = requests.get(
            BASE + path, headers={"Accept": "application/json"}, timeout=20
        )
        print(f"{path:28s} -> {response.status_code}")
    except Exception as exc:  # pragma: no cover - diagnostic script
        print(f"{path:28s} -> ERROR {exc}")
