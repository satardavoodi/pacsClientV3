def get_roboto_font_family(weight='regular'):
    """
    Get the appropriate font-family CSS declaration for Roboto fonts
    
    Args:
        weight (str): Font weight - 'thin', 'light', 'regular', 'medium', 'bold', 'black'
    
    Returns:
        str: CSS font-family declaration
    """
    
    font_mapping = {
        'thin': "'Roboto-Thin', 'Roboto', sans-serif",
        'light': "'Roboto-Light', 'Roboto', sans-serif", 
        'regular': "'Roboto-Regular', 'Roboto', sans-serif",
        'medium': "'Roboto-Medium', 'Roboto', sans-serif",
        'bold': "'Roboto-Bold', 'Roboto', sans-serif",
        'black': "'Roboto-Black', 'Roboto', sans-serif",
        'condensed': "'Roboto-Condensed', 'Roboto', sans-serif",
        'boldcondensed': "'Roboto-BoldCondensed', 'Roboto', sans-serif"
    }
    
    return font_mapping.get(weight.lower(), "'Roboto-Regular', 'Roboto', sans-serif")


def get_roboto_css_style(weight='regular', size=12, color='#000000'):
    """
    Get a complete CSS style string for Roboto fonts
    
    Args:
        weight (str): Font weight
        size (int): Font size in pixels
        color (str): Font color (hex or CSS color)
    
    Returns:
        str: Complete CSS style string
    """
    font_family = get_roboto_font_family(weight)
    return f"font-family: {font_family}; font-size: {size}px; color: {color};"


def get_roboto_button_style(weight='medium', size=11, color='#ffffff', bg_color='#16a085'):
    """
    Get CSS style for Roboto buttons
    
    Args:
        weight (str): Font weight
        size (int): Font size
        color (str): Text color
        bg_color (str): Background color
    
    Returns:
        str: Complete button CSS style
    """
    font_family = get_roboto_font_family(weight)
    return f"""
        QPushButton {{
            background: {bg_color};
            color: {color};
            border: 1px solid {bg_color};
            border-radius: 0px;
            padding: 6px 12px;
            font-size: {size}px;
            font-weight: 600;
            font-family: {font_family};
            margin: 2px 0px;
        }}
        QPushButton:hover {{
            background: {bg_color}dd;
            border-color: {bg_color}dd;
        }}
    """


def get_roboto_label_style(weight='regular', size=10, color='#e2e8f0'):
    """
    Get CSS style for Roboto labels
    
    Args:
        weight (str): Font weight
        size (int): Font size
        color (str): Text color
    
    Returns:
        str: Complete label CSS style
    """
    font_family = get_roboto_font_family(weight)
    return f"""
        QLabel {{
            font-size: {size}px;
            font-family: {font_family};
            color: {color};
        }}
    """


def get_roboto_input_style(weight='regular', size=10, color='#f7fafc'):
    """
    Get CSS style for Roboto input fields
    
    Args:
        weight (str): Font weight
        size (int): Font size
        color (str): Text color
    
    Returns:
        str: Complete input CSS style
    """
    font_family = get_roboto_font_family(weight)
    return f"""
        QLineEdit {{
            background: #1a202c;
            border: 1px solid #4a5568;
            border-radius: 0px;
            padding: 4px 8px;
            font-size: {size}px;
            font-family: {font_family};
            color: {color};
        }}
        QLineEdit:focus {{
            border-color: #3182ce;
            background: #2d3748;
        }}
    """


def get_high_quality_font_css(weight='regular', size=12, color='#000000'):
    """
    Get high-quality CSS for fonts with proper anti-aliasing
    
    Args:
        weight (str): Font weight
        size (int): Font size in pixels
        color (str): Font color
    
    Returns:
        str: High-quality CSS style
    """
    font_family = get_roboto_font_family(weight)
    return f"font-family: {font_family}; font-size: {size}px; color: {color}; font-weight: normal; font-style: normal;"


def get_global_font_smoothing_css():
    """
    Get global CSS for font smoothing across the application
    
    Returns:
        str: Global font smoothing CSS
    """
    return """
        QWidget {
            font-family: 'Roboto-Regular', 'Roboto', sans-serif;
        }
        
        QLabel, QPushButton, QLineEdit, QTextEdit, QPlainTextEdit {
            font-family: 'Roboto-Regular', 'Roboto', sans-serif;
        }
    """
