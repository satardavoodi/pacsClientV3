"""One-off: dump everything GapGPT will tell us about the models on this key.

Before spending a single image request we need to know what the gateway
already knows: how many models, what metadata rides on each, and whether it
publishes prices anywhere. Guessing a shortlist from model NAMES is how you end
up sending 41 screenshots to a text-only model.

Read-only. Writes the raw catalogue to disk so later passes do not re-query.
"""
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3]))

from modules.ai_imaging.eagle_eye_lumbar import llm_backend  # noqa: E402

denied = llm_backend.company_entitlement_error()
if denied:
    raise SystemExit("not entitled: " + denied)

from modules.EchoMind import echomind_http                      # noqa: E402
from modules.EchoMind.ai_chat_config import GAPGPT_API_URL      # noqa: E402
from modules.EchoMind.viewer_chat.api_manager import Manage     # noqa: E402

center, api_key = Manage.instance().get_center_and_gapgpt_key()
base = GAPGPT_API_URL.replace("/chat/completions", "")
root = base.rsplit("/v1", 1)[0]
headers = {"Authorization": f"Bearer {api_key}"}

out = pathlib.Path(__file__).resolve().parents[3] / "generated-files" / "gapgpt"
out.mkdir(parents=True, exist_ok=True)

# 1. the model list, in full
response = echomind_http.get(base + "/models", headers=headers)
print("GET /v1/models ->", response.status_code)
payload = response.json()
models = payload.get("data") or []
(out / "models_raw.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False),
                                     encoding="utf-8")
print("models:", len(models))

keys = sorted({k for m in models for k in m.keys()})
print("fields per entry:", keys)
print("\nsample entry:")
print(json.dumps(models[0], indent=2, ensure_ascii=False)[:1200])

# 2. anywhere a gateway of this family tends to publish prices
for path in ("/v1/pricing", "/api/pricing", "/api/models", "/api/status",
             "/v1/dashboard/billing/subscription", "/api/user/self"):
    try:
        probe = echomind_http.get(root + path, headers=headers)
        body = (probe.text or "")[:300].replace("\n", " ")
        print("\nGET %-40s -> %s  %s" % (path, probe.status_code, body))
    except Exception as exc:
        print("\nGET %-40s -> ERROR %s" % (path, exc))

print("\nwrote", out / "models_raw.json")
