"""Helpers for opening singleton module tabs (web browser, education, printing, etc.).

Centralises the repeated "find-or-create tab" pattern that was duplicated
across multiple ``open_*`` methods in HomePanelWidget.

v2.2.8 architecture refactor.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Callable, Optional

from PySide6.QtWidgets import QTabWidget, QWidget

if TYPE_CHECKING:
    from PacsClient.pacs.patient_tab.ui.patient_ui.custom_tab_manager import CustomTabManager


def find_existing_module_tab(
    tab_widget: QTabWidget,
    custom_tab_manager: Optional["CustomTabManager"],
    tab_flag_key: str,
) -> Optional[int]:
    """Return the index of an existing module tab identified by *tab_flag_key*, or ``None``.

    *tab_flag_key* is the key stored in ``custom_tab_manager.patient_tabs``
    (e.g. ``'is_education_tab'``, ``'is_printing_tab'``).
    """
    if custom_tab_manager is None:
        return None
    for i in range(tab_widget.count()):
        tab_data = custom_tab_manager.patient_tabs.get(i, {})
        if tab_data.get(tab_flag_key, False):
            return i
    return None


def activate_or_create_module_tab(
    tab_widget: QTabWidget,
    custom_tab_manager: Optional["CustomTabManager"],
    tab_flag_key: str,
    widget_factory: Callable[[], QWidget],
    add_tab_method_name: str,
    fallback_label: str,
) -> QWidget:
    """Activate an existing module tab or create a new one.

    Parameters
    ----------
    tab_widget:
        The main ``QTabWidget`` hosting all tabs.
    custom_tab_manager:
        Optional ``CustomTabManager`` for themed tab headers.
    tab_flag_key:
        Key used by ``custom_tab_manager`` to track this tab type.
    widget_factory:
        Zero-arg callable that creates and returns the module widget.
    add_tab_method_name:
        Name of the method on *custom_tab_manager* to call when adding
        the tab (e.g. ``'add_web_browser_tab'``).
    fallback_label:
        Tab label used when ``custom_tab_manager`` is not available.

    Returns
    -------
    QWidget
        The module widget (new or existing).
    """
    existing_idx = find_existing_module_tab(tab_widget, custom_tab_manager, tab_flag_key)
    if existing_idx is not None:
        tab_widget.setCurrentIndex(existing_idx)
        if custom_tab_manager:
            tab_data = custom_tab_manager.patient_tabs.get(existing_idx, {})
            return tab_data.get('widget', tab_widget.widget(existing_idx))
        return tab_widget.widget(existing_idx)

    widget = widget_factory()

    if custom_tab_manager and hasattr(custom_tab_manager, add_tab_method_name):
        adder = getattr(custom_tab_manager, add_tab_method_name)
        adder(widget=widget)
    else:
        tab_widget.addTab(widget, fallback_label)
        tab_widget.setCurrentWidget(widget)

    return widget
