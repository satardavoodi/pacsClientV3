"""One-off: ask GapGPT which models THIS centre's key can actually reach.

A wrong model id fails only at request time, after the study has been captured -
and `gapgpt-qwen-3.8` from the vendor's sample snippet came back
"No available channel for model ... under group default (distributor)", which is
an entitlement answer, not a typo answer. This lists what the key really has, so
a bake-off is planned against reality instead of a screenshot.

Read-only: one GET to /v1/models. Uses the SAME key path and the SAME transport
as every other GapGPT call - it is a diagnostic, not a second AI path.
"""
import pathlib
import re
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
url = GAPGPT_API_URL.replace("/chat/completions", "/models")

response = echomind_http.get(url, headers={"Authorization": f"Bearer {api_key}"})
print("centre:", center, "| GET", url, "->", response.status_code)
if response.status_code != 200:
    print(response.text[:800])
    raise SystemExit(1)

ids = sorted(str(m.get("id") or "") for m in (response.json().get("data") or []))
print("%d model(s) available\n" % len(ids))

wanted = sys.argv[1:] or ["qwen", "gemini", "gpt-5.6", "sol", "terra"]
for term in wanted:
    hits = [i for i in ids if re.search(term, i, re.I)]
    print("  %-10s %s" % (term, ", ".join(hits) if hits else "- none -"))
