#!/usr/bin/env python3
"""
NewMPR2Slicer Post-Generation Customization Script

This script applies NewMPR2 branding customizations to a newly generated
SlicerCustomAppTemplate project in an idempotent manner (safe to run multiple times).

Usage:
    python customize_slicer_app.py

The script expects the NewMPR2Slicer project to be located at:
    slicer_custom_app/NewMPR2Slicer/

It will:
1. Verify the project structure exists
2. Copy branding resources (stylesheet, icons, colors)
3. Update CMakeLists.txt with NewMPR2 branding
4. Modify Main.cxx to load stylesheet and set app identity
5. Update main window for custom title and menus
6. Update Qt resource files (.qrc) to include branding assets

Run this script AFTER generating with cookiecutter and BEFORE building.
"""

import os
import sys
import re
import shutil
from pathlib import Path
from datetime import datetime

# ============================================================
# Configuration
# ============================================================
APP_NAME = "NewMPR2Slicer"
APP_TITLE = "Ai-Pacs – NewMPR2 Advanced Viewer"
ORGANIZATION_NAME = "Ai-Pacs"
ORGANIZATION_DOMAIN = "aipacs.com"
APP_VERSION = "1.0.0"

# Marker to identify our customizations (for idempotency)
CUSTOMIZATION_MARKER = "// [NewMPR2 Customization]"
CMAKE_MARKER = "# [NewMPR2 Customization]"


def get_script_dir() -> Path:
    """Get the directory containing this script."""
    return Path(__file__).parent.resolve()


def log_info(msg: str):
    """Print info message."""
    print(f"  ✓ {msg}")


def log_warn(msg: str):
    """Print warning message."""
    print(f"  ⚠ {msg}")


def log_error(msg: str):
    """Print error message."""
    print(f"  ✗ {msg}")


def log_skip(msg: str):
    """Print skip message."""
    print(f"  → {msg}")


def find_slicer_project(base_dir: Path) -> Path:
    """Find the NewMPR2Slicer project directory."""
    expected_path = base_dir / "NewMPR2Slicer"
    
    if expected_path.exists() and expected_path.is_dir():
        # Verify it looks like a Slicer project
        if (expected_path / "CMakeLists.txt").exists():
            return expected_path
    
    # Try to find any Slicer project directory
    for item in base_dir.iterdir():
        if item.is_dir() and (item / "CMakeLists.txt").exists():
            apps_dir = item / "Applications"
            if apps_dir.exists():
                return item
    
    return None


def find_app_directory(slicer_project_path: Path) -> Path:
    """Find the Applications/<AppName>App directory."""
    apps_dir = slicer_project_path / "Applications"
    if not apps_dir.exists():
        return None
    
    # Look for the app directory
    for item in apps_dir.iterdir():
        if item.is_dir() and item.name.endswith("App"):
            return item
    
    return None


def ensure_directory(path: Path) -> bool:
    """Ensure a directory exists, create if needed."""
    if not path.exists():
        path.mkdir(parents=True, exist_ok=True)
        log_info(f"Created directory: {path.name}")
        return True
    return False


def copy_branding_resources(script_dir: Path, slicer_project_path: Path, app_dir: Path) -> bool:
    """Copy branding resources to the Slicer project."""
    branding_dir = script_dir / "branding"
    
    if not branding_dir.exists():
        log_warn(f"Branding directory not found: {branding_dir}")
        return False
    
    success = True
    
    # Create destination directories
    resources_dir = app_dir / "Resources"
    stylesheets_dir = resources_dir / "Stylesheets"
    icons_dir = resources_dir / "Icons"
    utilities_dir = slicer_project_path / "Utilities" / "Branding"
    
    ensure_directory(stylesheets_dir)
    ensure_directory(icons_dir)
    ensure_directory(utilities_dir)
    
    # Copy stylesheet
    qss_src = branding_dir / "NewMPR2Slicer.qss"
    if qss_src.exists():
        qss_dst = stylesheets_dir / "NewMPR2Slicer.qss"
        shutil.copy(qss_src, qss_dst)
        shutil.copy(qss_src, utilities_dir / "NewMPR2Slicer.qss")
        log_info(f"Copied stylesheet: {qss_dst.relative_to(slicer_project_path)}")
    else:
        log_warn("Stylesheet not found: branding/NewMPR2Slicer.qss")
        success = False
    
    # Copy colors.json
    colors_src = branding_dir / "colors.json"
    if colors_src.exists():
        shutil.copy(colors_src, utilities_dir / "colors.json")
        log_info("Copied colors.json")
    
    # Copy icons if they exist (not just README)
    icons_src = branding_dir / "icons"
    if icons_src.exists():
        icon_files = [f for f in icons_src.glob("*") 
                      if f.is_file() and f.suffix.lower() in (".png", ".ico", ".svg")]
        if icon_files:
            for icon_file in icon_files:
                shutil.copy(icon_file, icons_dir / icon_file.name)
            log_info(f"Copied {len(icon_files)} icon file(s)")
        else:
            log_skip("No icon files found (only placeholders exist)")
    
    return success


def update_root_cmakelists(slicer_project_path: Path) -> bool:
    """Update root CMakeLists.txt with branding information."""
    cmake_file = slicer_project_path / "CMakeLists.txt"
    
    if not cmake_file.exists():
        log_error(f"CMakeLists.txt not found: {cmake_file}")
        return False
    
    content = cmake_file.read_text(encoding='utf-8')
    
    # Check if already customized
    if CMAKE_MARKER in content:
        log_skip("CMakeLists.txt already customized")
        return True
    
    # Build customization block
    customization_block = f'''
{CMAKE_MARKER}
# NewMPR2 Branding Configuration
set(APPLICATION_NAME "{APP_NAME}" CACHE STRING "Application name" FORCE)
set(APPLICATION_TITLE "{APP_TITLE}" CACHE STRING "Application display title" FORCE)
set(ORGANIZATION_NAME "{ORGANIZATION_NAME}" CACHE STRING "Organization name" FORCE)
set(ORGANIZATION_DOMAIN "{ORGANIZATION_DOMAIN}" CACHE STRING "Organization domain" FORCE)
# [End NewMPR2 Customization]
'''
    
    # Find a good insertion point (after project() command)
    project_match = re.search(r'project\s*\([^)]+\)', content, re.IGNORECASE)
    if project_match:
        insert_pos = project_match.end()
        new_content = content[:insert_pos] + "\n" + customization_block + content[insert_pos:]
        cmake_file.write_text(new_content, encoding='utf-8')
        log_info("Updated CMakeLists.txt with branding configuration")
        return True
    else:
        # Append to end if no project() found
        content += "\n" + customization_block
        cmake_file.write_text(content, encoding='utf-8')
        log_info("Appended branding configuration to CMakeLists.txt")
        return True


def update_main_cxx(app_dir: Path) -> bool:
    """Update Main.cxx with branding code."""
    main_file = app_dir / "Main.cxx"
    
    if not main_file.exists():
        log_warn(f"Main.cxx not found: {main_file}")
        return False
    
    content = main_file.read_text(encoding='utf-8')
    
    # Check if already customized
    if CUSTOMIZATION_MARKER in content:
        log_skip("Main.cxx already customized")
        return True
    
    # Add necessary includes
    include_block = f'''
{CUSTOMIZATION_MARKER} - Includes
#include <QFile>
#include <QIcon>
#include <QTextStream>
// [End NewMPR2 Includes]
'''
    
    # Branding code to add after QApplication creation
    branding_code = f'''
  {CUSTOMIZATION_MARKER} - Application Identity
  QCoreApplication::setApplicationName("{APP_NAME}");
  QCoreApplication::setApplicationDisplayName("{APP_TITLE}");
  QCoreApplication::setOrganizationName("{ORGANIZATION_NAME}");
  QCoreApplication::setOrganizationDomain("{ORGANIZATION_DOMAIN}");
  QCoreApplication::setApplicationVersion("{APP_VERSION}");
  
  // Set application icon
  QApplication::setWindowIcon(QIcon(":/Icons/{APP_NAME}.png"));
  
  // Load custom stylesheet
  QFile styleFile(":/Stylesheets/NewMPR2Slicer.qss");
  if (styleFile.open(QFile::ReadOnly | QFile::Text))
  {{
    QString stylesheet = QLatin1String(styleFile.readAll());
    qApp->setStyleSheet(stylesheet);
    styleFile.close();
  }}
  // [End NewMPR2 Branding]
'''
    
    # Add includes after existing includes
    include_match = re.search(r'(#include\s*<[^>]+>\s*\n)+', content)
    if include_match:
        insert_pos = include_match.end()
        content = content[:insert_pos] + include_block + content[insert_pos:]
    
    # Find QApplication or qSlicerApplication creation and add branding after
    app_creation_patterns = [
        r'(qSlicerApplication\s+\w+\s*\([^)]*\)\s*;)',
        r'(QApplication\s+\w+\s*\([^)]*\)\s*;)',
        r'(new\s+qSlicerApplication[^;]+;)',
    ]
    
    for pattern in app_creation_patterns:
        match = re.search(pattern, content)
        if match:
            insert_pos = match.end()
            content = content[:insert_pos] + "\n" + branding_code + content[insert_pos:]
            main_file.write_text(content, encoding='utf-8')
            log_info("Updated Main.cxx with branding code")
            return True
    
    # If no match found, add a note
    log_warn("Could not find QApplication creation in Main.cxx")
    log_warn("Manual modification may be required - see CUSTOMIZATION_INSTRUCTIONS.md")
    return False


def update_main_window(app_dir: Path) -> bool:
    """Update main window class with branding."""
    # Find the main window source file
    main_window_patterns = [
        "qSlicerAppMainWindow.cxx",
        f"q{APP_NAME}AppMainWindow.cxx",
        "*MainWindow.cxx"
    ]
    
    main_window_file = None
    for pattern in main_window_patterns:
        matches = list(app_dir.glob(pattern))
        if matches:
            main_window_file = matches[0]
            break
    
    if not main_window_file or not main_window_file.exists():
        log_warn("Main window source file not found")
        return False
    
    content = main_window_file.read_text(encoding='utf-8')
    
    # Check if already customized
    if CUSTOMIZATION_MARKER in content:
        log_skip(f"{main_window_file.name} already customized")
        return True
    
    # Add includes
    include_block = f'''
{CUSTOMIZATION_MARKER} - Includes
#include <QDesktopServices>
#include <QMessageBox>
#include <QUrl>
// [End NewMPR2 Includes]
'''
    
    # Window title and menu code
    window_code = f'''
  {CUSTOMIZATION_MARKER} - Window Title
  this->setWindowTitle("{APP_TITLE}");
  // [End NewMPR2 Title]
'''
    
    # Add includes
    include_match = re.search(r'(#include\s*[<"][^>"]+[>"]\s*\n)+', content)
    if include_match:
        insert_pos = include_match.end()
        content = content[:insert_pos] + include_block + content[insert_pos:]
    
    # Find setupUi or constructor body to add window code
    setup_patterns = [
        r'(void\s+\w+::setupUi\s*\([^)]*\)\s*\{)',
        r'(this->Superclass::setup\s*\(\s*\)\s*;)',
    ]
    
    for pattern in setup_patterns:
        match = re.search(pattern, content)
        if match:
            insert_pos = match.end()
            content = content[:insert_pos] + "\n" + window_code + content[insert_pos:]
            main_window_file.write_text(content, encoding='utf-8')
            log_info(f"Updated {main_window_file.name} with window title")
            return True
    
    log_warn(f"Could not find setupUi in {main_window_file.name}")
    return False


def update_qrc_file(app_dir: Path) -> bool:
    """Update the Qt resource file to include branding resources."""
    resources_dir = app_dir / "Resources"
    
    if not resources_dir.exists():
        log_warn("Resources directory not found")
        return False
    
    # Find existing .qrc file
    qrc_files = list(resources_dir.glob("*.qrc"))
    
    if not qrc_files:
        # Create a new .qrc file
        qrc_file = resources_dir / f"{APP_NAME}App.qrc"
        qrc_content = f'''<RCC>
  <qresource prefix="/{APP_NAME}">
    <file>Icons/{APP_NAME}.png</file>
  </qresource>
  <qresource prefix="/Icons">
    <file>Icons/{APP_NAME}.png</file>
  </qresource>
  <qresource prefix="/Stylesheets">
    <file>Stylesheets/NewMPR2Slicer.qss</file>
  </qresource>
</RCC>
'''
        qrc_file.write_text(qrc_content, encoding='utf-8')
        log_info(f"Created {qrc_file.name}")
        return True
    
    qrc_file = qrc_files[0]
    content = qrc_file.read_text(encoding='utf-8')
    modified = False
    
    # Check if stylesheet is already referenced
    if "NewMPR2Slicer.qss" not in content:
        stylesheet_resource = '''  <qresource prefix="/Stylesheets">
    <file>Stylesheets/NewMPR2Slicer.qss</file>
  </qresource>
'''
        if "</RCC>" in content:
            content = content.replace("</RCC>", stylesheet_resource + "</RCC>")
            modified = True
    
    # Check if icon is referenced (add to /Icons prefix)
    if f"Icons/{APP_NAME}.png" not in content:
        # Find existing Icons qresource or add new one
        if '<qresource prefix="/Icons">' in content:
            # Add to existing Icons resource
            insert_match = re.search(r'(<qresource prefix="/Icons">)', content)
            if insert_match:
                insert_pos = insert_match.end()
                icon_entry = f'\n    <file>Icons/{APP_NAME}.png</file>'
                content = content[:insert_pos] + icon_entry + content[insert_pos:]
                modified = True
        else:
            # Add new Icons resource
            icon_resource = f'''  <qresource prefix="/Icons">
    <file>Icons/{APP_NAME}.png</file>
  </qresource>
'''
            if "</RCC>" in content:
                content = content.replace("</RCC>", icon_resource + "</RCC>")
                modified = True
    
    if modified:
        qrc_file.write_text(content, encoding='utf-8')
        log_info(f"Updated {qrc_file.name} with branding resources")
    else:
        log_skip(f"{qrc_file.name} already contains branding resources")
    
    return True


def create_placeholder_icon(app_dir: Path) -> bool:
    """Create a simple placeholder icon if none exists."""
    icons_dir = app_dir / "Resources" / "Icons"
    ensure_directory(icons_dir)
    
    icon_file = icons_dir / f"{APP_NAME}.png"
    if icon_file.exists():
        log_skip("Icon file already exists")
        return True
    
    # Create a simple 1x1 pixel PNG as placeholder
    # This is a minimal valid PNG (cyan color #22d3ee)
    # In practice, users should replace this with a real icon
    placeholder_png = bytes([
        0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A,  # PNG signature
        0x00, 0x00, 0x00, 0x0D, 0x49, 0x48, 0x44, 0x52,  # IHDR chunk
        0x00, 0x00, 0x00, 0x01, 0x00, 0x00, 0x00, 0x01,  # 1x1 pixel
        0x08, 0x02, 0x00, 0x00, 0x00, 0x90, 0x77, 0x53,
        0xDE, 0x00, 0x00, 0x00, 0x0C, 0x49, 0x44, 0x41,  # IDAT chunk
        0x54, 0x08, 0xD7, 0x63, 0x48, 0xD7, 0xCE, 0x00,
        0x00, 0x00, 0x82, 0x00, 0x81, 0xDD, 0xF2, 0x17,
        0x00, 0x00, 0x00, 0x00, 0x00, 0x49, 0x45, 0x4E,  # IEND chunk
        0x44, 0xAE, 0x42, 0x60, 0x82
    ])
    
    with open(icon_file, 'wb') as f:
        f.write(placeholder_png)
    
    log_info(f"Created placeholder icon: {icon_file.name}")
    log_warn("Replace with a real 256x256 PNG icon before release!")
    return True


def copy_startup_script(script_dir: Path, slicer_project_path: Path, app_dir: Path) -> bool:
    """Copy the startup script for CLI argument handling."""
    startup_src = script_dir / "startup_script.py"
    args_header_src = script_dir / "NewMPR2SlicerArgs.h"
    
    success = True
    
    # Copy startup_script.py to multiple locations
    if startup_src.exists():
        # Copy to Resources
        resources_dir = app_dir / "Resources"
        ensure_directory(resources_dir)
        shutil.copy(startup_src, resources_dir / "startup_script.py")
        
        # Copy to Utilities
        utilities_dir = slicer_project_path / "Utilities"
        ensure_directory(utilities_dir)
        shutil.copy(startup_src, utilities_dir / "startup_script.py")
        
        log_info("Copied startup_script.py for CLI argument handling")
    else:
        log_warn("startup_script.py not found - CLI argument handling may not work")
        success = False
    
    # Copy NewMPR2SlicerArgs.h
    if args_header_src.exists():
        shutil.copy(args_header_src, app_dir / "NewMPR2SlicerArgs.h")
        log_info("Copied NewMPR2SlicerArgs.h for C++ argument parsing")
    
    return success


def write_customization_instructions(slicer_project_path: Path, app_dir: Path):
    """Write detailed instructions for any manual steps needed."""
    instructions_file = slicer_project_path / "CUSTOMIZATION_INSTRUCTIONS.md"
    
    content = f'''# NewMPR2Slicer Customization Instructions

Generated: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}

## Automatic Customizations Applied

The `customize_slicer_app.py` script has applied the following customizations:

1. **Branding resources copied** to `Applications/*/Resources/`
2. **CMakeLists.txt updated** with application identity variables
3. **Main.cxx modified** to set app name, icon, and load stylesheet
4. **Main window updated** with custom window title
5. **Qt resource file (.qrc)** updated with branding entries

## Manual Steps (if needed)

If any automatic modifications failed, apply these manually:

### Main.cxx Modifications

Add after includes:
```cpp
#include <QFile>
#include <QIcon>
#include <QTextStream>
```

Add after QApplication/qSlicerApplication creation:
```cpp
  // NewMPR2 Branding
  QCoreApplication::setApplicationName("{APP_NAME}");
  QCoreApplication::setApplicationDisplayName("{APP_TITLE}");
  QCoreApplication::setOrganizationName("{ORGANIZATION_NAME}");
  QCoreApplication::setOrganizationDomain("{ORGANIZATION_DOMAIN}");
  QCoreApplication::setApplicationVersion("{APP_VERSION}");
  
  QApplication::setWindowIcon(QIcon(":/Icons/{APP_NAME}.png"));
  
  QFile styleFile(":/Stylesheets/NewMPR2Slicer.qss");
  if (styleFile.open(QFile::ReadOnly | QFile::Text))
  {{
    QString stylesheet = QLatin1String(styleFile.readAll());
    qApp->setStyleSheet(stylesheet);
    styleFile.close();
  }}
```

### Main Window Modifications

In the main window constructor or setupUi():
```cpp
  this->setWindowTitle("{APP_TITLE}");
```

## Icon Files

Replace the placeholder icon with real icons:

| File | Size | Location |
|------|------|----------|
| `{APP_NAME}.png` | 256x256 | `Applications/*/Resources/Icons/` |
| `{APP_NAME}.ico` | Multi-size | `Applications/*/Resources/Icons/` |

## Verification

After building, verify:
- [ ] Window title shows "{APP_TITLE}"
- [ ] Application icon appears in taskbar/dock
- [ ] Colors match NewMPR2 theme (dark background, cyan accents)
- [ ] About dialog shows correct app name (if applicable)

## Re-running Customization

This script is idempotent - you can run it again safely:
```bash
python customize_slicer_app.py
```
'''
    
    instructions_file.write_text(content, encoding='utf-8')
    log_info(f"Created CUSTOMIZATION_INSTRUCTIONS.md")


def main():
    """Main entry point."""
    print("=" * 60)
    print(" NewMPR2Slicer Customization Script")
    print("=" * 60)
    print()
    
    script_dir = get_script_dir()
    print(f"Script directory: {script_dir}")
    
    # Find the Slicer project
    print("\n[1/7] Locating NewMPR2Slicer project...")
    slicer_project_path = find_slicer_project(script_dir)
    
    if not slicer_project_path:
        log_error("NewMPR2Slicer project not found!")
        log_error("Expected location: slicer_custom_app/NewMPR2Slicer/")
        log_error("")
        log_error("Please run the cookiecutter generation first:")
        log_error("  cd tools")
        log_error("  generate_newmpr2slicer.bat")
        log_error("")
        log_error("Then move the generated folder to slicer_custom_app/NewMPR2Slicer/")
        sys.exit(1)
    
    log_info(f"Found project: {slicer_project_path.name}")
    
    # Find application directory
    print("\n[2/7] Locating application directory...")
    app_dir = find_app_directory(slicer_project_path)
    
    if not app_dir:
        log_error("Applications/<AppName>App directory not found!")
        log_error("The project structure may be incorrect.")
        sys.exit(1)
    
    log_info(f"Found app directory: {app_dir.name}")
    
    # Copy branding resources
    print("\n[3/7] Copying branding resources...")
    copy_branding_resources(script_dir, slicer_project_path, app_dir)
    
    # Update CMakeLists.txt
    print("\n[4/7] Updating CMakeLists.txt...")
    update_root_cmakelists(slicer_project_path)
    
    # Update Main.cxx
    print("\n[5/7] Updating Main.cxx...")
    update_main_cxx(app_dir)
    
    # Update main window
    print("\n[6/7] Updating main window...")
    update_main_window(app_dir)
    
    # Update .qrc file
    print("\n[7/8] Updating Qt resource file...")
    update_qrc_file(app_dir)
    
    # Copy startup script for CLI handling
    print("\n[8/8] Copying startup script for CLI argument handling...")
    copy_startup_script(script_dir, slicer_project_path, app_dir)
    
    # Create placeholder icon if needed
    print("\n[Bonus] Checking for placeholder icon...")
    create_placeholder_icon(app_dir)
    
    # Write instructions
    print("\n[Final] Writing customization instructions...")
    write_customization_instructions(slicer_project_path, app_dir)
    
    print()
    print("=" * 60)
    print(" CUSTOMIZATION COMPLETE")
    print("=" * 60)
    print()
    print("Modified files:")
    print(f"  • {slicer_project_path.name}/CMakeLists.txt")
    print(f"  • {app_dir.relative_to(slicer_project_path)}/Main.cxx")
    print(f"  • {app_dir.relative_to(slicer_project_path)}/Resources/")
    print()
    print("Next steps:")
    print("  1. Review CUSTOMIZATION_INSTRUCTIONS.md for any manual steps")
    print("  2. Replace placeholder icon with real 256x256 PNG")
    print("  3. Configure and build with CMake:")
    print("       cd NewMPR2Slicer/build")
    print("       cmake -S .. -B . -G \"Visual Studio 17 2022\" -A x64")
    print("       cmake --build . --config Release")
    print()
    print("See docs/setup_windows.md for detailed build instructions.")
    print()
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
