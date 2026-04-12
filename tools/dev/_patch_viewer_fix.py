import os

TARGET = os.path.normpath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)), '..', '..',
    'modules', 'viewer', 'advanced', 'viewer_2d.py'
))

with open(TARGET, 'r', encoding='utf-8') as f:
    lines = f.readlines()

patches_applied = []

P2_START_STR = "            # Need to rebuild or rebind reslice input\n"
P2_END_STR   = "            # Cache the series UID\n"

p2_start = None
p2_end   = None
for i, line in enumerate(lines):
    if p2_start is None and line == P2_START_STR:
        p2_start = i
    if p2_start is not None and p2_end is None and line == P2_END_STR:
        p2_end = i + 1
        break

assert p2_start is not None, "PATCH2: start not found"
assert p2_end   is not None, "PATCH2: end not found"
block = ''.join(lines[p2_start:p2_end])
assert '_is_pydicom_lazy' not in block, "PATCH2: already applied"
assert 'self.image_reslice.Update()' in block, "PATCH2: Update() not found"

new_block = (
    "            # Need to rebuild or rebind reslice input\n"
    "            # For pydicom_2d (lazy backend), bypass preprocessing: upsampling\n"
    "            # creates a disconnected vtkImageData copy that severs\n"
    "            # mark_vtk_modified() signaling. The viewer is wired directly to\n"
    "            # the raw source; no reslice.Update() needed per scroll event.\n"
    "            if _is_pydicom_lazy:\n"
    "                pass  # use vtk_image_data as-is (raw lazy numpy-backed volume)\n"
    "            elif cached_preprocessed is not None:\n"
    "                vtk_image_data = cached_preprocessed\n"
    '                print(f"      \u2705 Reusing cached preprocessed display volume")\n'
    "            else:\n"
    "                vtk_image_data = self._preprocess_vtk_image_data(vtk_image_data)\n"
    "                if allow_preprocess_cache:\n"
    "                    self._local_preprocess_cache[preprocess_cache_key] = vtk_image_data\n"
    "                    self._cache_put_preprocessed(preprocess_cache_key, vtk_image_data)\n"
    "\n"
    "            # Reuse existing ImageReslice instance when possible to reduce object churn\n"
    "            _reslice_data_updated = False  # v2.2.5.3: track in-place rebuild\n"
    "            if hasattr(self, 'image_reslice') and self.image_reslice is not None:\n"
    "                self.image_reslice.vtk_image_data = vtk_image_data\n"
    "                self.image_reslice.metadata = metadata\n"
    "                self.image_reslice.SetInputData(vtk_image_data)\n"
    "                if hasattr(self.image_reslice, '_configure_output_from_input'):\n"
    "                    self.image_reslice._configure_output_from_input()\n"
    "                if not _is_pydicom_lazy:\n"
    "                    # For lazy backend, viewer connects directly to the source --\n"
    "                    # Update() would wastefully re-reslice the full 3D volume.\n"
    "                    self.image_reslice.Update()\n"
    "                    _reslice_data_updated = True  # v2.2.5.3\n"
    "            else:\n"
    "                self.image_reslice = ImageReslice(vtk_image_data, metadata)\n"
    "\n"
    "            # Cache the series UID\n"
    "            self._cached_series_uid = current_series_uid\n"
)

lines[p2_start:p2_end] = [new_block]
patches_applied.append('PATCH2')
print(f"PATCH2 applied: lines {p2_start}-{p2_end}")

P3_START_STR = "                self.SetInputData(_current_reslice_output)\n"
P3_VTK_REF   = "        self.vtk_image_data = _current_reslice_output  # refresh Python-side ref\n"

p3_setinput = None
p3_vtkref   = None
for i, line in enumerate(lines):
    if p3_setinput is None and line == P3_START_STR:
        p3_setinput = i
    if p3_setinput is not None and p3_vtkref is None and line == P3_VTK_REF:
        p3_vtkref = i
        break

assert p3_setinput is not None, "PATCH3: SetInputData line not found"
assert p3_vtkref   is not None, "PATCH3: vtk_image_data ref line not found"

lines[p3_setinput] = (
    "                # For lazy backend, wire viewer directly to the raw numpy-backed source\n"
    "                # so mark_vtk_modified() causes the trivial producer to detect the MTime\n"
    "                # change and re-read fresh numpy scalars on Render() -- no reslice.Update()\n"
    "                # needed per scroll event.\n"
    "                _viewer_input = _src_vtk_image_data if _is_pydicom_lazy else _current_reslice_output\n"
    "                self.SetInputData(_viewer_input)\n"
)
patches_applied.append('PATCH3a')

extra = 5
p3_vtkref += extra
assert lines[p3_vtkref] == P3_VTK_REF, f"vtk ref shifted, got: {repr(lines[p3_vtkref])}"

lines[p3_vtkref] = (
    "        # For lazy backend the viewer input is the raw source; keep Python ref consistent.\n"
    "        self.vtk_image_data = _src_vtk_image_data if _is_pydicom_lazy else _current_reslice_output\n"
)
patches_applied.append('PATCH3b')
print(f"PATCH3 applied at {p3_setinput} and {p3_vtkref}")

with open(TARGET, 'w', encoding='utf-8') as f:
    f.writelines(lines)

print(f"Done: {patches_applied}")
