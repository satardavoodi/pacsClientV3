# PyInstaller hook for numpy
# Prevents "cannot load module more than once per process" error

from PyInstaller.utils.hooks import collect_submodules, collect_data_files

# Collect all numpy submodules
hiddenimports = collect_submodules('numpy')

# Collect numpy data files
datas = collect_data_files('numpy')

