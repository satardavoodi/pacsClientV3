"""
patient_widget.py — backward-compatible shim (v2.2.9.1)

The PatientWidget class has been split into focused mixin files inside
``patient_widget_core/``.  This shim re-exports the public API so that
every existing ``from ...patient_widget import PatientWidget`` keeps working.

See patient_widget_core/README.md for the file map.
"""

# Re-export the assembled PatientWidget class
from PacsClient.pacs.patient_tab.ui.patient_ui.patient_widget_core.widget import (  # noqa: F401
    PatientWidget,
    # Module-level helpers used by other modules
    _pw_theme_color_map,
    _pw_retint_stylesheet,
    _pw_retint_widget_tree,
    GRID_CONFIG_PATH,
    PRIORITY_MANAGER_AVAILABLE,
    logger,
)

__all__ = [
    "PatientWidget",
    "_pw_theme_color_map",
    "_pw_retint_stylesheet",
    "_pw_retint_widget_tree",
    "GRID_CONFIG_PATH",
    "PRIORITY_MANAGER_AVAILABLE",
]
