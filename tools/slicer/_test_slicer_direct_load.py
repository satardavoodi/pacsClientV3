"""
Diagnostic: Test direct volume loading in Slicer (bypasses broken DICOMUtils).
Writes results to a temp file so we can read them even with stdout suppressed.
"""
import os, sys, traceback

RESULT_FILE = os.path.join(os.environ.get("TEMP", "C:\\Temp"), "slicer_direct_load_result.txt")

def write_result(lines):
    with open(RESULT_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

try:
    import slicer
    results = ["[TEST] Slicer import OK"]
    
    # Check DICOM dir from env
    dicom_dir = os.environ.get("NEWMPR2_DICOM_DIR", "")
    results.append(f"[TEST] NEWMPR2_DICOM_DIR = {dicom_dir}")
    results.append(f"[TEST] exists = {os.path.exists(dicom_dir)}")
    
    if not dicom_dir or not os.path.exists(dicom_dir):
        # Use a known test directory
        dicom_dir = r"C:\AI-Pacs codes\aipacs-pydicom2d\user_data\patients\dicom\1.3.12.2.1107.5.2.46.174759.30000026030705563063400000017\5"
        results.append(f"[TEST] Using fallback dir: {dicom_dir}")
    
    # List files
    files = sorted([f for f in os.listdir(dicom_dir) if not f.endswith(('.txt','.xml','.json'))])
    results.append(f"[TEST] Files in dir: {len(files)}")
    if files:
        results.append(f"[TEST] First file: {files[0]}")
    
    # Test 1: Check if DICOMUtils is available
    try:
        from DICOMLib import DICOMUtils
        results.append("[TEST] DICOMUtils import: OK")
        try:
            key = slicer.dicomDatabaseDirectorySettingsKey
            results.append(f"[TEST] dicomDatabaseDirectorySettingsKey: {key}")
        except AttributeError:
            results.append("[TEST] dicomDatabaseDirectorySettingsKey: MISSING (expected - SubjectHierarchy not loaded)")
    except ImportError as e:
        results.append(f"[TEST] DICOMUtils import: FAILED - {e}")
    
    # Test 2: Module status
    try:
        fm = slicer.app.moduleManager().factoryManager()
        loaded = sorted(fm.loadedModuleNames())
        results.append(f"[TEST] Total loaded modules: {len(loaded)}")
        results.append(f"[TEST] SubjectHierarchy loaded: {'SubjectHierarchy' in loaded}")
        results.append(f"[TEST] DICOM loaded: {'DICOM' in loaded}")
        results.append(f"[TEST] Volumes loaded: {'Volumes' in loaded}")
        # List all loaded modules
        results.append(f"[TEST] All modules: {', '.join(loaded)}")
    except Exception as e:
        results.append(f"[TEST] Module check error: {e}")
    
    # Test 3: Direct loadVolume with a DICOM file
    first_file = os.path.join(dicom_dir, files[0]) if files else None
    if first_file:
        results.append(f"[TEST] Attempting slicer.util.loadVolume({os.path.basename(first_file)})...")
        try:
            vol = slicer.util.loadVolume(first_file)
            if vol:
                results.append(f"[TEST] loadVolume SUCCESS: name={vol.GetName()}, id={vol.GetID()}, class={vol.GetClassName()}")
                dims = vol.GetImageData().GetDimensions() if vol.GetImageData() else "NO_DATA"
                results.append(f"[TEST] Volume dimensions: {dims}")
            else:
                results.append("[TEST] loadVolume returned None")
        except Exception as e:
            results.append(f"[TEST] loadVolume FAILED: {e}")
            results.append(traceback.format_exc())
    
    # Test 4: Try loading the whole directory with loadVolume
    results.append(f"[TEST] Attempting slicer.util.loadVolume(directory)...")
    try:
        vol2 = slicer.util.loadVolume(dicom_dir)
        if vol2:
            results.append(f"[TEST] loadVolume(dir) SUCCESS: name={vol2.GetName()}")
        else:
            results.append("[TEST] loadVolume(dir) returned None")
    except Exception as e:
        results.append(f"[TEST] loadVolume(dir) FAILED: {e}")
    
    write_result(results)
    results.append("[TEST] Results written to: " + RESULT_FILE)
    
    # Print to both stdout and stderr (since we don't know which is captured)
    for r in results:
        print(r)
        print(r, file=sys.stderr)
    
    slicer.app.quit()

except Exception as e:
    error_lines = [f"[TEST] FATAL: {e}", traceback.format_exc()]
    write_result(error_lines)
    print(f"[TEST] FATAL: {e}", file=sys.stderr)
