"""One-off: probe every GapGPT chat candidate for REACHABILITY and VISION.

Two facts decide whether a model can serve any part of this app, and the
gateway publishes neither: can this key actually reach it, and can it read an
image. A name cannot answer either - `gapgpt-qwen-3.8` looked perfectly real
and returned model_not_found.

The vision probe deliberately asks the model to READ A WORD rendered into the
image rather than name a colour. Eagle Eye's real workload is reading small
text and fine structure out of a screenshot; a model that can only tell red
from blue would pass a colour test and still be useless here. It also separates
"saw the image" from "guessed plausibly", which a colour test does not.

Costs a few hundred tokens per model. Read-only with respect to the app.
"""
import base64
import io
import json
import pathlib
import sys
import time
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

SECRET_WORD = "LUMBAR"
OUT = ROOT / "generated-files" / "gapgpt"


def make_probe_image():
    """A small white tile with SECRET_WORD printed large and black."""
    from PIL import Image, ImageDraw, ImageFont
    img = Image.new("RGB", (320, 120), "white")
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("arialbd.ttf", 64)
    except Exception:
        font = ImageFont.load_default()
    draw.text((18, 26), SECRET_WORD, fill="black", font=font)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("ascii")


IMAGE_B64 = make_probe_image()


def call(model, content, max_tokens=1024):
    """max_tokens is deliberately GENEROUS.

    The first version of this probe used 24 and reported gemini-3.1-pro-preview,
    gpt-5.2, o3 and every other reasoning model as blind - while their usage
    showed the image tokens had been counted. They had SEEN the image and spent
    the whole 24-token budget on internal reasoning, returning empty content. A
    tight budget does not measure vision, it measures reasoning verbosity.
    """
    payload = {"model": model, "messages": [{"role": "user", "content": content}],
               "max_tokens": max_tokens, "temperature": 0}
    started = time.time()
    try:
        response = echomind_http.post(GAPGPT_API_URL, headers=HEADERS, json=payload)
    except Exception as exc:
        return {"ok": False, "error": f"transport: {exc}", "seconds": round(time.time() - started, 1)}
    elapsed = round(time.time() - started, 1)
    if response.status_code != 200:
        try:
            detail = response.json().get("error", {})
            message = str(detail.get("code") or detail.get("message") or "")[:90]
        except Exception:
            message = (response.text or "")[:90]
        return {"ok": False, "error": f"{response.status_code}: {message}", "seconds": elapsed}
    try:
        body = response.json()
        choice = body["choices"][0]
        text = (choice["message"].get("content") or "").strip()
        usage = body.get("usage") or {}
    except Exception as exc:
        return {"ok": False, "error": f"shape: {exc}", "seconds": elapsed}
    # `served_model` is the model the GATEWAY says answered. It is not always
    # the one that was asked for, and for a medical read that matters.
    return {"ok": True, "text": text[:160], "seconds": elapsed,
            "finish_reason": choice.get("finish_reason"),
            "served_model": body.get("model"),
            "prompt_tokens": usage.get("prompt_tokens"),
            "completion_tokens": usage.get("completion_tokens")}


def probe(model):
    result = {"model": model}

    text = call(model, "Reply with exactly one word: READY")
    result["reachable"] = text["ok"]
    result["text_seconds"] = text.get("seconds")
    if not text["ok"]:
        result["error"] = text["error"]
        result["vision"] = "not tested"
        return result
    result["text_reply"] = text.get("text", "")
    result["text_ok"] = "READY" in text.get("text", "").upper()

    vision = call(model, [
        {"type": "text",
         "text": "One word only: what word is written in this image?"},
        {"type": "image_url",
         "image_url": {"url": f"data:image/png;base64,{IMAGE_B64}", "detail": "high"}},
    ])
    result["vision_seconds"] = vision.get("seconds")
    if not vision["ok"]:
        result["vision"] = "refused"
        result["vision_error"] = vision["error"]
        return result
    reply = vision.get("text", "")
    result["vision_reply"] = reply
    result["vision_prompt_tokens"] = vision.get("prompt_tokens")
    result["vision_completion_tokens"] = vision.get("completion_tokens")
    result["finish_reason"] = vision.get("finish_reason")
    result["served_model"] = vision.get("served_model")
    result["substituted"] = bool(vision.get("served_model")
                                 and vision["served_model"] != model)
    if SECRET_WORD in reply.upper():
        result["vision"] = "reads"
    elif not reply and vision.get("finish_reason") == "length":
        # Saw the image, ran out of budget mid-reasoning. Not a vision verdict.
        result["vision"] = "no answer"
    else:
        result["vision"] = "blind"
    return result


def main():
    candidates = json.loads((OUT / "candidates.json").read_text(encoding="utf-8"))
    if len(sys.argv) > 1:
        candidates = candidates[:int(sys.argv[1])]
    print("probing %d model(s) via %s\n" % (len(candidates), CENTER))

    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(probe, candidates))

    results.sort(key=lambda r: (r.get("vision") != "reads",
                                not r.get("reachable"), r["model"]))
    (OUT / "probe.json").write_text(json.dumps(results, indent=2, ensure_ascii=False),
                                    encoding="utf-8")

    reads = [r for r in results if r.get("vision") == "reads"]
    blind = [r for r in results if r.get("vision") == "blind"]
    refused = [r for r in results if r.get("vision") == "refused"]
    dead = [r for r in results if not r.get("reachable")]

    print("%-32s %-9s %-6s %7s %6s %-4s %s"
          % ("MODEL", "VISION", "TEXT", "IMG-TOK", "SECS", "SUB", "NOTE"))
    for r in results:
        note = r.get("error") or r.get("vision_error") or r.get("vision_reply", "")
        print("%-32s %-9s %-6s %7s %6s %-4s %s" % (
            r["model"][:32], r.get("vision", "-"),
            "ok" if r.get("text_ok") else ("reply" if r.get("reachable") else "-"),
            r.get("vision_prompt_tokens") or "-",
            r.get("vision_seconds") or "-",
            "YES" if r.get("substituted") else "",
            str(note)[:44]))

    swapped = [r for r in results if r.get("substituted")]
    print("\nreads image: %d | blind: %d | no answer: %d | refused image: %d | unreachable: %d"
          % (len(reads), len(blind),
             len([r for r in results if r.get("vision") == "no answer"]),
             len(refused), len(dead)))
    if swapped:
        print("\nGATEWAY SERVED A DIFFERENT MODEL THAN ASKED FOR:")
        for r in swapped:
            print("   asked %-30s served %s" % (r["model"], r.get("served_model")))
    print("wrote", OUT / "probe.json")


if __name__ == "__main__":
    main()
