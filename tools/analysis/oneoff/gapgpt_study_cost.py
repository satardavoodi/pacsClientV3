"""One-off: what would ONE Eagle Eye study cost on each vision-capable model?

Rates alone cannot answer this. On the same 320x120 probe tile the models
charged between 62 and 8,519 prompt tokens - a 130x spread - because each
vendor tiles images differently. A cheap $/M rate on a model that bills an
image at 8,000 tokens is not cheap.

So this measures the thing that actually drives the bill: send ONE REAL
captured Eagle Eye frame with max_tokens=1, read `prompt_tokens` and the
prompt cost the gateway reports, and scale to the 41 frames a lumbar study
sends. Costs about a tenth of a cent per model instead of a real study each.

Output cost is added from the ranges measured on live runs (3k-9k completion
tokens across both passes).
"""
import base64
import json
import pathlib
import sys
from concurrent.futures import ThreadPoolExecutor

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
OUT = ROOT / "generated-files" / "gapgpt"

FRAMES_PER_STUDY = 41          # measured: 11 sagittal + 30 axial
PASSES = 2                     # screening + verification both send every frame
OUTPUT_TOKENS = 12000          # measured total across both passes, generously

frame = sys.argv[1] if len(sys.argv) > 1 else None
if not frame:
    base = (ROOT / "user_data" / "ai" / "eagle_eye")
    frame = str(next(base.rglob("Axial/*.png")))
IMAGE_B64 = base64.b64encode(pathlib.Path(frame).read_bytes()).decode("ascii")
print("real frame:", pathlib.Path(frame).name,
      "(%.0f KB)\n" % (len(IMAGE_B64) * 3 / 4 / 1024))


def measure(model):
    payload = {"model": model, "temperature": 0, "max_tokens": 1,
               "messages": [{"role": "user", "content": [
                   {"type": "text", "text": "Describe this lumbar MRI screenshot."},
                   {"type": "image_url", "image_url": {
                       "url": f"data:image/png;base64,{IMAGE_B64}", "detail": "high"}},
               ]}]}
    row = {"model": model}
    try:
        response = echomind_http.post(GAPGPT_API_URL, headers=HEADERS, json=payload)
    except Exception as exc:
        row["error"] = f"transport: {exc}"
        return row
    if response.status_code != 200:
        row["error"] = str(response.status_code)
        return row
    try:
        usage = response.json().get("usage") or {}
        details = usage.get("cost_details") or {}
        row["frame_tokens"] = int(usage.get("prompt_tokens") or 0)
        row["frame_cost"] = details.get("upstream_inference_prompt_cost")
    except Exception as exc:
        row["error"] = f"shape: {exc}"
    return row


def main():
    probe = {r["model"]: r for r in json.loads((OUT / "probe.json").read_text("utf-8"))}
    prices = {r["model"]: r for r in json.loads((OUT / "prices.json").read_text("utf-8"))}
    models = [m for m, r in probe.items() if r.get("vision") == "reads"]
    print("measuring %d vision-capable model(s)\n" % len(models))

    with ThreadPoolExecutor(max_workers=6) as pool:
        rows = list(pool.map(measure, models))

    table = []
    for row in rows:
        model = row["model"]
        price = prices.get(model, {})
        out_rate = price.get("out_per_m")
        cost = row.get("frame_cost")
        if cost is None or not row.get("frame_tokens"):
            row["study_usd"] = None
        else:
            image_cost = cost * FRAMES_PER_STUDY * PASSES
            out_cost = (out_rate or 0) * OUTPUT_TOKENS / 1e6
            row["study_usd"] = round(image_cost + out_cost, 4)
        row["in_per_m"] = price.get("in_per_m")
        row["out_per_m"] = price.get("out_per_m")
        table.append(row)

    priced = sorted([r for r in table if r.get("study_usd") is not None],
                    key=lambda r: r["study_usd"])
    (OUT / "study_cost.json").write_text(json.dumps(table, indent=2), encoding="utf-8")

    print("%-32s %8s %11s %10s %10s" %
          ("MODEL", "TOK/IMG", "USD/STUDY", "$/M IN", "$/M OUT"))
    for r in priced:
        print("%-32s %8d %11.4f %10s %10s" % (
            r["model"][:32], r["frame_tokens"], r["study_usd"],
            r.get("in_per_m"), r.get("out_per_m")))

    unknown = [r for r in table if r.get("study_usd") is None]
    print("\nno study cost (%d): %s" % (len(unknown),
          ", ".join(r["model"] for r in unknown)))
    print("wrote", OUT / "study_cost.json")


if __name__ == "__main__":
    main()
