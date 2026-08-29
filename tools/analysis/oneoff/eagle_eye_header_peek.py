"""One-off: rebuild a captured session's package header and print it.

Proves what the model will actually receive - in particular the measured
AXIAL SLAB STRUCTURE block - without spending a request.
"""
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3]))

from modules.ai_imaging.eagle_eye_lumbar import llm_package as pkg

package = pkg.build_package(sys.argv[1])
print(package.header)
