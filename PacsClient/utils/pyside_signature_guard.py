"""Narrow compatibility guard for the verified PySide6 6.10.2 import race.

Do not edit site-packages or change credential-provider selection. Install before
application workers start. Remove/review this adapter when changing PySide6.
It does not handle native wrapper faults or suppress application exceptions.
"""
import logging

_LOG = logging.getLogger(__name__)


def _install_mapping_guard(mapping, parser, version):
    """Keep the existing reloader owner and both cached entry points in sync."""
    if version != "6.10.2":
        return False
    original = mapping.update_mapping
    if getattr(original, "_aipacs_snapshot_guard", False):
        return True
    if (getattr(original, "__self__", None) is None
            or parser.update_mapping is not original
            or original.__func__ is not mapping.Reloader.update):
        return False  # An unknown binding must not be partially replaced.

    namespace = vars(mapping)
    registry_owner = namespace["sys"]

    def update_from_snapshot(owner):
        registry = registry_owner.modules
        if owner.sys_module_count == len(registry):
            return
        snapshot = registry.copy()
        owner.sys_module_count = len(snapshot)
        # Values must come from the same snapshot as the keys: failed imports
        # can remove their provisional entry while module_valid releases GIL.
        candidates = [(name, module) for name, module in snapshot.items()
                      if owner.module_valid(module)]
        for name, module in candidates:
            if registry.get(name) is not module:
                continue  # Do not resurrect an unloaded/replaced candidate.
            top = namespace.get("__import__", __import__)(name)
            namespace[top.__name__] = top
            initializer_name = "init_" + name.replace(".", "_")
            if initializer_name in namespace:
                initializer = namespace.pop(initializer_name)
                namespace.update(initializer())
            if name.startswith("PySide6."):
                namespace["pyside_modules"].add(name)

    update_from_snapshot._aipacs_snapshot_guard = True
    replacement = update_from_snapshot.__get__(original.__self__, mapping.Reloader)
    mapping.Reloader.update = update_from_snapshot
    mapping.update_mapping = replacement
    parser.update_mapping = replacement
    return True


def install_pyside_signature_guard():
    """Apply only to the reviewed version; source and frozen use the same path."""
    import PySide6
    if PySide6.__version__ != "6.10.2":
        _LOG.warning("[QT_SIGNATURE_GUARD] unreviewed version=%s; adapter not applied",
                     PySide6.__version__)
        return False
    from PySide6.support.signature import mapping, parser

    installed = _install_mapping_guard(mapping, parser, PySide6.__version__)
    if installed:
        _LOG.info("[QT_SIGNATURE_GUARD] snapshot adapter active version=%s", PySide6.__version__)
    else:
        _LOG.warning("[QT_SIGNATURE_GUARD] adapter not applied; review required version=%s",
                     PySide6.__version__)
    return installed
