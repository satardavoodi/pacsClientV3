# Theme Color Reference

## Overview
AIPacs now includes a **comprehensive theme system** where every UI element can be themed. Each theme defines not just an accent color, but a complete, cohesive color palette for all use cases.

## How to Use Theme Colors in UI Code

### Getting the Current Theme

```python
from PacsClient.utils.theme_manager import get_theme_manager

theme_manager = get_theme_manager()
theme = theme_manager.current_theme()

# Access any theme color
accent_color = theme['accent']
success_color = theme['success']
danger_color = theme['danger']
```

### Available Theme Colors

#### Base Layout Colors
- `window_bg` — Main application background
- `window_alt_bg` — Alternative background (e.g., footer)
- `menu_bg` — Left/top menu background
- `menu_hover_bg` — Menu item on hover
- `menu_active_bg` — Active menu item background
- `panel_bg` — Settings/dialog panel background
- `panel_alt_bg` — Elevated panel background
- `panel_deep_bg` — Recessed panel background
- `card_bg` — Card/container background

#### Primary Accent
- `accent` — Main theme accent (e.g., buttons, highlights)
- `accent_secondary` — Secondary accent for variety
- `accent_hover` — Accent on hover
- `accent_pressed` — Accent when pressed
- `accent_soft` — Subtle accent (background)

#### Semantic Colors - Info
- `info` — Information messages (bright)
- `info_subtle` — Information background
- `info_hover` — Information on hover

#### Semantic Colors - Success
- `success` — Success messages, positive actions
- `success_subtle` — Success background
- `success_hover` — Success on hover

#### Semantic Colors - Warning
- `warning` — Warning messages, cautions
- `warning_subtle` — Warning background
- `warning_hover` — Warning on hover

#### Semantic Colors - Danger
- `danger` — Error/danger messages, destructive actions
- `danger_subtle` — Danger background
- `danger_hover` — Danger on hover

#### Badges & Tags
- `badge_blue` — Blue badge variant
- `badge_cyan` — Cyan badge variant

#### Status Indicators
- `status_online` — Online/active status
- `status_offline` — Offline/inactive status
- `status_busy` — Busy/unavailable status

#### Text
- `text_primary` — Main text color
- `text_secondary` — Secondary text (reduced emphasis)
- `text_muted` — Muted/disabled text
- `button_text` — Button text (auto-adjusts for contrast)

#### UI Elements
- `border` — Border color
- `tab_bg` — Tab bar background
- `tab_active_bg` — Active tab background
- `tab_hover_bg` — Tab on hover
- `neutral` — Neutral/gray color
- `shadow` — Shadow color (RGBA)

## Available Themes

### 1. Blue (Default)
**Accent:** `#3182ce`  
**Style:** Professional, calm, corporate  
**Best for:** Medical settings, professional environments

### 2. Gray
**Accent:** `#8b95a7`  
**Style:** Neutral, minimal, monochromatic  
**Best for:** DICOM-focused workflows, reduced visual noise

### 3. Green
**Accent:** `#2f9e70`  
**Style:** Natural, growth-oriented, eco-friendly  
**Best for:** Health metrics, positive feedback

### 4. Turquoise
**Accent:** `#20a4a5`  
**Style:** Modern, tech-forward, cool  
**Best for:** Contemporary interfaces, innovation

### 5. Dark Red ⭐ NEW
**Accent:** `#b63c57`  
**Style:** Bold, luxury, clinical precision  
**Best for:** High-stakes workflows, surgical planning, emergency contexts  
**Semantic Colors:** Reds and pinks throughout (success→magenta, danger→crimson)

### 6. Yellow ⭐ NEW
**Accent:** `#c99512`  
**Style:** Warm, premium, attention-grabbing  
**Best for:** Notifications, highlights, warm environments  
**Semantic Colors:** Golds and ambers throughout (success→light gold, warning→amber)

## Example: Styling a Button

### Before (Hardcoded)
```python
btn.setStyleSheet("background-color: #3182ce; color: white; border-radius: 8px;")
```

### After (Themed) ✅
```python
theme = get_theme_manager().current_theme()
btn.setStyleSheet(f"""
    QPushButton {{
        background-color: {theme['accent']};
        color: {theme['button_text']};
        border-radius: 8px;
    }}
    QPushButton:hover {{
        background-color: {theme['accent_hover']};
    }}
    QPushButton:pressed {{
        background-color: {theme['accent_pressed']};
    }}
""")
```

When the user changes to **Dark Red**, the button automatically becomes crimson.  
When they switch to **Yellow**, it becomes gold.  
No code changes needed!

## Example: Status Badge

```python
theme = get_theme_manager().current_theme()

if user_status == "online":
    badge_color = theme['status_online']
    bg_color = theme['success_subtle']
elif user_status == "busy":
    badge_color = theme['status_busy']
    bg_color = theme['warning_subtle']
else:
    badge_color = theme['status_offline']
    bg_color = theme['neutral']

badge.setStyleSheet(f"background-color: {bg_color}; color: {badge_color};")
```

## Theme Change Signal

To respond when the user changes themes:

```python
theme_manager = get_theme_manager()
theme_manager.themeChanged.connect(self.on_theme_changed)

def on_theme_changed(self, theme):
    # Reapply all stylesheets with new theme colors
    self.apply_theme_stylesheet(theme)
```

## Best Practices

1. **Always use `get_theme_manager().current_theme()`** instead of hardcoding colors
2. **Use semantic colors** (`success`, `danger`, `warning`) instead of inventing new colors
3. **Test across all themes** to ensure your UI looks good in every theme
4. **Use `button_text`** for automatic contrast adjustment on accent colors
5. **Connect to `themeChanged` signal** for dynamic theme updates
6. **Prefer subtle variants** (`success_subtle`, `warning_subtle`) for backgrounds
7. **Use hover/pressed variants** for interactive feedback

## Migration Guide

If you have hardcoded theme colors in existing code:

1. Import the theme manager
2. Replace hardcoded hex values with theme lookups
3. Test in all 6 themes (especially Dark Red and Yellow)
4. Connect to `themeChanged` if the component persists across theme changes

Example:

```python
# OLD (❌ Not themed)
self.search_btn.setStyleSheet("background-color: #10b981; color: white;")

# NEW (✅ Fully themed)
theme = get_theme_manager().current_theme()
self.search_btn.setStyleSheet(f"background-color: {theme['success']}; color: {theme['button_text']};")
```

## Theme Customization

Users can create custom themes via the Theme settings panel (left sidebar):

1. Click **Theme** in the left menu
2. Click **Customize...** in the Theme panel
3. Pick your own accent, window, menu, and panel colors
4. All other colors derive automatically from these 4 anchors

Developers don't need to do anything special—custom themes are fully supported by the theme blueprint system.

---

**Version:** 2.2.6+  
**Last Updated:** March 17, 2026
