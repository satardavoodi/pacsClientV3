"""One-off: does the gateway tell us what a call COST?

/v1/models publishes no prices and the vendor's pricing page blocks automated
fetch, so the only remaining source of truth is the gateway's own accounting.
Gateways of this family often return a quota/cost header per request, or expose
a usage endpoint. If either works, price becomes something MEASURED per model
instead of transcribed from a screenshot.
"""
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from modules.ai_imaging.eagle_eye_lumbar import llm_backend  # noqa: E402

denied = llm_backend.company_entitlement_error()
if denied:
    raise SystemExit("not entitled: " + denied)

from modules.EchoMind import echomind_http                      # noqa: E402
from modules.EchoMind.ai_chat_config import GAPGPT_API_URL      # noqa: E402
from modules.EchoMind.viewer_chat.api_manager import Manage     # noqa: E402

CENTER, API_KEY = Manage.instance().get_center_and_gapgpt_key()
HEADERS = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}
ROOT_URL = GAPGPT_API_URL.rsplit("/v1", 1)[0]

payload = {"model": "gpt-5.6-sol", "max_tokens": 8, "temperature": 0,
           "messages": [{"role": "user", "content": "Say OK"}]}
response = echomind_http.post(GAPGPT_API_URL, headers=HEADERS, json=payload)
print("POST /v1/chat/completions ->", response.status_code)
print("\nresponse headers:")
for key, value in sorted(response.headers.items()):
    print("  %-34s %s" % (key, str(value)[:90]))

print("\nbody top-level keys:", sorted(response.json().keys()))
print("usage:", json.dumps(response.json().get("usage"), ensure_ascii=False))

for path in ("/v1/dashboard/billing/usage?start_date=2026-08-01&end_date=2026-08-31",
             "/v1/dashboard/billing/credit_grants",
             "/v1/me", "/v1/quota", "/v1/user/quota"):
    try:
        probe = echomind_http.get(ROOT_URL + path, headers=HEADERS)
        print("\nGET %-58s -> %s  %s"
              % (path[:58], probe.status_code, (probe.text or "")[:220].replace("\n", " ")))
    except Exception as exc:
        print("\nGET %-58s -> ERROR %s" % (path[:58], exc))
