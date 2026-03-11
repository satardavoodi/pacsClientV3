
# ============================================================================
# AI-PACS Advanced Viewer - Application Properties
# ============================================================================
# This file defines branding for the custom Slicer application.
# The APPLICATION_NAME determines the executable name in Task Manager.

set(APPLICATION_NAME
  AIPacsAdvancedViewer
  )
set(APPLICATION_DISPLAY_NAME
  "AI-PACS Advanced Viewer"
  )

set(VERSION_MAJOR
  0
  )
set(VERSION_MINOR
  1
  )
set(VERSION_PATCH
  0
  )

set(DESCRIPTION_SUMMARY
  "AI-PACS Advanced Viewer - MPR and 3D Visualization"
  )
set(DESCRIPTION_FILE
  ${Slicer_SOURCE_DIR}/README.md
  )

# Organization branding
set(ORGANIZATION_DOMAIN
  "ai-pacs.local"
  )
set(ORGANIZATION_NAME
  "AI-PACS"
  )

set(LAUNCHER_SPLASHSCREEN_FILE
  "${CMAKE_CURRENT_LIST_DIR}/Resources/Images/SplashScreen.png"
  )
set(APPLE_ICON_FILE
  "${CMAKE_CURRENT_LIST_DIR}/Resources/Icons/DesktopIcon.icns"
  )
set(WIN_ICON_FILE
  "${CMAKE_CURRENT_LIST_DIR}/Resources/Icons/DesktopIcon.ico"
  )

set(LICENSE_FILE
  "${NewMPR2Slicer_SOURCE_DIR}/LICENSE"
  )
