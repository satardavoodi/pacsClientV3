"""Is GET /chat/cases/{id} broken for one case, or for all of them?

The right-hand detail panel is fed entirely by this endpoint. It answered 500
for the first case tried, which would leave the panel blank no matter what the
client does — so the question is whether that is data-dependent or total.

Read-only: this endpoint does not write.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from modules.Identity.providers.aipacs_web import API_PREFIX          # noqa: E402
from modules.aipacs_chat.services.chat_client import ChatClient       # noqa: E402


def main() -> int:
    user = sys.argv[1] if len(sys.argv) > 1 else "vahid"
    client = ChatClient.for_user(user)
    web = client._client
    session = web._ensure_session()
    headers = {"Authorization": f"Bearer {web._token}",
               "Accept": "application/json"}

    rows = client._call("GET", "/chat/sync", params=client._params(
        [("m", "0"), ("rev", "0"), ("ev", "0"), ("req", "1"),
         ("visible", "0"), ("typing", "0")]
    )).get("rows") or []
    print(f"{len(rows)} conversations on the account\n")

    ok = bad = 0
    for row in rows[:12]:
        case_id = row.get("id")
        url = f"{web.base_url}{API_PREFIX}/chat/cases/{case_id}"
        resp = session.get(url, headers=headers, timeout=web._timeout)
        status = resp.status_code
        if status == 200:
            ok += 1
            try:
                payload = resp.json().get("case", {})
                keys = len(payload) if isinstance(payload, dict) else 0
            except Exception:
                keys = -1
            print(f"  case {case_id:<5} {status}  ok, {keys} fields")
        else:
            bad += 1
            body = (resp.text or "")[:220].replace("\n", " ")
            print(f"  case {case_id:<5} {status}  {body}")

    print(f"\n{ok} ok / {bad} failed")

    if bad:
        # Laravel hides the real message unless APP_DEBUG is on. Ask for it
        # anyway — some deployments return a JSON 'message' regardless.
        case_id = rows[0].get("id")
        url = f"{web.base_url}{API_PREFIX}/chat/cases/{case_id}"
        resp = session.get(url, headers=headers, timeout=web._timeout)
        print("\nfull body of one failure:")
        print(" content-type:", resp.headers.get("content-type"))
        print(" body        :", (resp.text or "")[:1200])
        try:
            print(" json        :", json.dumps(resp.json(), ensure_ascii=False)[:800])
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
