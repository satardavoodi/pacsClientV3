/*==============================================================================

  Copyright (c) Kitware, Inc.

  See http://www.slicer.org/copyright/copyright.txt for details.

  Unless required by applicable law or agreed to in writing, software
  distributed under the License is distributed on an "AS IS" BASIS,
  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
  See the License for the specific language governing permissions and
  limitations under the License.

  This file was originally developed by Julien Finet, Kitware, Inc.
  and was partially funded by NIH grant 3P41RR013218-12S1

==============================================================================*/

// NewMPR2Slicer includes
#include "qNewMPR2SlicerAppMainWindow.h"
#include "qNewMPR2SlicerAppMainWindow_p.h"

// Qt includes
#include <QDebug>
#include <QDesktopWidget>
#include <QLabel>
#include <QScreen>
#include <QToolBar>
#include <QStatusBar>
#include <QDockWidget>
#include <QSplitter>
#include <QSettings>

// Slicer includes
#include "qSlicerApplication.h"
#include "qSlicerAboutDialog.h"
#include "qSlicerMainWindow_p.h"
#include "qSlicerModuleSelectorToolBar.h"
#include "qSlicerLayoutManager.h"
#include "qMRMLWidget.h"

// MRML includes (for layout constants)
#include "vtkMRMLLayoutNode.h"

//-----------------------------------------------------------------------------
// qNewMPR2SlicerAppMainWindowPrivate methods

qNewMPR2SlicerAppMainWindowPrivate::qNewMPR2SlicerAppMainWindowPrivate(qNewMPR2SlicerAppMainWindow& object)
  : Superclass(object)
{
}

//-----------------------------------------------------------------------------
qNewMPR2SlicerAppMainWindowPrivate::~qNewMPR2SlicerAppMainWindowPrivate()
{
}

//-----------------------------------------------------------------------------
void qNewMPR2SlicerAppMainWindowPrivate::init()
{
#if (QT_VERSION >= QT_VERSION_CHECK(5, 7, 0))
  QApplication::setAttribute(Qt::AA_UseHighDpiPixmaps);
#endif
  Q_Q(qNewMPR2SlicerAppMainWindow);

  // =========================================================================
  // AI-PACS STABLE BUILD: Set default module BEFORE base class init
  // This ensures NewMPR2MPR is the "home module" from the very first frame.
  // The base class init() calls restoreGUIState() which reads Modules/HomeModule.
  // =========================================================================
  {
    QSettings settings;
    settings.setValue("Modules/HomeModule", "NewMPR2MPR");
    qDebug() << "[AIPACS_UI_CPP] [OK] Home module set to NewMPR2MPR in QSettings";
  }

  // =========================================================================
  // AI-PACS STABLE BUILD: Set default layout to FourUpView BEFORE base class init
  // =========================================================================
  {
    QSettings settings;
    settings.setValue("MainWindow/layout", vtkMRMLLayoutNode::SlicerLayoutFourUpView);
    qDebug() << "[AIPACS_UI_CPP] [OK] Default layout set to FourUpView (3)";
  }

  this->Superclass::init();
}

//-----------------------------------------------------------------------------
void qNewMPR2SlicerAppMainWindowPrivate::setupUi(QMainWindow * mainWindow)
{
  qSlicerApplication * app = qSlicerApplication::application();

  //----------------------------------------------------------------------------
  // Add actions
  //----------------------------------------------------------------------------
  QAction* helpAboutSlicerAppAction = new QAction(mainWindow);
  helpAboutSlicerAppAction->setObjectName("HelpAboutNewMPR2SlicerAppAction");
  helpAboutSlicerAppAction->setText(qNewMPR2SlicerAppMainWindow::tr("About %1").arg(qSlicerApplication::application()->mainApplicationDisplayName()));

  //----------------------------------------------------------------------------
  // Calling "setupUi()" after adding the actions above allows the call
  // to "QMetaObject::connectSlotsByName()" done in "setupUi()" to
  // successfully connect each slot with its corresponding action.
  this->Superclass::setupUi(mainWindow);

  // Add Help Menu Action
  this->HelpMenu->addAction(helpAboutSlicerAppAction);

  //----------------------------------------------------------------------------
  // Configure
  //----------------------------------------------------------------------------
  mainWindow->setWindowIcon(QIcon(":/Icons/Medium/DesktopIcon.png"));

  // =========================================================================
  // AI-PACS: Remove the large logo from PanelDockWidget
  // =========================================================================
  // Previously, this code set a large LogoFull.png (1080x1080) as the title bar
  // widget, which Python then had to remove with timing hacks.
  // Now we simply use an empty widget to eliminate the logo from the start.
  //
  // OLD CODE (removed):
  //   QLabel* logoLabel = new QLabel();
  //   logoLabel->setObjectName("LogoLabel");
  //   logoLabel->setPixmap(qMRMLWidget::pixmapFromIcon(QIcon(":/LogoFull.png")));
  //   this->PanelDockWidget->setTitleBarWidget(logoLabel);
  //
  // NEW: Empty widget with zero height - clean dock without logo
  QWidget* emptyTitleBar = new QWidget();
  emptyTitleBar->setObjectName("AIPacsEmptyTitleBar");
  emptyTitleBar->setFixedHeight(0);
  emptyTitleBar->setMaximumHeight(0);
  this->PanelDockWidget->setTitleBarWidget(emptyTitleBar);
  qDebug() << "[AIPACS_UI_CPP] [OK] PanelDockWidget logo removed (empty title bar)";

  // =========================================================================
  // AI-PACS v1.1.1: GEOMETRY CONFIGURATION
  // Set window size from environment variables (passed from main PACS app)
  // This ensures the Advanced Viewer matches the viewport size from first frame
  // =========================================================================
  bool okX = false, okY = false, okW = false, okH = false;
  int viewerWidth = qEnvironmentVariableIntValue("NEWMPR2_VOR_WIDTH", &okW);
  int viewerHeight = qEnvironmentVariableIntValue("NEWMPR2_VOR_HEIGHT", &okH);
  int vorX = qEnvironmentVariableIntValue("NEWMPR2_VOR_X", &okX);
  int vorY = qEnvironmentVariableIntValue("NEWMPR2_VOR_Y", &okY);

  if (okX && okY && okW && okH && viewerWidth > 400 && viewerHeight > 300)
  {
    mainWindow->setGeometry(vorX, vorY, viewerWidth, viewerHeight);
    qDebug() << "[AIPACS_UI_CPP] VOR geometry applied:" << vorX << "," << vorY << "size" << viewerWidth << "x" << viewerHeight;
  }
  else
  {
    // Default size matching the screenshot layout
    mainWindow->resize(940, 620);
    qDebug() << "[AIPACS_UI_CPP] Window size set to 940x620 (VOR not available)";
    
    // Center window on screen (only when VOR is not used)
    QScreen* screen = QGuiApplication::primaryScreen();
    if (screen)
    {
      QRect screenGeometry = screen->availableGeometry();
      int cx = (screenGeometry.width() - mainWindow->width()) / 2;
      int cy = (screenGeometry.height() - mainWindow->height()) / 2;
      mainWindow->move(cx, cy);
      qDebug() << "[AIPACS_UI_CPP] Window centered at" << cx << "," << cy;
    }
  }

  // =========================================================================
  // AI-PACS v1.1.1: HIDE STATUS BAR
  // =========================================================================
  if (mainWindow->statusBar())
  {
    mainWindow->statusBar()->hide();
    qDebug() << "[AIPACS_UI_CPP] [OK] Status bar hidden";
  }

  // =========================================================================
  // AI-PACS STABLE BUILD: TOOLBAR CONFIGURATION
  // Keep ModuleSelectorToolBar visible at top (per requirements).
  // Hide all other toolbars to prevent flash/movement.
  // =========================================================================
  QStringList toolbarsToHide;
  toolbarsToHide << "MainToolBar"
                 << "ModuleToolBar" << "ViewToolBar" << "CaptureToolBar"
                 << "MouseModeToolBar" << "DataProbeToolBar" << "DialogToolBar"
                 << "FavoriteModulesToolBar" << "UndoRedoToolBar" << "LayoutToolBar"
                 << "ViewersToolBar" << "MarkupsToolBar" << "SequenceBrowserToolBar";

  QList<QToolBar*> allToolbars = mainWindow->findChildren<QToolBar*>();
  for (QToolBar* toolbar : allToolbars)
  {
    QString name = toolbar->objectName();
    if (name == "ModuleSelectorToolBar")
    {
      // Keep ModuleSelectorToolBar visible and at top
      toolbar->setVisible(true);
      qDebug() << "[AIPACS_UI_CPP] [OK] ModuleSelectorToolBar kept VISIBLE at top";
    }
    else if (toolbarsToHide.contains(name) || name.isEmpty())
    {
      toolbar->setVisible(false);
      qDebug() << "[AIPACS_UI_CPP] [OK] Hidden toolbar:" << name;
    }
  }

  // =========================================================================
  // AI-PACS STABLE BUILD: SET LEFT PANEL WIDTH
  // Configure the left module panel to have a reasonable default width
  // =========================================================================
  if (this->PanelDockWidget)
  {
    // Set minimum and preferred width for the left panel
    this->PanelDockWidget->setMinimumWidth(220);
    // The dock widget will be sized by the splitter, but we set a base
    qDebug() << "[AIPACS_UI_CPP] [OK] Left panel configured";
  }

  // =========================================================================
  // AI-PACS STABLE BUILD: SET LAYOUT TO FOUR-UP MPR VIEW
  // Use the layout manager to set the 4-up view before window is shown
  // =========================================================================
  qSlicerApplication* slicerApp = qSlicerApplication::application();
  if (slicerApp)
  {
    qSlicerLayoutManager* layoutManager = slicerApp->layoutManager();
    if (layoutManager)
    {
      layoutManager->setLayout(vtkMRMLLayoutNode::SlicerLayoutFourUpView);
      qDebug() << "[AIPACS_UI_CPP] [OK] Layout set to FourUpView (4-up MPR)";
    }
  }

  // =========================================================================
  // AI-PACS STABLE BUILD: SELECT MODULE VIA TOOLBAR
  // Explicitly select NewMPR2MPR module so the left panel shows it
  // =========================================================================
  if (this->ModuleSelectorToolBar)
  {
    this->ModuleSelectorToolBar->selectModule("NewMPR2MPR");
    qDebug() << "[AIPACS_UI_CPP] [OK] Module NewMPR2MPR selected via toolbar";
  }

  qDebug() << "[AIPACS_UI_CPP] === STABLE BUILD INITIALIZATION COMPLETE ===";

  // Hide the menus
  //this->menubar->setVisible(false);
  //this->FileMenu->setVisible(false);
  //this->EditMenu->setVisible(false);
  //this->ViewMenu->setVisible(false);
  //this->LayoutMenu->setVisible(false);
  //this->HelpMenu->setVisible(false);
}

//-----------------------------------------------------------------------------
// qNewMPR2SlicerAppMainWindow methods

//-----------------------------------------------------------------------------
qNewMPR2SlicerAppMainWindow::qNewMPR2SlicerAppMainWindow(QWidget* windowParent)
  : Superclass(new qNewMPR2SlicerAppMainWindowPrivate(*this), windowParent)
{
  Q_D(qNewMPR2SlicerAppMainWindow);
  d->init();
}

//-----------------------------------------------------------------------------
qNewMPR2SlicerAppMainWindow::qNewMPR2SlicerAppMainWindow(
  qNewMPR2SlicerAppMainWindowPrivate* pimpl, QWidget* windowParent)
  : Superclass(pimpl, windowParent)
{
  // init() is called by derived class.
}

//-----------------------------------------------------------------------------
qNewMPR2SlicerAppMainWindow::~qNewMPR2SlicerAppMainWindow()
{
}

//-----------------------------------------------------------------------------
void qNewMPR2SlicerAppMainWindow::on_HelpAboutNewMPR2SlicerAppAction_triggered()
{
  qSlicerAboutDialog about(this);
  about.setLogo(QPixmap(":/Logo.png"));
  about.exec();
}
