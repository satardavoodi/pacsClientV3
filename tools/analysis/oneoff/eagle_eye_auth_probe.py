"""One-off: can an Eagle Eye analysis authenticate OUTSIDE the running app?

The GapGPT key is runtime-derived, and an earlier probe failed with "No
validated IRANNOBAT API key" - but that probe asked `Manage` for the key
DIRECTLY. `entitlement.company_entitled()` is the ONE authority and it
self-heals by re-validating the key saved in settings, which is exactly the bug
that took down the first live run. This checks whether that self-heal is enough
to make a headless bake-off possible.

Read-only: it authenticates and imports the transport, it sends nothing.
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3]))

from modules.ai_imaging.eagle_eye_lumbar import llm_backend

backend = llm_backend.resolve_backend()
print("backend:", backend)

denied = llm_backend.company_entitlement_error()
print("entitlement:", denied or "OK")
if denied:
    raise SystemExit("headless run not possible: " + denied)

module = llm_backend._backend_module(backend)
print("transport:", module.__name__, "->", hasattr(module, "EagleEyeImageAnalysis"))

from modules.EchoMind.viewer_chat.Manage import Manage  # noqa: E402
center, key = Manage.instance().get_center_and_gapgpt_key()
print("center:", center, "| key length:", len(str(key or "")))
print("READY")
