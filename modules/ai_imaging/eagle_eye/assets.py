"""Eagle Eye asset ownership; shared Slicer remains an Advanced MPR service."""
from pathlib import Path

FEATURE_ASSETS = {
    'breast': 'eagle_eye/breast',
    'bone_age': 'eagle_eye/bone-age',
    'total_spine': 'eagle_eye/total-spine',
    'alignment': 'eagle_eye/alignment',
    'brain': 'eagle_eye/brain',
    'brain_lesions': 'eagle_eye/brain-lesions',
    # Preserve the deployed lumbar path for existing installations.
    'lumbar': 'offline_lumbar',
}


def installed_feature_roots(feature):
    from aipacs_runtime import modules_runtime_search_roots, bundled_module_packages_search_roots
    relative = FEATURE_ASSETS[feature]
    roots = [root / 'advanced_mpr' / relative for root in modules_runtime_search_roots()]
    roots.extend(root / 'advanced_mpr/payload' / relative for root in bundled_module_packages_search_roots())
    return list(dict.fromkeys(Path(root) for root in roots))
