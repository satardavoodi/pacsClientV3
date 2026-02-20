def get_scroll_area_style() -> str:
    return """
        QScrollArea {
            border: none;
            background: transparent;
        }
        QScrollBar:vertical {
            border: 1px solid #4b5563;
            background: #1f2937;
            width: 12px;
            margin: 12px 0px 12px 0px;
            border-radius: 6px;
        }
        QScrollBar::handle:vertical {
            background: #374151;
            min-height: 40px;
            border-radius: 5px;
        }
        QScrollBar::handle:vertical:hover {
            background: #4b5563;
        }
        QScrollBar::add-line:vertical,
        QScrollBar::sub-line:vertical {
            height: 12px;
            width: 12px;
            background: transparent;
            border: none;
            subcontrol-origin: margin;
        }
        QScrollBar::add-page:vertical,
        QScrollBar::sub-page:vertical {
            background: none;
        }
        QScrollBar::up-arrow:vertical,
        QScrollBar::down-arrow:vertical {
            width: 0px;
            height: 0px;
        }
    """
