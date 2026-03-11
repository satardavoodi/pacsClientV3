import os
import sys
from pathlib import Path
from PySide6.QtGui import QFontDatabase, QFont, QFontInfo
from PySide6.QtCore import QDir, Qt
from PySide6.QtWidgets import QApplication, QWidget


class FontManager:
    """Manages loading and registration of custom fonts including Roboto and IranYekan"""  
    
    def __init__(self):
        self.fonts_loaded = False
        self.iranyekan_loaded = False
        self.font_ids = {}
        
    def load_iranyekan_fonts(self):
        """Load all IranYekan font variants from the Fonts/iranyekan folder"""
        if self.iranyekan_loaded:
            return True
            
        try:
            from _project_root import PROJECT_ROOT
            base_path = PROJECT_ROOT
            
            iranyekan_dir = base_path / "Fonts" / "iranyekan"
            
            if not iranyekan_dir.exists():
                print(f"IranYekan fonts directory not found: {iranyekan_dir}")
                return False
            
            # IranYekan font file mappings (TTF files)
            iranyekan_files = {
                'IRANYekan-Regular': 'iranyekanwebregular.ttf',
                'IRANYekan-Bold': 'iranyekanwebbold.ttf',
                'IRANYekan-Light': 'iranyekanweblight.ttf',
                'IRANYekan-Regular-FaNum': 'iranyekanwebregular(fanum).ttf',
                'IRANYekan-Bold-FaNum': 'iranyekanwebbold(fanum).ttf',
                'IRANYekan-Light-FaNum': 'iranyekanweblight(fanum).ttf',
            }
            
            # Load each font file
            loaded_count = 0
            for font_name, font_file in iranyekan_files.items():
                font_path = iranyekan_dir / font_file
                if font_path.exists():
                    font_id = QFontDatabase.addApplicationFont(str(font_path))
                    if font_id != -1:
                        self.font_ids[font_name] = font_id
                        loaded_count += 1
                    else:
                        print(f"Failed to load IranYekan font: {font_path}")
                else:
                    print(f"IranYekan font file not found: {font_path}")
            
            self.iranyekan_loaded = loaded_count > 0
            print(f"Loaded {loaded_count} IranYekan font variants")
            return self.iranyekan_loaded
            
        except Exception as e:
            print(f"Error loading IranYekan fonts: {str(e)}")
            return False
    
    def load_all_fonts(self):
        """Load all available fonts (Roboto and IranYekan)"""
        roboto_ok = self.load_roboto_fonts()
        iranyekan_ok = self.load_iranyekan_fonts()
        return roboto_ok or iranyekan_ok
        
    def load_roboto_fonts(self):
        """Load all Roboto font variants from the Fonts folder"""
        if self.fonts_loaded:
            return True
            
        try:
            from _project_root import PROJECT_ROOT
            base_path = PROJECT_ROOT
            fonts_dir = base_path / "Fonts"
            
            if not fonts_dir.exists():
                print(f"Fonts directory not found: {fonts_dir}")
                return False
                
            # Font file mappings
            font_files = {
                'Roboto-Thin': 'Roboto-Thin.ttf',
                'Roboto-ThinItalic': 'Roboto-ThinItalic.ttf',
                'Roboto-Light': 'Roboto-Light.ttf',
                'Roboto-LightItalic': 'Roboto-LightItalic.ttf',
                'Roboto-Regular': 'Roboto-Regular.ttf',
                'Roboto-Italic': 'Roboto-Italic.ttf',
                'Roboto-Medium': 'Roboto-Medium.ttf',
                'Roboto-MediumItalic': 'Roboto-MediumItalic.ttf',
                'Roboto-Bold': 'Roboto-Bold.ttf',
                'Roboto-BoldItalic': 'Roboto-BoldItalic.ttf',
                'Roboto-Black': 'Roboto-Black.ttf',
                'Roboto-BlackItalic': 'Roboto-BlackItalic.ttf',
                'Roboto-Condensed': 'Roboto-Condensed.ttf',
                'Roboto-CondensedItalic': 'Roboto-CondensedItalic.ttf',
                'Roboto-BoldCondensed': 'Roboto-BoldCondensed.ttf',
                'Roboto-BoldCondensedItalic': 'Roboto-BoldCondensedItalic.ttf'
            }
            
            # Load each font file
            for font_name, font_file in font_files.items():
                font_path = fonts_dir / font_file
                if font_path.exists():
                    font_id = QFontDatabase.addApplicationFont(str(font_path))
                    if font_id != -1:
                        self.font_ids[font_name] = font_id
                    else:
                        print(f"Font file not found: {font_path}")
            
            self.fonts_loaded = True
            return True
            
        except Exception as e:
            print(f"Error loading fonts: {str(e)}")
            return False
    
    def get_font(self, font_name, size=12, weight=QFont.Normal, italic=False):
        """Get a QFont object with the specified font (Roboto or IranYekan)"""
        # Load all fonts if not loaded
        if not self.fonts_loaded:
            self.load_roboto_fonts()
        if not self.iranyekan_loaded:
            self.load_iranyekan_fonts()
        
        # Map common font names to actual variants
        font_mapping = {
            # Roboto mappings
            'Roboto': 'Roboto-Regular',
            'Roboto-Bold': 'Roboto-Bold',
            'Roboto-Medium': 'Roboto-Medium',
            'Roboto-Light': 'Roboto-Light',
            'Roboto-Thin': 'Roboto-Thin',
            'Roboto-Black': 'Roboto-Black',
            'Roboto-Condensed': 'Roboto-Condensed',
            'Roboto-BoldCondensed': 'Roboto-BoldCondensed',
            # IranYekan mappings
            'IRANYekan': 'IRANYekan-Regular',
            'IranYekan': 'IRANYekan-Regular',
            'iranyekan': 'IRANYekan-Regular',
            'IRANYekan-FaNum': 'IRANYekan-Regular-FaNum',
        }
        
        # Use mapped name or original name
        actual_font_name = font_mapping.get(font_name, font_name)
        
        # Check if font is loaded
        if actual_font_name in self.font_ids:
            font = QFont(actual_font_name, size, weight)
            font.setItalic(italic)
            
            # Enable anti-aliasing and font smoothing
            font.setStyleStrategy(QFont.PreferAntialias)
            font.setHintingPreference(QFont.PreferFullHinting)
            
            # Set pixel size for better rendering
            font.setPixelSize(size)
            
            return font
        else:
            # Fallback to system font
            print(f"Font {actual_font_name} not found, using system font")
            font = QFont(font_name, size, weight)
            font.setItalic(italic)
            font.setStyleStrategy(QFont.PreferAntialias)
            font.setHintingPreference(QFont.PreferFullHinting)
            font.setPixelSize(size)
            return font
    
    def get_iranyekan_font(self, weight='regular', size=12, use_persian_numerals=False):
        """
        Get an IranYekan font with specified parameters.
        
        Args:
            weight: 'light', 'regular', or 'bold'
            size: Font size in pixels
            use_persian_numerals: If True, use FaNum variant with Persian numbers
        
        Returns:
            QFont: Configured IranYekan font
        """
        if not self.iranyekan_loaded:
            self.load_iranyekan_fonts()
        
        # Build font name
        weight_map = {
            'light': 'Light',
            'regular': 'Regular',
            'bold': 'Bold'
        }
        weight_suffix = weight_map.get(weight.lower(), 'Regular')
        fanum_suffix = '-FaNum' if use_persian_numerals else ''
        font_name = f'IRANYekan-{weight_suffix}{fanum_suffix}'
        
        return self.get_font(font_name, size)
    
    def get_available_fonts(self):
        """Get list of all available fonts (Roboto and IranYekan)"""
        if not self.fonts_loaded:
            self.load_roboto_fonts()
        if not self.iranyekan_loaded:
            self.load_iranyekan_fonts()
        return list(self.font_ids.keys())
    
    def get_available_iranyekan_fonts(self):
        """Get list of available IranYekan fonts"""
        if not self.iranyekan_loaded:
            self.load_iranyekan_fonts()
        return [name for name in self.font_ids.keys() if 'IRANYekan' in name]


# Global font manager instance
font_manager = FontManager()


def load_fonts():
    """Load all Roboto fonts"""
    return font_manager.load_roboto_fonts()


def get_roboto_font(font_name='Roboto-Regular', size=12, weight=QFont.Normal, italic=False):
    """Get a Roboto font with specified parameters"""
    return font_manager.get_font(font_name, size, weight, italic)


def get_available_roboto_fonts():
    """Get list of available Roboto fonts"""
    return font_manager.get_available_fonts()


def load_iranyekan_fonts():
    """Load all IranYekan fonts"""
    return font_manager.load_iranyekan_fonts()


def get_iranyekan_font(weight='regular', size=12, use_persian_numerals=False):
    """
    Get an IranYekan font with specified parameters.
    
    Args:
        weight: 'light', 'regular', or 'bold'
        size: Font size in pixels
        use_persian_numerals: If True, use FaNum variant with Persian numbers
    
    Returns:
        QFont: Configured IranYekan font
    """
    return font_manager.get_iranyekan_font(weight, size, use_persian_numerals)


def get_available_iranyekan_fonts():
    """Get list of available IranYekan fonts"""
    return font_manager.get_available_iranyekan_fonts()


def load_all_fonts():
    """Load all available fonts (Roboto and IranYekan)"""
    return font_manager.load_all_fonts()


def setup_font_rendering():
    """Setup global font rendering settings for better quality"""
    try:
        # Get the application instance
        app = QApplication.instance()
        if app is None:
            return False
        
        # Set global font rendering attributes
        # Note: AA_EnableHighDpiScaling is deprecated in Qt6/PySide6 (enabled by default)
        # Only set AA_UseHighDpiPixmaps for better pixmap scaling
        try:
            app.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
        except AttributeError:
            # Attribute may not exist in all Qt versions
            pass
        
        return True
        
    except Exception:
        # Silently fail - font rendering will use defaults
        return False


def apply_font_smoothing_to_widget(widget):
    """Apply font smoothing to a specific widget using Qt-compatible methods"""
    try:
        # Apply anti-aliasing through font settings instead of CSS
        font = widget.font()
        font.setStyleStrategy(QFont.PreferAntialias)
        font.setHintingPreference(QFont.PreferFullHinting)
        widget.setFont(font)
        return True
    except Exception as e:
        print(f"Error applying font smoothing to widget: {str(e)}")
        return False


def apply_anti_aliasing_to_all_widgets(parent_widget):
    """Apply anti-aliasing to all child widgets recursively"""
    try:
        # Apply to the parent widget itself
        apply_font_smoothing_to_widget(parent_widget)
        
        # Apply to all child widgets
        for child in parent_widget.findChildren(QWidget):
            apply_font_smoothing_to_widget(child)
        
        return True
    except Exception as e:
        print(f"Error applying anti-aliasing to widgets: {str(e)}")
        return False


def get_qt_compatible_font_css(weight='regular', size=12, color='#000000'):
    """
    Get Qt-compatible CSS for fonts without unsupported properties
    
    Args:
        weight (str): Font weight
        size (int): Font size in pixels
        color (str): Font color
    
    Returns:
        str: Qt-compatible CSS style
    """
    # Import here to avoid circular import
    from PacsClient.utils.css_utils import get_roboto_font_family
    font_family = get_roboto_font_family(weight)
    return f"font-family: {font_family}; font-size: {size}px; color: {color};"


def create_roboto_qfont(weight='regular', size=12):
    """
    Create a QFont object with proper anti-aliasing settings
    
    Args:
        weight (str): Font weight (regular, medium, bold, etc.)
        size (int): Font size
    
    Returns:
        QFont: Configured QFont object with anti-aliasing
    """
    # Map weight names to font names
    weight_map = {
        'thin': 'Roboto-Thin',
        'light': 'Roboto-Light', 
        'regular': 'Roboto-Regular',
        'medium': 'Roboto-Medium',
        'bold': 'Roboto-Bold',
        'black': 'Roboto-Black'
    }
    
    font_name = weight_map.get(weight.lower(), 'Roboto-Regular')
    
    # Create font with anti-aliasing
    font = QFont(font_name, size)
    font.setStyleStrategy(QFont.PreferAntialias)
    font.setHintingPreference(QFont.PreferFullHinting)
    font.setPixelSize(size)
    
    return font


def apply_anti_aliasing_to_widget(widget):
    """
    Apply anti-aliasing to a single widget
    
    Args:
        widget: QWidget to apply anti-aliasing to
    """
    try:
        apply_font_smoothing_to_widget(widget)
        return True
    except Exception as e:
        print(f"Error applying anti-aliasing to widget: {str(e)}")
        return False


def apply_anti_aliasing_to_table(table_widget):
    """
    Apply anti-aliasing to table headers and all items
    
    Args:
        table_widget: QTableWidget to apply anti-aliasing to
    """
    try:
        # Apply to table widget itself
        apply_font_smoothing_to_widget(table_widget)
        
        # Apply to headers
        if table_widget.horizontalHeader():
            apply_font_smoothing_to_widget(table_widget.horizontalHeader())
        if table_widget.verticalHeader():
            apply_font_smoothing_to_widget(table_widget.verticalHeader())
            
        # Apply to all existing items
        for row in range(table_widget.rowCount()):
            for col in range(table_widget.columnCount()):
                item = table_widget.item(row, col)
                if item:
                    font = item.font()
                    font.setStyleStrategy(QFont.PreferAntialias)
                    font.setHintingPreference(QFont.PreferFullHinting)
                    item.setFont(font)
                    
        return True
    except Exception as e:
        print(f"Error applying anti-aliasing to table: {str(e)}")
        return False
