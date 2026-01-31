/*
 * NewMPR2Slicer Command-Line Arguments
 * 
 * This file defines the command-line argument parsing for NewMPR2Slicer.
 * It follows the contract defined in docs/launch_contract.md.
 * 
 * Include this in Main.cxx and call parseNewMPR2Args() after creating QApplication.
 * Then call executeNewMPR2Startup() after the main window is shown.
 */

#ifndef NEWMPR2SLICER_ARGS_H
#define NEWMPR2SLICER_ARGS_H

#include <QString>
#include <QStringList>
#include <QCoreApplication>
#include <QFile>
#include <QDir>
#include <QDebug>

// ============================================================
// Argument Structure
// ============================================================

struct NewMPR2Args
{
    QString dicomDir;           // --dicom-dir <path>
    QString layout = "mpr";     // --layout <name>
    QString patientId;          // --patient-id <id>
    QString studyId;            // --study-id <id>
    bool noSplash = false;      // --no-splash
    bool autoCenter = true;     // --auto-center (default) or --no-auto-center
    
    bool hasArgs() const
    {
        return !dicomDir.isEmpty() || layout != "mpr" || 
               !patientId.isEmpty() || !studyId.isEmpty();
    }
};

// Global instance to store parsed arguments
inline NewMPR2Args g_newMPR2Args;

// ============================================================
// Argument Parsing
// ============================================================

inline void parseNewMPR2Args()
{
    QStringList args = QCoreApplication::arguments();
    
    qInfo() << "[NewMPR2Slicer] Parsing command-line arguments...";
    qInfo() << "[NewMPR2Slicer] Arguments:" << args;
    
    for (int i = 1; i < args.size(); ++i)
    {
        QString arg = args[i];
        
        if (arg == "--dicom-dir" && i + 1 < args.size())
        {
            g_newMPR2Args.dicomDir = args[++i];
            qInfo() << "[NewMPR2Slicer] DICOM dir:" << g_newMPR2Args.dicomDir;
        }
        else if (arg == "--layout" && i + 1 < args.size())
        {
            g_newMPR2Args.layout = args[++i].toLower();
            qInfo() << "[NewMPR2Slicer] Layout:" << g_newMPR2Args.layout;
        }
        else if (arg == "--patient-id" && i + 1 < args.size())
        {
            g_newMPR2Args.patientId = args[++i];
            qInfo() << "[NewMPR2Slicer] Patient ID:" << g_newMPR2Args.patientId;
        }
        else if (arg == "--study-id" && i + 1 < args.size())
        {
            g_newMPR2Args.studyId = args[++i];
            qInfo() << "[NewMPR2Slicer] Study ID:" << g_newMPR2Args.studyId;
        }
        else if (arg == "--no-splash")
        {
            g_newMPR2Args.noSplash = true;
            qInfo() << "[NewMPR2Slicer] No splash: true";
        }
        else if (arg == "--auto-center")
        {
            g_newMPR2Args.autoCenter = true;
        }
        else if (arg == "--no-auto-center")
        {
            g_newMPR2Args.autoCenter = false;
        }
    }
}

// ============================================================
// Python Startup Script Execution
// ============================================================

inline QString getStartupScriptPath()
{
    // Look for the startup script in several locations
    QStringList searchPaths = {
        QCoreApplication::applicationDirPath() + "/startup_script.py",
        QCoreApplication::applicationDirPath() + "/../startup_script.py",
        QCoreApplication::applicationDirPath() + "/../../startup_script.py",
        QCoreApplication::applicationDirPath() + "/../Resources/startup_script.py",
    };
    
    for (const QString& path : searchPaths)
    {
        if (QFile::exists(path))
        {
            return QDir::cleanPath(path);
        }
    }
    
    return QString();
}

// Python code to run at startup (uses the startup_script.py)
inline QString getStartupPythonCode()
{
    QString scriptPath = getStartupScriptPath();
    
    if (!scriptPath.isEmpty())
    {
        // Execute the external script
        return QString(
            "import sys\n"
            "exec(open('%1').read())\n"
        ).arg(scriptPath.replace("\\", "\\\\").replace("'", "\\'"));
    }
    
    // Fallback: inline Python code if script not found
    return QString(
        "import slicer\n"
        "import sys\n"
        "\n"
        "# Layout mapping\n"
        "LAYOUT_MAP = {\n"
        "    'mpr': slicer.vtkMRMLLayoutNode.SlicerLayoutFourUpView,\n"
        "    'fourup': slicer.vtkMRMLLayoutNode.SlicerLayoutFourUpView,\n"
        "    'axial': slicer.vtkMRMLLayoutNode.SlicerLayoutOneUpRedSliceView,\n"
        "    'sagittal': slicer.vtkMRMLLayoutNode.SlicerLayoutOneUpYellowSliceView,\n"
        "    'coronal': slicer.vtkMRMLLayoutNode.SlicerLayoutOneUpGreenSliceView,\n"
        "    'threed': slicer.vtkMRMLLayoutNode.SlicerLayoutOneUp3DView,\n"
        "    'conventional': slicer.vtkMRMLLayoutNode.SlicerLayoutConventionalView,\n"
        "}\n"
        "\n"
        "# Parse arguments\n"
        "dicom_dir = '%1'\n"
        "layout = '%2'\n"
        "\n"
        "# Load DICOM if specified\n"
        "if dicom_dir:\n"
        "    try:\n"
        "        vol = slicer.util.loadVolume(dicom_dir)\n"
        "        if vol:\n"
        "            logic = slicer.app.applicationLogic()\n"
        "            sel = logic.GetSelectionNode()\n"
        "            sel.SetActiveVolumeID(vol.GetID())\n"
        "            logic.PropagateVolumeSelection()\n"
        "            slicer.util.resetSliceViews()\n"
        "    except Exception as e:\n"
        "        print(f'[NewMPR2Slicer] Load error: {e}')\n"
        "\n"
        "# Set layout\n"
        "layout_id = LAYOUT_MAP.get(layout.lower(), LAYOUT_MAP['mpr'])\n"
        "slicer.app.layoutManager().setLayout(layout_id)\n"
        "\n"
        "print('[NewMPR2Slicer] Startup complete')\n"
    ).arg(g_newMPR2Args.dicomDir.replace("\\", "/").replace("'", "\\'"))
     .arg(g_newMPR2Args.layout);
}

#endif // NEWMPR2SLICER_ARGS_H
