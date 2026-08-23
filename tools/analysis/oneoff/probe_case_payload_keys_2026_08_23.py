"""What does a WORKING /chat/cases/{id} payload actually contain?

The widget drops a detail whose ``id`` does not match the open case — the guard
that stops patient A's panel landing on patient B. If the server names that
field something else, the guard rejects every answer and the panel stays blank
even when the endpoint succeeded. Worth knowing before blaming the 500s.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from modules.aipacs_chat.services.chat_client import ChatClient  # noqa: E402

# Ids that answered 200 in probe_case_detail_500_2026_08_23.py.
WORKING = (51, 36, 38)


def main() -> int:
    user = sys.argv[1] if len(sys.argv) > 1 else "vahid"
    client = ChatClient.for_user(user)

    for case_id in WORKING:
        try:
            detail = client.case(case_id)
        except Exception as exc:
            print(f"case {case_id}: {type(exc).__name__} {exc}")
            continue

        print(f"\n=== case {case_id} ===")
        print("keys :", sorted(detail.keys()))
        print("id-ish fields:")
        for key in ("id", "case", "case_id", "reference", "ref"):
            print(f"   {key!r:12} -> {detail.get(key)!r}")
        print("panel fields:")
        for key in ("display_label", "email", "phone", "patient_online",
                    "status", "status_tone", "stage", "summaries", "files",
                    "drive", "location", "device_label", "modality",
                    "source_label", "landing_title", "landing_path",
                    "referrer_host", "journey_steps", "email_sends",
                    "primary_study_file_id", "needs_price_nudge", "pinned",
                    "mirrored"):
            value = detail.get(key, "<MISSING>")
            shown = json.dumps(value, ensure_ascii=False)[:90] if value != "<MISSING>" else "<MISSING>"
            print(f"   {key!r:22} {shown}")
        break   # one full dump is enough
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
