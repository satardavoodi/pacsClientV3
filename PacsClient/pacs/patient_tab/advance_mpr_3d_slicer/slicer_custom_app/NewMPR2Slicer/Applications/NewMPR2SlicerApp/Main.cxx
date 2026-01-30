/*==============================================================================

  Copyright (c) Kitware, Inc.

  See http://www.slicer.org/copyright/copyright.txt for details.

  Unless required by applicable law or agreed to in writing, software
  distributed under the License is distributed on an "AS IS" BASIS,
  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
  See the License for the specific language governing permissions and
  limitations under the License.

  This file was originally developed by Jean-Christophe Fillion-Robin, Kitware, Inc.
  and was partially funded by NIH grant 3P41RR013218-12S1

==============================================================================*/

// NewMPR2Slicer includes
#include "qNewMPR2SlicerAppMainWindow.h"
#include "Widgets/qAppStyle.h"

// Slicer includes
#include "qSlicerApplication.h"
#include "qSlicerApplicationHelper.h"
#include "vtkSlicerConfigure.h" // For Slicer_MAIN_PROJECT_APPLICATION_NAME
#include "vtkSlicerVersionConfigure.h" // For Slicer_MAIN_PROJECT_VERSION_FULL

// Qt includes
#include <QCoreApplication>
#include <QFile>
#include <QDebug>

namespace
{

// AI-PACS Branding Constants
// These match the branding in launch_slicer.py and startup_script.py
const char* AIPACS_APP_NAME = "AIPacsAdvancedViewer";
const char* AIPACS_DISPLAY_NAME = "AI-PACS Advanced Viewer";
const char* AIPACS_WINDOW_TITLE = "AI-PACS Advanced Viewer v0.1";
const char* AIPACS_ORG_NAME = "AI-PACS";
const char* AIPACS_ORG_DOMAIN = "ai-pacs.local";

//----------------------------------------------------------------------------
// Load AI-PACS dark theme stylesheet from embedded resources
// This must be called BEFORE the main window is shown to prevent flash
//----------------------------------------------------------------------------
void loadAIPacsStylesheet(QApplication* app)
{
  qDebug() << "[AIPACS_UI_CPP] Loading AI-PACS dark theme stylesheet...";
  
  QFile styleFile(":/AIPacsTheme.qss");
  if (styleFile.open(QFile::ReadOnly | QFile::Text))
    {
    QString styleSheet = QString::fromUtf8(styleFile.readAll());
    app->setStyleSheet(styleSheet);
    qDebug() << "[AIPACS_UI_CPP] [OK] Stylesheet loaded from embedded resources ("
             << styleSheet.length() << " characters)";
    styleFile.close();
    }
  else
    {
    qWarning() << "[AIPACS_UI_CPP] Warning: Could not load embedded stylesheet from :/AIPacsTheme.qss";
    }
}

//----------------------------------------------------------------------------
int SlicerAppMain(int argc, char* argv[])
{
  typedef qNewMPR2SlicerAppMainWindow SlicerMainWindowType;

  qDebug() << "[AIPACS_UI_CPP] === AI-PACS Advanced Viewer Starting ===";

  // AI-PACS: Set application identity BEFORE creating the app
  // This ensures the window title and Task Manager process name are correct from first frame
  QCoreApplication::setApplicationName(AIPACS_APP_NAME);
  // Note: setApplicationDisplayName is only available on QGuiApplication, set after app creation
  QCoreApplication::setOrganizationName(AIPACS_ORG_NAME);
  QCoreApplication::setOrganizationDomain(AIPACS_ORG_DOMAIN);

  qDebug() << "[AIPACS_UI_CPP] Application identity set (pre-init)";

  qSlicerApplicationHelper::preInitializeApplication(argv[0], new qAppStyle);

  qSlicerApplication app(argc, argv);
  if (app.returnCode() != -1)
    {
    return app.returnCode();
    }

  // AI-PACS: Reinforce branding after app creation (in case Slicer overrides)
  app.setApplicationName(AIPACS_APP_NAME);
  app.setApplicationDisplayName(AIPACS_WINDOW_TITLE);
  app.setOrganizationName(AIPACS_ORG_NAME);
  app.setOrganizationDomain(AIPACS_ORG_DOMAIN);

  // =========================================================================
  // AI-PACS: Load dark theme stylesheet BEFORE window creation
  // This prevents the "light to dark flash" that occurred when Python applied
  // the stylesheet after the window was already visible.
  // =========================================================================
  loadAIPacsStylesheet(&app);

  qDebug() << "[AIPACS_UI_CPP] Creating main window...";

  QScopedPointer<SlicerMainWindowType> window;
  QScopedPointer<QSplashScreen> splashScreen;

  qSlicerApplicationHelper::postInitializeApplication<SlicerMainWindowType>(
        app, splashScreen, window);

  if (!window.isNull())
    {
    // AI-PACS: Set window title - this is the title shown to users
    // Must be set after window creation to override any Slicer defaults
    window->setWindowTitle(AIPACS_WINDOW_TITLE);
    qDebug() << "[AIPACS_UI_CPP] [OK] Window title set:" << AIPACS_WINDOW_TITLE;
    }

  qDebug() << "[AIPACS_UI_CPP] === Main window ready, entering event loop ===";

  return app.exec();
}

} // end of anonymous namespace

#include "qSlicerApplicationMainWrapper.cxx"
