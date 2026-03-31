"""Move test files into module subfolders."""
import shutil, os

BASE = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "tests")

MOVES = {
    "download_manager": [
        "test_download_manager.py",
        "run_dm_test.py",
        "dm_results.txt",
    ],
    "viewer": [
        "test_fast_viewer_pipeline.py",
        "test_dicom_import_preview.py",
        "test_flat_folder_import.py",
        "test_pooyan_opencv_filter.py",
        "test_pydicom_backend_geometry.py",
        "test_viewer_backend_config.py",
        "test_viewer_gpu_boost.py",
    ],
    "builder": [
        "test_build_gpu_profile.py",
        "test_materialize_plugin_packages.py",
        "test_plugin_package_builder.py",
        "test_plugin_package_registry.py",
    ],
    "runtime": [
        "test_aipacs_runtime_graphics.py",
        "test_aipacs_runtime_modules.py",
    ],
    "printing": [
        "test_printing_series_repository.py",
    ],
    "cd_burner": [
        "test_cd_burner_portability.py",
    ],
    "web_browser": [
        "test_web_browser_state_store.py",
    ],
    "module_system": [
        "test_module_installation_packages.py",
    ],
    "smoke": [
        "test_import_smoke.py",
        "_simple_test.py",
    ],
}

moved = 0
errors = []
for folder, files in MOVES.items():
    dst_dir = os.path.join(BASE, folder)
    os.makedirs(dst_dir, exist_ok=True)
    for f in files:
        src = os.path.join(BASE, f)
        dst = os.path.join(dst_dir, f)
        if os.path.exists(src):
            shutil.move(src, dst)
            moved += 1
            print(f"  OK  {f} -> {folder}/")
        elif os.path.exists(dst):
            print(f"  SKIP {f} (already in {folder}/)")
        else:
            errors.append(f)
            print(f"  MISS {f}")

print(f"\nMoved: {moved}, Errors: {len(errors)}")
if errors:
    print("Missing files:", errors)
