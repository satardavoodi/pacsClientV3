"""One-off: what does /chat/sync actually return when a case is open?

The sidebar's whole job is: click a row -> send ``case=<id>`` -> get a thread
back. This prints the RAW keys of both answers so a mismatch between what the
server sends and what the client parses is visible rather than inferred.

SAFETY: every request here sends ``visible=0``.  ``GET /chat/sync`` is not a
read-only endpoint — with visible=1 the server writes ``staff_last_read_at``,
which clears the unread flag and cancels the staff notification email. A probe
must never do that to a real patient's conversation.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from modules.Identity.identity_service import IdentityService          # noqa: E402
from modules.aipacs_chat.services.chat_client import ChatClient        # noqa: E402
from modules.aipacs_chat.services.models import SyncResponse, Thread   # noqa: E402


def base(req: int, case: int | None = None):
    params = [("m", "0"), ("rev", "0"), ("ev", "0"), ("req", str(req)),
              ("visible", "0"), ("typing", "0")]
    if case:
        params.append(("case", str(case)))
    return params


def main() -> int:
    # Identity is bound per LOCAL workstation user, and a headless probe has no
    # widget to resolve one from — so it is passed in. See
    # probe_identity_owner_2026_08_23.py for what is actually stored.
    user = sys.argv[1] if len(sys.argv) > 1 else IdentityService.resolve_aipacs_user(None)
    print("aipacs_user:", user)
    client = ChatClient.for_user(user)

    # --- 1. the list, with no case open ---------------------------------
    raw = client._call("GET", "/chat/sync", params=client._params(base(1)))
    print("\n=== /chat/sync (no case) ===")
    print("top-level keys :", sorted(raw.keys()) if isinstance(raw, dict) else type(raw))
    rows = raw.get("rows") or []
    print("rows           :", len(rows))
    if rows:
        print("row[0] keys    :", sorted(rows[0].keys()))
        print("row[0]         :", json.dumps(rows[0], ensure_ascii=False)[:400])

    parsed = SyncResponse.parse(raw)
    print("parsed rows    :", len(parsed.rows))
    if parsed.rows:
        print("parsed row[0]  : id=%r title=%r" % (parsed.rows[0].id, parsed.rows[0].title))

    if not rows:
        print("\nNo conversations on this account — nothing further to probe.")
        return 0

    case_id = rows[0].get("id")
    print("\nchosen case_id :", case_id)

    # --- 2. the same endpoint WITH a case open ---------------------------
    raw2 = client._call("GET", "/chat/sync", params=client._params(base(2, case_id)))
    print("\n=== /chat/sync (case=%s) ===" % case_id)
    print("top-level keys :", sorted(raw2.keys()) if isinstance(raw2, dict) else type(raw2))
    for key in ("thread", "case", "cold", "messages"):
        print(f"  has {key!r:12}:", key in raw2)

    thread_raw = raw2.get("thread")
    print("thread type    :", type(thread_raw).__name__)
    if isinstance(thread_raw, dict):
        print("thread keys    :", sorted(thread_raw.keys()))
        msgs = thread_raw.get("messages") or []
        print("thread msgs    :", len(msgs))
        if msgs:
            print("msg[0] keys    :", sorted(msgs[0].keys()))
            print("msg[0]         :", json.dumps(msgs[0], ensure_ascii=False)[:400])
        parsed_thread = Thread.parse(thread_raw)
        print("Thread.parse   :", "None!" if parsed_thread is None else
              f"case={parsed_thread.case} messages={len(parsed_thread.messages)} "
              f"revised={len(parsed_thread.revised)} status={parsed_thread.status!r}")
    else:
        print("!! no thread object in the answer")
        print("raw2 (trimmed) :", json.dumps(raw2, ensure_ascii=False)[:900])

    parsed2 = SyncResponse.parse(raw2)
    print("SyncResponse.thread:", parsed2.thread)

    # --- 3. the case detail the right-hand panel renders ------------------
    detail = client.case(case_id)
    print("\n=== /chat/cases/%s ===" % case_id)
    print("detail keys    :", sorted(detail.keys()) if isinstance(detail, dict) else type(detail))
    for key in ("display_label", "reference", "email", "phone", "summaries",
                "files", "drive", "location", "stage", "email_sends",
                "journey_steps", "pinned"):
        present = isinstance(detail, dict) and key in detail
        value = detail.get(key) if present else None
        shown = json.dumps(value, ensure_ascii=False)[:110] if present else "-"
        print(f"  {key!r:16} {'yes' if present else 'NO '}  {shown}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
