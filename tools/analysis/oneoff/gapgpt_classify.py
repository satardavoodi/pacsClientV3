"""One-off: split the GapGPT catalogue into what could possibly serve this app.

The gateway publishes no capability flags - only an id, a vendor and an endpoint
type - so the first cut has to be by NAME, and a name-based cut is a hypothesis,
not an answer. Everything that survives here still gets probed against the real
API before it is allowed near a study.

Read-only, offline: works from the dumped catalogue.
"""
import json
import pathlib
import re
import sys
from collections import Counter, defaultdict

ROOT = pathlib.Path(__file__).resolve().parents[3]
RAW = ROOT / "generated-files" / "gapgpt" / "models_raw.json"

# Families that cannot answer a chat/completions request with a report in it.
# Matched on the id, so a false positive here silently drops a usable model -
# keep the patterns specific and print what was dropped.
NON_CHAT = [
    ("embedding", r"embed"),
    ("image generation", r"(^|-)(dall-e|imagen|flux|sora|seedream|kandinsky|midjourney)|image-preview|-image$|gpt-image"),
    ("speech / audio", r"tts|whisper|transcribe|audio|speech|voice|realtime|live-"),
    ("video", r"veo|kling|runway|luma|video"),
    ("rerank / moderation", r"rerank|moderation|guard"),
    ("search product", r"search-preview|sonar"),
]


def bucket(model_id):
    for label, pattern in NON_CHAT:
        if re.search(pattern, model_id, re.I):
            return label
    return "chat candidate"


def main():
    models = json.loads(RAW.read_text(encoding="utf-8"))["data"]
    grouped = defaultdict(list)
    for entry in models:
        grouped[bucket(str(entry.get("id")))].append(entry)

    print("catalogue: %d models\n" % len(models))
    for label in sorted(grouped, key=lambda k: -len(grouped[k])):
        print("  %-22s %3d" % (label, len(grouped[label])))

    print("\nvendors (owned_by):")
    for vendor, count in Counter(str(m.get("owned_by")) for m in models).most_common():
        print("  %-16s %3d" % (vendor, count))

    print("\nendpoint types:")
    kinds = Counter(",".join(m.get("supported_endpoint_types") or []) for m in models)
    for kind, count in kinds.most_common():
        print("  %-16s %3d" % (kind or "(none)", count))

    print("\n--- EXCLUDED, by reason ---")
    for label in sorted(grouped):
        if label == "chat candidate":
            continue
        print("\n%s:" % label)
        for entry in sorted(grouped[label], key=lambda e: str(e.get("id"))):
            print("   ", entry.get("id"))

    candidates = sorted(str(e.get("id")) for e in grouped["chat candidate"])
    print("\n--- CHAT CANDIDATES (%d) ---" % len(candidates))
    for name in candidates:
        print("   ", name)

    out = RAW.with_name("candidates.json")
    out.write_text(json.dumps(candidates, indent=2), encoding="utf-8")
    print("\nwrote", out)


if __name__ == "__main__":
    main()
