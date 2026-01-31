# New MPR4 Module - ITK-SNAP Integration

## Overview

The `newmpr4` module provides seamless integration between the PACS client and **ITK-SNAP** (Insight Segmentation and Registration Toolkit - SNAP), a powerful medical image segmentation and visualization tool.

## Features

- ✅ **Automatic VTK to NIfTI conversion** with metadata preservation
- ✅ **Cross-platform ITK-SNAP detection** (Windows, Linux, macOS)
- ✅ **One-click MPR launching** from DICOM series
- ✅ **DICOM metadata preservation** (spacing, origin, orientation)
- ✅ **Non-blocking process management** (ITK-SNAP runs independently)

## Architecture

```
Patient Tab UI
    ↓
MPR Dropdown Menu → "ITK MPR (ITK-SNAP)"
    ↓
toolbar_manager.py → on_itk_mpr_from_dropdown_requested()
    ↓
newmpr4_module.py → launch_itk_mpr_for_active_series()
    ↓
┌─────────────────────────────────────────┐
│ 1. Convert VTK → NIfTI (SimpleITK)      │
│ 2. Export to temporary file             │
│ 3. Find ITK-SNAP binary                 │
│ 4. Launch ITK-SNAP with NIfTI file      │
└─────────────────────────────────────────┘
```

## ITK-SNAP Installation

### Windows

1. **Download ITK-SNAP:**
   - Visit: http://www.itksnap.org/pmwiki/pmwiki.php?n=Downloads.SNAP3
   - Download the latest Windows installer (e.g., `itksnap-3.8.0-20190612-win64.exe`)

2. **Install:**
   - Run the installer
   - Default location: `C:\Program Files\ITK-SNAP 3.8\` (or similar)
   - The module will automatically detect it

3. **Verify:**
   - The binary should be at: `C:\Program Files\ITK-SNAP X.X\bin\ITK-SNAP.exe`

### Linux

```bash
# Ubuntu/Debian
sudo apt-get install itksnap

# Or download from official site
wget http://www.itksnap.org/download/snap/itksnap-3.8.0-Linux-gcc64.tar.gz
tar -xzf itksnap-3.8.0-Linux-gcc64.tar.gz
sudo mv itksnap-3.8.0-Linux-gcc64 /usr/local/itksnap
sudo ln -s /usr/local/itksnap/bin/itksnap /usr/local/bin/itksnap
```

### macOS

1. **Download:**
   - Visit: http://www.itksnap.org/pmwiki/pmwiki.php?n=Downloads.SNAP3
   - Download the macOS `.dmg` file

2. **Install:**
   - Open the `.dmg`
   - Drag ITK-SNAP to Applications folder
   - Location: `/Applications/ITK-SNAP.app`

## Usage

### From UI (Recommended)

1. Open a patient study in the PACS viewer
2. Select a DICOM series (e.g., MRI scan)
3. Click the **MPR button** dropdown (small arrow)
4. Select **"ITK MPR (ITK-SNAP)"**
5. ITK-SNAP will launch automatically with the series

### Programmatic Usage

```python
from PacsClient.pacs.patient_tab.newmpr4 import launch_itk_mpr_for_active_series

# Launch ITK-SNAP for a series
launch_itk_mpr_for_active_series(
    vtk_image_data=vtk_image,
    metadata=dicom_metadata,
    series_index=0,
    parent_widget=main_window
)
```

## Technical Details

### VTK to NIfTI Conversion

The module uses **SimpleITK** to convert VTK image data to NIfTI format:

1. **Extract VTK data:**
   - Dimensions (x, y, z)
   - Spacing (voxel size in mm)
   - Origin (world coordinates)
   - Direction matrix (orientation)

2. **Convert to NumPy:**
   - Extract scalar data using `vtk_to_numpy`
   - Reshape from Fortran order (VTK) to C order (NumPy)
   - Transpose to correct axis order

3. **Create SimpleITK image:**
   - Set spacing, origin, direction
   - Write as compressed NIfTI (`.nii.gz`)

4. **Export location:**
   - Temporary directory: `%TEMP%\itk_mpr_export\`
   - Filename: `series_{number}_{description}.nii.gz`

### ITK-SNAP Binary Detection

The module searches for ITK-SNAP in this order:

1. **Project directory:** `external/itksnap/bin/`
2. **Common install locations:**
   - Windows: `C:\Program Files\ITK-SNAP X.X\bin\ITK-SNAP.exe`
   - Linux: `/usr/bin/itksnap`, `/usr/local/bin/itksnap`
   - macOS: `/Applications/ITK-SNAP.app/Contents/MacOS/ITK-SNAP`
3. **System PATH:** Searches using `shutil.which()`

### Process Management

- ITK-SNAP is launched as a **detached process**
- Uses `-g` flag to open image immediately
- Non-blocking: PACS client remains responsive
- ITK-SNAP runs independently and can be closed anytime

## Troubleshooting

### "ITK-SNAP binary not found"

**Solution:**
1. Install ITK-SNAP (see installation instructions above)
2. Verify it's installed in a standard location
3. Or add ITK-SNAP to your system PATH

**Manual workaround:**
- The error dialog shows the NIfTI file path
- Open ITK-SNAP manually
- Load the NIfTI file from the temporary directory

### "Error converting VTK to NIfTI"

**Possible causes:**
- Missing SimpleITK: `pip install SimpleITK`
- Corrupted VTK data
- Insufficient disk space

**Check:**
```python
import SimpleITK as sitk
print(sitk.Version.VersionString())
```

### ITK-SNAP crashes on launch

**Possible causes:**
- Incompatible NIfTI file
- Corrupted ITK-SNAP installation
- Insufficient GPU/OpenGL support

**Try:**
- Update ITK-SNAP to latest version
- Check ITK-SNAP logs (usually in `~/.itksnap/`)
- Try opening the NIfTI file manually in ITK-SNAP

## Dependencies

**Required:**
- `SimpleITK >= 2.5.0` (VTK to NIfTI conversion)
- `vtk >= 9.0` (VTK image data handling)
- `PySide6` (Qt GUI framework)

**Optional:**
- ITK-SNAP binary (external application)

## File Locations

```
PacsClient/pacs/patient_tab/newmpr4/
├── __init__.py           # Package initialization
├── newmpr4_module.py     # Core integration logic ⭐
├── newmpr4_widget.py     # UI widget (placeholder)
└── README.md             # This file
```

## Integration Points

### Called by:
- `patient_toolbar/toolbar_manager.py` → `on_itk_mpr_from_dropdown_requested()`

### Calls:
- `_convert_vtk_to_nifti()` - VTK to NIfTI conversion
- `_find_itksnap_binary()` - Binary detection
- `_launch_itksnap()` - Process launching

## Future Enhancements

- [ ] In-process ITK-SNAP library integration (no binary needed)
- [ ] Segmentation result import back to PACS
- [ ] Custom ITK-SNAP workspace presets
- [ ] Multi-series comparison mode
- [ ] Automatic label/segmentation export to DICOM RT Structure Set
- [ ] Integration with ITK-SNAP Python API (when available)

## Resources

- **ITK-SNAP Official Site:** http://www.itksnap.org/
- **ITK-SNAP Documentation:** http://www.itksnap.org/pmwiki/pmwiki.php?n=Documentation.SNAP3
- **ITK-SNAP GitHub:** https://github.com/pyushkevich/itksnap
- **SimpleITK:** https://simpleitk.org/
- **VTK:** https://vtk.org/

## License

This integration module is part of the PACS client project.  
ITK-SNAP is licensed under the GPLv3 license.

## Support

For issues related to:
- **Integration module:** Contact PACS development team
- **ITK-SNAP application:** Visit http://www.itksnap.org/pmwiki/pmwiki.php?n=Main.Support
- **SimpleITK:** Visit https://discourse.itk.org/

---

**Last Updated:** January 2026  
**Module Version:** 1.0  
**ITK-SNAP Compatibility:** 3.8.0 and newer
