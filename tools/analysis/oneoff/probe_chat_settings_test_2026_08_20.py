"""One-off: run exactly what Settings ▸ Consultation & Education's
"Test chat connection" button runs, and print what the label will say."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from modules.Identity.identity_service import IdentityService
from modules.aipacs_chat.services.chat_client import (
    ChatApiMissingError,
    ChatAuthError,
    ChatClient,
    ChatNotConfiguredError,
)

user = IdentityService.resolve_aipacs_user(None)
print("aipacs_user:", user)
try:
    rows = ChatClient.for_user(user).statuses()
    print(f"RESULT: Connected ✓ — the chat API answered ({len(rows)} case statuses).")
except ChatNotConfiguredError as e:
    print("RESULT: Not configured — sign in to AI-PACS.  (", e, ")")
except ChatAuthError as e:
    print("RESULT: Session expired — sign in again.  (", e, ")")
except ChatApiMissingError as e:
    print("RESULT (api missing):", e)
except Exception as e:
    print("RESULT (transport):", type(e).__name__, "-", e)
