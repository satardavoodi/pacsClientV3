"""Which cases make GET /chat/cases/{id} throw, and what do they have in common?

Turns "some conversations 500" into a repro the backend can act on: for every
case it records the row's status/tone, whether the thread carries file or
price messages, and whether the detail endpoint answered.

Read-only. Every sync request sends visible=0.
"""

import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from modules.Identity.providers.aipacs_web import API_PREFIX     # noqa: E402
from modules.aipacs_chat.services.chat_client import ChatClient  # noqa: E402


def main() -> int:
    user = sys.argv[1] if len(sys.argv) > 1 else "vahid"
    limit = int(sys.argv[2]) if len(sys.argv) > 2 else 20

    client = ChatClient.for_user(user)
    web = client._client
    session = web._ensure_session()
    headers = {"Authorization": f"Bearer {web._token}", "Accept": "application/json"}

    def sync(req, case=None):
        params = [("m", "0"), ("rev", "0"), ("ev", "0"), ("req", str(req)),
                  ("visible", "0"), ("typing", "0")]
        if case:
            params.append(("case", str(case)))
        return client._call("GET", "/chat/sync", params=client._params(params))

    rows = sync(1).get("rows") or []
    print(f"{len(rows)} conversations; probing the first {limit}\n")
    print(f"{'case':>5} {'detail':>6}  {'status':<20} {'tone':<6} "
          f"{'msgs':>4} {'file':>4} {'price':>5} {'link':>4}  unread")
    print("-" * 78)

    records = []
    for index, row in enumerate(rows[:limit]):
        case_id = row.get("id")

        url = f"{web.base_url}{API_PREFIX}/chat/cases/{case_id}"
        status = session.get(url, headers=headers, timeout=web._timeout).status_code

        thread = (sync(index + 2, case_id) or {}).get("thread") or {}
        messages = thread.get("messages") or []
        kinds = Counter(str(m.get("type") or "text") for m in messages)

        records.append({
            "case": case_id, "detail": status,
            "status": row.get("status"), "tone": row.get("tone"),
            "msgs": len(messages), "file": kinds.get("file", 0),
            "price": kinds.get("price_offer", 0) + kinds.get("price", 0),
            "link": kinds.get("link", 0) + kinds.get("imaging_link", 0),
            "unread": row.get("unread"),
        })
        r = records[-1]
        print(f"{r['case']:>5} {r['detail']:>6}  {str(r['status']):<20} "
              f"{str(r['tone']):<6} {r['msgs']:>4} {r['file']:>4} "
              f"{r['price']:>5} {r['link']:>4}  {r['unread']}")

    ok = [r for r in records if r["detail"] == 200]
    bad = [r for r in records if r["detail"] != 200]
    print(f"\n{len(ok)} ok / {len(bad)} failed")

    def summarise(label, group):
        if not group:
            return
        print(f"\n{label} ({len(group)}):")
        print("   statuses :", dict(Counter(str(r['status']) for r in group)))
        print("   any file :", sum(1 for r in group if r['file']))
        print("   any price:", sum(1 for r in group if r['price']))
        print("   msg count:", sorted(r['msgs'] for r in group))

    summarise("WORKING", ok)
    summarise("FAILING", bad)

    only_bad = {str(r["status"]) for r in bad} - {str(r["status"]) for r in ok}
    only_ok = {str(r["status"]) for r in ok} - {str(r["status"]) for r in bad}
    print("\nstatuses seen ONLY on failing cases :", sorted(only_bad) or "none")
    print("statuses seen ONLY on working cases :", sorted(only_ok) or "none")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
