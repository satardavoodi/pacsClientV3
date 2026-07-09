# -*- coding: utf-8 -*-
"""
Model Training Tab — Main training interface with embedded settings tabs.

Integrates BoneAge (EVA-02 ViT) and Mammography (FCOS + XGBoost) training
through a unified tabbed interface.
"""

import os
import logging
from typing import Optional

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QStackedWidget, QFrame, QSizePolicy
)

from .abstract_tab import AbstractTab
from .training_data_settings_tab import TrainingDataSettingsTab

logger = logging.getLogger(__name__)


class ModelTrainingTab(AbstractTab):
    """
    Model Training tab — provides access to training configuration for both
    BoneAge and Mammography backends with separate settings tabs.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self):
        """Build the main training tab UI."""
        center = self.get_center_layout_vertical()

        # ── Training Data Settings (tabbed: BoneAge + Mammography) ──
        self._settings_widget = TrainingDataSettingsTab()
        self._settings_widget.training_requested.connect(self._on_training_requested)
        center.addWidget(self._settings_widget)

    def _on_training_requested(self, settings: dict):
        """Handle training request from settings widget."""
        logger.info(f"[ModelTrainingTab] Training requested: backend={settings.get('backend')}")

    def get_settings(self) -> dict:
        """Return all training settings."""
        return self._settings_widget.get_all_settings()
