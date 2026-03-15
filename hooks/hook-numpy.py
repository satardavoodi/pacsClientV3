# PyInstaller hook for numpy
# Prevents "cannot load module more than once per process" error

from PyInstaller.utils.hooks import collect_data_files, collect_submodules


def _keep_numpy_runtime_module(name: str) -> bool:
    deny_prefixes = (
        "numpy._pyinstaller",
        "numpy.conftest",
        "numpy.f2py",
        "numpy.testing",
    )
    if name.startswith(deny_prefixes):
        return False
    if ".tests" in name:
        return False
    return True


hiddenimports = collect_submodules("numpy", filter=_keep_numpy_runtime_module)

datas = collect_data_files(
    "numpy",
    excludes=[
        "**/tests",
        "**/tests/**",
        "**/conftest.py",
    ],
)

