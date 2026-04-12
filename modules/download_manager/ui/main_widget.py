"""
Download Manager Widget - backward-compatible shim.

Original 5,534-line file split into focused mixins in widget/ subfolder.
See widget/README.md for the file map.

All public names re-exported for backward compatibility:
    from modules.download_manager.ui.main_widget import DownloadManagerWidget
"""
from modules.download_manager.ui.widget.widget import (
    DownloadManagerWidget,
    _dm_theme_color_map,
    _dm_retint_stylesheet,
    _dm_retint_widget_tree,
    logger,
)

__all__ = [
    "DownloadManagerWidget",
    "_dm_theme_color_map",
    "_dm_retint_stylesheet",
    "_dm_retint_widget_tree",
]
