"""Eagle Eye asset ownership; shared Slicer remains an Advanced MPR service."""
from pathlib import Path

FEATURE_ASSETS = {
    'brain': 'eagle_eye/brain',
    # Preserve the deployed lumbar path for existing installations.
    'lumbar': 'offline_lumbar',
}


def installed_feature_roots(feature):
    from aipacs_runtime import modules_runtime_search_roots, bundled_module_packages_search_roots
    relative = FEATURE_ASSETS[feature]
    roots = [root / 'advanced_mpr' / relative for root in modules_runtime_search_roots()]
    roots.extend(root / 'advanced_mpr/payload' / relative for root in bundled_module_packages_search_roots())
    return list(dict.fromkeys(Path(root) for root in roots))
