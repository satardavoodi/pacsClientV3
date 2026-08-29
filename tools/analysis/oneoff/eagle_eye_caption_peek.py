"""One-off: print the axial captions a stage actually received.

Used to settle frame-numbering questions (is the caption index 0- or 1-based?)
against what the model's LEVEL MAP claims.
"""
import json
import sys

doc = json.loads(open(sys.argv[1], encoding="utf-8").read())
items = doc.get("sent", {}).get("images") or doc.get("sent", {}).get("items") or []
axial = [i for i in items if "xial" in str(i.get("caption", ""))]
print("axial captions:", len(axial))
for entry in axial[:3] + axial[-2:]:
    print(" ", entry.get("caption"))
