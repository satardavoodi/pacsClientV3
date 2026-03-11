"""Quick Slicer test: check if DICOM loading works via both strategies."""
import os, sys, traceback

LOG = os.path.join(os.environ.get("TEMP", "."), "slicer_dicom_test_result.txt")

def log(msg):
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(msg + "\n")
    sys.stderr.write(msg + "\n")

try:
    import slicer
    log("[TEST] Slicer imported OK")
except ImportError:
    log("[TEST] FATAL: not running inside Slicer")
    sys.exit(1)

dicom_dir = os.environ.get("NEWMPR2_DICOM_DIR", "")
log(f"[TEST] DICOM dir: {dicom_dir}")
log(f"[TEST] Dir exists: {os.path.exists(dicom_dir)}")

if dicom_dir and os.path.exists(dicom_dir):
    files = [f for f in os.listdir(dicom_dir) if not f.endswith(('.txt','.json','.xml','.py'))]
    log(f"[TEST] Files in dir: {len(files)}")
    if files:
        log(f"[TEST] First file: {files[0]}")

# Strategy 1: DICOMUtils
log("\n[TEST] === Strategy 1: DICOMUtils ===")
try:
    from DICOMLib import DICOMUtils
    log("[TEST] DICOMUtils imported OK")
    log(f"[TEST] hasattr dicomDatabaseDirectorySettingsKey: {hasattr(slicer, 'dicomDatabaseDirectorySettingsKey')}")
    with DICOMUtils.TemporaryDICOMDatabase() as db:
        DICOMUtils.importDicom(dicom_dir, db)
        patients = db.patients()
        log(f"[TEST] Strategy1 OK: patients={patients}")
except Exception as e:
    log(f"[TEST] Strategy1 FAILED: {type(e).__name__}: {e}")

# Strategy 2: slicer.util.loadVolume
log("\n[TEST] === Strategy 2: loadVolume ===")
try:
    flist = sorted([os.path.join(dicom_dir, f) for f in os.listdir(dicom_dir) 
                    if not f.endswith(('.txt','.json','.xml','.py'))])
    log(f"[TEST] {len(flist)} candidate files")
    if flist:
        first = flist[0]
        log(f"[TEST] Loading: {first}")
        vol = slicer.util.loadVolume(first)
        log(f"[TEST] loadVolume result: {vol}")
        if vol:
            imgdata = vol.GetImageData()
            if imgdata:
                log(f"[TEST] SUCCESS: name={vol.GetName()} dims={imgdata.GetDimensions()}")
            else:
                log(f"[TEST] Volume loaded but no image data!")
        else:
            log("[TEST] loadVolume returned None")
except Exception as e2:
    log(f"[TEST] Strategy2 FAILED: {type(e2).__name__}: {e2}")
    traceback.print_exc(file=open(LOG, "a"))

# Strategy 3: Try loading entire directory with DICOMScalarVolumePlugin directly
log("\n[TEST] === Strategy 3: ITK ImageSeriesReader ===")
try:
    import vtk
    reader = vtk.vtkDICOMImageReader()
    reader.SetDirectoryName(dicom_dir)
    reader.Update()
    output = reader.GetOutput()
    if output:
        dims = output.GetDimensions()
        log(f"[TEST] vtkDICOMImageReader: dims={dims}")
    else:
        log("[TEST] vtkDICOMImageReader returned no output")
except Exception as e3:
    log(f"[TEST] Strategy3 FAILED: {type(e3).__name__}: {e3}")

log("\n[TEST] === Module check ===")
try:
    fm = slicer.app.moduleManager().factoryManager()
    loaded = sorted(fm.loadedModuleNames())
    log(f"[TEST] Loaded modules: {len(loaded)}")
    log(f"[TEST] SubjectHierarchy loaded: {'SubjectHierarchy' in loaded}")
    log(f"[TEST] DICOM loaded: {'DICOM' in loaded}")
    log(f"[TEST] Volumes loaded: {'Volumes' in loaded}")
except Exception as e4:
    log(f"[TEST] Module check failed: {e4}")

log("\n[TEST] DONE - quitting")
slicer.app.quit()
