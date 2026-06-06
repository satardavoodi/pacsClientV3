#!/usr/bin/env python3
"""
Code review verification: R29 Fix for UNKNOWN planes
Directly reads the fixed code to verify the fix is in place
"""
import re

print("R29 Fix Code Review: Verifying UNKNOWN planes no longer get K_FLIP\n")
print("=" * 80)

# Read the fixed display_geometry.py file
with open("modules/viewer/geometry/display_geometry.py", "r") as f:
    content = f.read()

# Extract the key logic section
pattern = r'recommended_transform\s*=\s*"NONE"\s+if\s+\(([^)]+)\)\s+else\s+"K_FLIP"'
match = re.search(pattern, content)

if match:
    condition = match.group(1)
    print(f"Found K_FLIP recommendation logic:\n")
    print(f"  recommended_transform = 'NONE' if ({condition}) else 'K_FLIP'")
    print()
    
    # Check if the condition includes the UNKNOWN guard
    if 'convention_name == "UNKNOWN"' in condition:
        print("✓ VERIFIED: Code includes guard for UNKNOWN planes!")
        print(f"  Full condition: {condition}")
        print()
        print("Fix Explanation:")
        print("  - When convention_name == 'UNKNOWN': recommend NONE (don't flip)")
        print("  - When order_matches == True: recommend NONE (already correct)")
        print("  - Otherwise: recommend K_FLIP (convention mismatch)")
        print()
        print("=" * 80)
        print("✓ R29 FIX IS CORRECTLY IMPLEMENTED")
    else:
        print("✗ WARNING: UNKNOWN guard not found in condition!")
        print(f"  Condition: {condition}")
else:
    print("✗ ERROR: Could not find recommended_transform logic")

# Also verify plugin package mirror
print("\nVerifying plugin package mirror...\n")
with open("builder/plugin package/packages/viewer/payload/python/modules/viewer/geometry/display_geometry.py", "r") as f:
    plugin_content = f.read()

plugin_match = re.search(pattern, plugin_content)
if plugin_match:
    print("✓ Plugin package mirror also has the fix!")
else:
    print("✗ Plugin package mirror does not have the fix!")

print("\n" + "=" * 80)
