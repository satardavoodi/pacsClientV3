"""One-off: MEASURE each model's per-token price from the gateway's own billing.

GapGPT publishes no price list through the API and its pricing page refuses
automated fetch, so prices have until now been transcribed from screenshots -
for two models out of a hundred. But every chat response carries
`usage.cost_details` with the prompt and completion cost of THAT call. Divide by
the tokens the same response reports and the rate falls out, per model, exactly,
without trusting anyone's table.

CAVEAT, and it matters: the field is `upstream_inference_cost` - what the
gateway pays its provider, not necessarily what this centre is billed. On
gpt-5.6-sol it measures $2.00/$10.00 per M against the $2.50/$15.00 the vendor's
page shows, i.e. a markup that is not a single constant. Treat these numbers as
exact for COMPARING models and as a lower bound on the invoice.
"""
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

# Long enough that the prompt rate divides cleanly, short enough to be cheap.
FILLER = ("A radiology workstation packages a set of screenshots and asks a "
          "language model to describe what changed between them. " * 8)


def measure(model):
    payload = {"model": model, "temperature": 0, "max_tokens": 80,
               "messages": [{"role": "user",
                             "content": FILLER + "\nWrite three short sentences about imaging."}]}
    row = {"model": model}
    try:
        response = echomind_http.post(GAPGPT_API_URL, headers=HEADERS, json=payload)
    except Exception as exc:
        row["error"] = f"transport: {exc}"
        return row
    if response.status_code != 200:
        row["error"] = f"{response.status_code}"
        return row
    try:
        body = response.json()
        usage = body.get("usage") or {}
        details = usage.get("cost_details") or {}
        pt = int(usage.get("prompt_tokens") or 0)
        ct = int(usage.get("completion_tokens") or 0)
        row["served_model"] = body.get("model")
        row["provider"] = body.get("provider")
        row["prompt_tokens"] = pt
        row["completion_tokens"] = ct
        row["call_cost"] = usage.get("cost")
        pc = details.get("upstream_inference_prompt_cost")
        cc = details.get("upstream_inference_completions_cost")
        row["in_per_m"] = round(pc / pt * 1e6, 4) if pc is not None and pt else None
        row["out_per_m"] = round(cc / ct * 1e6, 4) if cc is not None and ct else None
        row["reasoning_tokens"] = (usage.get("completion_tokens_details") or {}).get("reasoning_tokens")
    except Exception as exc:
        row["error"] = f"shape: {exc}"
    return row


def main():
    probe = json.loads((OUT / "probe.json").read_text(encoding="utf-8"))
    models = [r["model"] for r in probe if r.get("reachable")]
    print("pricing %d reachable model(s)\n" % len(models))

    with ThreadPoolExecutor(max_workers=6) as pool:
        rows = list(pool.map(measure, models))

    priced = [r for r in rows if r.get("in_per_m") is not None]
    priced.sort(key=lambda r: (r["in_per_m"], r.get("out_per_m") or 0))
    (OUT / "prices.json").write_text(json.dumps(rows, indent=2, ensure_ascii=False),
                                     encoding="utf-8")

    print("%-32s %10s %10s %12s  %s" % ("MODEL", "$/M IN", "$/M OUT", "CALL COST", "PROVIDER"))
    for r in priced:
        print("%-32s %10.3f %10.3f %12.6f  %s"
              % (r["model"][:32], r["in_per_m"], r["out_per_m"] or 0,
                 r.get("call_cost") or 0, str(r.get("provider") or "")[:22]))

    missing = [r for r in rows if r.get("in_per_m") is None]
    if missing:
        print("\nno price measured (%d):" % len(missing))
        for r in missing:
            print("   %-32s %s" % (r["model"][:32], r.get("error", "no cost field")))
    print("\nwrote", OUT / "prices.json")


if __name__ == "__main__":
    main()
