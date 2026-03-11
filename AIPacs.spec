
# -*- mode: python ; coding: utf-8 -*-
# Production-ready build spec for AIPacs with all data files
# Security: Source files (.py) are excluded from distribution

import os
import sys
from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, collect_submodules

block_cipher = None

# Data files to include
datas = []

# Add main application directories
app_data_dirs = [
    ('PacsClient', 'PacsClient'),
    ('Fonts', 'Fonts'),
    ('Qss', 'Qss'),  # Includes all icons and images
    ('config', 'config'),
]

for src, dst in app_data_dirs:
    if os.path.exists(src):
        datas.append((src, dst))

# Optional files
optional_items = [
    ('json-styles', 'json-styles'),
    ('servers.json', '.'),
    ('browser_bookmarks.json', '.'),
    ('generated-files', 'generated-files'),
]

for src, dst in optional_items:
    if os.path.exists(src):
        datas.append((src, dst))

# Collect PyMuPDF data and binaries - Commented out to avoid build crash
# PyMuPDF will be imported conditionally at runtime if needed
# try:
#     pymupdf_datas = collect_data_files('fitz')
#     datas += pymupdf_datas
# except:
#     pass

# Collect qtawesome fonts and data - CRITICAL for icons
try:
    import qtawesome
    qa_dir = os.path.dirname(qtawesome.__file__)
    qa_fonts_dir = os.path.join(qa_dir, 'fonts')
    
    if os.path.exists(qa_fonts_dir):
        print(f"Adding qtawesome fonts from: {qa_fonts_dir}")
        # Add each font file manually
        import glob
        font_files = glob.glob(os.path.join(qa_fonts_dir, '*'))
        for font_file in font_files:
            if os.path.isfile(font_file):
                datas.append((font_file, 'qtawesome/fonts'))
        print(f"  Added {len([f for f in font_files if os.path.isfile(f)])} qtawesome font files")
except Exception as e:
    print(f"Warning: Could not collect qtawesome fonts: {e}")

# Collect Custom_Widgets data
try:
    cw_datas = collect_data_files('Custom_Widgets')
    datas += cw_datas
except:
    pass

binaries = []
# PyMuPDF binaries - Commented out to avoid build crash
# PyMuPDF will be imported conditionally at runtime if needed
# try:
#     pymupdf_bins = collect_dynamic_libs('fitz')
#     binaries += pymupdf_bins
# except:
#     pass

# Essential hidden imports
hiddenimports = [
    # Project root resolver (used by config.py, font_manager.py, etc.)
    '_project_root',
    # User-data path registry
    'PacsClient.utils.data_paths',
    # Database package (canonical home of all DB code)
    'database',
    'database.core',
    'database.manager',
    
    # PySide6 essentials
    'PySide6.QtCore',
    'PySide6.QtGui',
    'PySide6.QtWidgets',
    'PySide6.QtOpenGL',
    'PySide6.QtOpenGLWidgets',
    'PySide6.QtSvg',
    'PySide6.QtSvgWidgets',
    'PySide6.QtNetwork',
    'PySide6.QtPrintSupport',
    'PySide6.QtWebEngineCore',
    'PySide6.QtWebEngineWidgets',
    'shiboken6',
    
    # VTK - Complete modules with all util submodules
    'vtkmodules',
    'vtkmodules.all',
    'vtkmodules.util',
    'vtkmodules.util.data_model',
    'vtkmodules.util.execution_model',
    'vtkmodules.util.numpy_support',
    'vtkmodules.util.keys',
    'vtkmodules.util.colors',
    'vtkmodules.util.misc',
    'vtkmodules.util.pickle_support',
    'vtkmodules.util.vtkAlgorithm',
    'vtkmodules.util.vtkConstants',
    'vtkmodules.util.vtkImageExportToArray',
    'vtkmodules.util.vtkImageImportFromArray',
    'vtkmodules.util.vtkMethodParser',
    'vtkmodules.util.vtkVariant',
    'vtkmodules.qt',
    'vtkmodules.qt.QVTKRenderWindowInteractor',
    'vtk',
    
    # Numeric - numpy with all required submodules
    'numpy',
    'numpy.core',
    'numpy.core._multiarray_umath',
    'numpy.core._dtype_ctypes',
    'numpy.core._methods',
    'numpy._core',
    'numpy._core.multiarray',
    'numpy._core._multiarray_umath',
    'numpy._core._methods',
    'numpy.linalg',
    'numpy.fft',
    'numpy.random',
    
    # Medical imaging
    'SimpleITK',
    'SimpleITK._SimpleITK',
    'pydicom',
    'pydicom.encoders',
    # 'pydicom.encoders.base',  # Removed - not found, may not exist in this version
    'pydicom.pixel_data_handlers',
    'pydicom.pixel_data_handlers.numpy_handler',
    'pydicom.fileset',  # Required for DICOMDIR creation (CD writing)
    'pydicom.uid',  # Required for UID generation
    'pydicom.dataset',  # Required for DICOM dataset handling
    'pydicom.charset',  # Required for character encoding
    'pynetdicom',
    'pynetdicom.sop_class',
    
    # PyMuPDF - Optional, imported conditionally, removed from hiddenimports to avoid build issues
    # 'fitz',  # Commented out - causes build crash, will be imported conditionally at runtime if needed
    # 'pymupdf',  # Commented out - causes build crash, will be imported conditionally at runtime if needed
    
    # Network/RPC
    'grpc',
    'grpc._cython.cygrpc',
    'googleapiclient',
    'googleapiclient.discovery',
    'google.auth',
    'google.oauth2',
    
    # UI libraries
    'qasync',
    'qtawesome',
    'qtawesome.iconic_font',
    'qtawesome.fonts',
    'Custom_Widgets',
    'Custom_Widgets.QAppSettings',
    'Custom_Widgets.Widgets',
    'Custom_Widgets.QCustomQStackedWidget',
    'Custom_Widgets.QCustomSlideMenu',
    
    # Data handling
    'pandas',
    'pandas._libs',
    'pandas._libs.tslibs',
    'natsort',
    
    # Sound
    'sounddevice',
    'soundfile',
    'speech_recognition',
    
    # System
    'sqlite3',
    'asyncio',
    'concurrent.futures',
    
    # OpenAI and dotenv (from requirements.txt)
    'openai',
    'dotenv',
    'python_dotenv',
    
    # Zeta MPR modules - Required for MPR functionality
    'modules.mpr.zeta_mpr',
    'modules.mpr.zeta_mpr.standard_mpr_viewer',
    'modules.mpr.zeta_mpr.preset_manager',
    'modules.mpr.zeta_mpr.advanced_rendering',
    'modules.mpr.zeta_mpr.curved_mpr',
    'modules.mpr.zeta_mpr.CurveMPR',
    'modules.mpr.zeta_mpr.segmentation_tools',
    'modules.mpr.zeta_mpr.surface_reconstruction',
    'modules.mpr.zeta_mpr.mpr_measurement_tools',
    'modules.mpr.zeta_mpr.toolbar_integration',
    'modules.mpr.orthogonal',
    'modules.mpr.advanced_3d_slicer',
]

# Add all Custom_Widgets submodules
try:
    cw_modules = collect_submodules('Custom_Widgets')
    hiddenimports += cw_modules
except:
    pass

# Add all Zeta MPR submodules - CRITICAL for MPR functionality
try:
    mpr_modules = collect_submodules('modules.mpr.zeta_mpr')
    hiddenimports += mpr_modules
    print(f"Added {len(mpr_modules)} Zeta MPR submodules to hiddenimports")
except Exception as e:
    print(f"Warning: Could not collect Zeta MPR submodules: {e}")

# Add all VTK submodules - CRITICAL for VTK functionality
try:
    vtk_modules = collect_submodules('vtkmodules')
    hiddenimports += vtk_modules
    print(f"Added {len(vtk_modules)} vtkmodules submodules to hiddenimports")
except Exception as e:
    print(f"Warning: Could not collect vtkmodules submodules: {e}")

# Packages to exclude
excludes = [
    'PyQt5',
    'PyQt6',
    'tkinter',
    'torch',
    'tensorflow',
    'transformers',
    'pytest',
    'unittest',
    'IPython',
    'jupyter',
    'fitz',  # PyMuPDF - causes build crash, imported conditionally at runtime
    'pymupdf',  # PyMuPDF - causes build crash, imported conditionally at runtime
]

a = Analysis(
    ['main.py'],
    pathex=[os.path.abspath('.')],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=['hooks'],  # Custom hooks directory for numpy fix
    hooksconfig={},
    runtime_hooks=[
        'hooks/runtime_hook_numpy.py',  # Fix numpy double import
        'hooks/runtime_hook_vtk.py',    # Ensure VTK modules load properly
    ],
    excludes=excludes,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

# Remove .py source files from datas (security)
# Only remove actual .py files, not directories
filtered_datas = []
for item in a.datas:
    if isinstance(item, tuple):
        src = item[0]
        # Only skip if it's a file (not a directory) and ends with .py
        if os.path.isfile(src) and src.endswith('.py'):
            # Skip .py source files for security
            continue
    else:
        src = item
        if os.path.isfile(src) and src.endswith('.py'):
            continue
    filtered_datas.append(item)

a.datas = filtered_datas

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='AIPacs',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,  # Disable console window - no cmd window will appear
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='Qss\\images\\favicon.ico',
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='AIPacs',
)
