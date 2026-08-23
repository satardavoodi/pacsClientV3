"""Which /api/v1 is real: ai-pacs.com/api/v1 or ai-pacs.com/consult-form/api/v1?

The integration contract (2026-08-21) says the base URL is
https://ai-pacs.com/api/v1. The workstation is configured for
https://ai-pacs.com/consult-form. Only one can be right. Unauthenticated:
  401 => route exists, auth required (the right answer)
  404 => route not mounted here
  3xx => the Accept header was not honoured / HTML login redirect
"""
import requests

PATHS = [
    "/me",
    "/chat/statuses",
    "/consultants",
    "/education/shared",
    "/me/entitlements",
    "/auth/workstation/pair",
]
BASES = [
    "https://ai-pacs.com/api/v1",
    "https://ai-pacs.com/consult-form/api/v1",
]
HEADERS = {"Accept": "application/json"}

for base in BASES:
    print(f"\n=== {base} ===")
    for path in PATHS:
        url = base + path
        try:
            r = requests.get(url, headers=HEADERS, timeout=20,
                             allow_redirects=False)
            body = (r.text or "")[:110].replace("\n", " ")
            print(f"  GET {path:24s} -> {r.status_code} "
                  f"{r.headers.get('location','')} | {body}")
        except Exception as exc:
            print(f"  GET {path:24s} -> ERROR {type(exc).__name__}: {exc}")

# Without the Accept header, to confirm the §10.1 redirect warning.
print("\n=== Accept-header check (no Accept) ===")
for base in BASES:
    try:
        r = requests.get(base + "/me", timeout=20, allow_redirects=False)
        print(f"  {base}/me -> {r.status_code} {r.headers.get('location','')}")
    except Exception as exc:
        print(f"  {base}/me -> ERROR {exc}")
