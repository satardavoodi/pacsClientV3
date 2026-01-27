# PyInstaller hook for vtkmodules
# Collects all VTK submodules including util.data_model

from PyInstaller.utils.hooks import collect_submodules, collect_data_files, collect_dynamic_libs

# Collect ALL vtkmodules submodules
hiddenimports = collect_submodules('vtkmodules')

# Ensure specific util modules are included
hiddenimports += [
    'vtkmodules.util',
    'vtkmodules.util.data_model',
    'vtkmodules.util.execution_model',
    'vtkmodules.util.numpy_support',
    'vtkmodules.util.colors',
    'vtkmodules.util.keys',
    'vtkmodules.util.misc',
    'vtkmodules.util.pickle_support',
    'vtkmodules.util.vtkAlgorithm',
    'vtkmodules.util.vtkConstants',
    'vtkmodules.util.vtkImageExportToArray',
    'vtkmodules.util.vtkImageImportFromArray',
    'vtkmodules.util.vtkMethodParser',
    'vtkmodules.util.vtkVariant',
]

# Collect VTK data files
datas = collect_data_files('vtkmodules')

# Collect VTK dynamic libraries
binaries = collect_dynamic_libs('vtkmodules')

