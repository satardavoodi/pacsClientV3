#-----------------------------------------------------------------------------
# NewMPR2MPR - Multi-Planar Reconstruction Module
#-----------------------------------------------------------------------------

set(MODULE_NAME NewMPR2MPR)

set(MODULE_PYTHON_SCRIPTS
  ${MODULE_NAME}.py
)

# Resource icon is optional; keep empty to avoid hard dependency on missing png.
set(MODULE_PYTHON_RESOURCES
)

slicerMacroBuildScriptedModule(
  NAME ${MODULE_NAME}
  SCRIPTS ${MODULE_PYTHON_SCRIPTS}
  RESOURCES ${MODULE_PYTHON_RESOURCES}
  WITH_GENERIC_TESTS
)
