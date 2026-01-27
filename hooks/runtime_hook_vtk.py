# Runtime hook for VTK to ensure proper module loading
# This runs before the main script

import sys
import os

# Pre-import vtkmodules.util submodules to prevent import errors
try:
    import vtkmodules.util
    import vtkmodules.util.data_model
    import vtkmodules.util.execution_model
    import vtkmodules.util.numpy_support
except ImportError:
    pass

