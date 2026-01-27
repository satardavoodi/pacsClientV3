# Runtime hook for numpy
# This runs before the main script to set up environment

import os
import sys

# Set environment variable to avoid numpy threading issues
os.environ['OMP_NUM_THREADS'] = '1'
os.environ['OPENBLAS_NUM_THREADS'] = '1'
os.environ['MKL_NUM_THREADS'] = '1'

# For numpy 1.x compatibility
os.environ['NPY_DISABLE_CPU_FEATURES'] = ''
