"""Worker-only, isolated manual segmentation sessions; never overwrite inference."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import uuid
import tempfile
import threading
import time

from .contracts import BrainError

_REVIEW_PROCESSES = {}
_REVIEW_LAUNCH_LOCK = threading.Lock()


def _review_running(directory):
    process = _REVIEW_PROCESSES.get(str(directory))
    if process is not None and process.poll() is None:
        return True
    _REVIEW_PROCESSES.pop(str(directory), None)
    marker = directory / 'editor-process.json'
    if not marker.is_file():
        return False
    import psutil
    try:
        state = json.loads(marker.read_text(encoding='utf-8'))
        command = psutil.Process(int(state['pid'])).cmdline()
        script = os.path.normcase(os.path.realpath(state['script']))
        return any(os.path.normcase(os.path.realpath(arg)) == script for arg in command)
    except (psutil.NoSuchProcess, ValueError, KeyError, TypeError):
        return False
    except psutil.AccessDenied:
        raise BrainError('Cannot verify the existing Advanced Image Analysis window. Close it before reopening.') from None


def reopen_review(session):
    """Worker-only relaunch; retain the session and any saved corrected mask."""
    directory = Path(session)
    if not all((directory / name).is_file() for name in ('session.json', 'image.nii.gz', 'original.nii.gz')):
        raise BrainError('The saved manual correction session is incomplete.')
    return _launch_review(directory)


def _launch_review(directory):
    with _REVIEW_LAUNCH_LOCK:
        deadline = time.monotonic() + 5
        while _review_running(directory):
            if time.monotonic() >= deadline:
                raise BrainError('Advanced Image Analysis is still open or finishing its exit. Return to its window, or wait for it to close.')
            time.sleep(0.1)
        return _launch_review_locked(directory)


def wait_review_ready(session, *, timeout=180):
    """Worker-only handshake: process creation is not visible editor readiness."""
    directory = Path(session)
    token = json.loads((directory / 'launch-request.json').read_text(encoding='utf-8'))['token']
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            state = json.loads((directory / 'editor-state.json').read_text(encoding='utf-8'))
        except (FileNotFoundError, json.JSONDecodeError):
            state = {}
        if state.get('token') == token:
            if state.get('status') == 'ready':
                return str(directory)
            if state.get('status') == 'error':
                raise BrainError('Advanced Image Analysis could not be initialized. Review its error message before retrying.')
        time.sleep(0.1)
    raise BrainError('Advanced Image Analysis is taking longer than expected. It may still be loading; check its window before retrying.')


def open_review_ready(result, session=None):
    """Keep client activity visible until the prepared editor acknowledges readiness."""
    return wait_review_ready(reopen_review(session) if session else prepare_review(result))


def review_environment(parent, directory):
    """Interactive VTK owns its GL context; preserve explicit software opt-in."""
    env = dict(parent)
    if env.get('AIPACS_MANUAL_REVIEW_SOFTWARE_RENDERING') != '1':
        for key in ('QT_OPENGL_DLL', 'QT_QUICK_BACKEND', 'LIBGL_ALWAYS_SOFTWARE',
                    'LIBGL_ALWAYS_INDIRECT', 'MESA_GL_VERSION_OVERRIDE',
                    'GALLIUM_DRIVER', 'VTK_OPENGL_FORCE_SOFTPIPE',
                    'VTK_DEFAULT_OPENGL_WINDOW'):
            env.pop(key, None)
        env['QT_OPENGL'] = 'desktop'
    env['AIPACS_MANUAL_REVIEW'] = str(directory)
    return env


def prepare_review(result):
    from .runtime import slicer_executable, sha256
    slicer_executable()  # Validate availability before creating a private session.
    lesion = result.get('analysis_type') == 'brain_lesions'
    review_assets = result.get('review_assets', {})
    source = Path(review_assets['mask']) if review_assets else Path(result['mask_path']) if lesion else Path(result['artifact_directory']) / 'labels.nii.gz'
    image_name = 'flair.nii.gz' if lesion else 'resampled.nii.gz'
    roots = [Path(result['artifact_directory']), *source.parents]
    root = Path(result['artifact_directory']) if review_assets else next((p for p in roots if (p / image_name).is_file() and source.is_file()), None)
    if root is None:
        raise BrainError('Original image and segmentation are required for manual correction.')
    from PacsClient.utils.data_paths import AI_DIR
    directory = Path(AI_DIR) / 'eagle_eye' / 'manual-reviews' / uuid.uuid4().hex
    directory.mkdir(parents=True)
    shutil.copy2(review_assets.get('image', root / image_name), directory / 'image.nii.gz')
    shutil.copy2(source, directory / 'original.nii.gz')
    manifest = dict(source_result=result, source_mask=str(source), source_sha256=sha256(source),
                    lesion=lesion, directory=str(directory))
    if not lesion:
        manifest['label_names'] = json.loads(Path(review_assets.get('names', root / 'label_names.json')).read_text(encoding='utf-8'))
    (directory / 'session.json').write_text(json.dumps(manifest, allow_nan=False), encoding='utf-8')
    return _launch_review(directory)


def _launch_review_locked(directory):
    from .runtime import slicer_executable
    executable = slicer_executable()
    source = directory / 'original.nii.gz'
    corrected = directory / 'corrected.nii.gz'
    if corrected.is_file():
        import SimpleITK as sitk
        manifest = json.loads((directory / 'session.json').read_text(encoding='utf-8'))
        validate_edit(sitk.ReadImage(str(source)), sitk.ReadImage(str(corrected)), lesion=manifest['lesion'])
        source = corrected
    shutil.copy2(source, directory / 'editor-input.nii.gz')
    # CTK launcher splits --python-script paths containing spaces. Stage only
    # application code; patient images remain in the private review directory.
    script_source = Path(__file__).with_name('manual_slicer.py')
    staged = Path(tempfile.mkdtemp(prefix='aipacs-manual-')) / 'manual_slicer.py'
    shutil.copy2(script_source, staged)
    chrome_source = Path(__file__).resolve().parents[2] / 'mpr/advanced_3d_slicer/slicer_custom_app/viewer_chrome.py'
    shutil.copy2(chrome_source, staged.with_name('viewer_chrome.py'))
    startup_modules = staged.parent / 'startup-modules'
    startup_modules.mkdir()
    shutil.copy2(script_source.with_name('AIPacsBrainReviewStartup.py'),
                 startup_modules / 'AIPacsBrainReviewStartup.py')
    script_path = str(staged)
    if ' ' in script_path and os.name == 'nt':
        import ctypes
        buffer = ctypes.create_unicode_buffer(32768)
        length = ctypes.windll.kernel32.GetShortPathNameW(script_path, buffer, len(buffer))
        if 0 < length < len(buffer):
            script_path = buffer.value
    if ' ' in script_path:
        raise BrainError('Advanced Image Analysis requires a temporary script path without spaces. Configure a space-free TEMP directory.')
    env = review_environment(os.environ, directory)
    token = uuid.uuid4().hex
    env['AIPACS_MANUAL_REVIEW_TOKEN'] = token
    (directory / 'launch-request.json').write_text(json.dumps({'token': token}), encoding='utf-8')
    startup = None
    if os.name == 'nt':
        startup = subprocess.STARTUPINFO()
        startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startup.wShowWindow = 0
    with (directory / 'slicer-launch.log').open('wb') as log:
        process = subprocess.Popen([str(executable), '--no-splash', '--launcher-no-splash', '--ignore-slicerrc', '--disable-settings',
                          '--launcher-ignore-user-additional-settings', '--python-script', script_path,
                          '--additional-module-paths', str(Path(script_path).parent / 'startup-modules')],
                         env=env, startupinfo=startup, stdout=log, stderr=subprocess.STDOUT)
    _REVIEW_PROCESSES[str(directory)] = process
    return str(directory)


def validate_edit(original, edited, *, lesion=False):
    import numpy as np
    import SimpleITK as sitk
    if (original.GetDimension() != 3 or edited.GetDimension() != 3
            or original.GetSize() != edited.GetSize()
            or edited.GetNumberOfComponentsPerPixel() != 1
            or any(not np.allclose(getattr(original, k)(), getattr(edited, k)(), atol=1e-5, rtol=0)
                   for k in ('GetSpacing', 'GetOrigin', 'GetDirection'))):
        raise BrainError('Corrected segmentation geometry does not match the original examination.')
    before, after = sitk.GetArrayFromImage(original), sitk.GetArrayFromImage(edited)
    allowed = [0, 1] if lesion else np.append(np.unique(before), 0)
    if (lesion and not np.isin(before, allowed).all()) or not np.isfinite(after).all() or not np.isin(after, allowed).all():
        raise BrainError('Corrected segmentation contains unsupported labels.')


def recalculate_review(session, *, cancel=None, progress=None):
    manifest_path = Path(session) / 'session.json'
    manifest = json.loads(manifest_path.read_text(encoding='utf-8')) if manifest_path.is_file() else {}
    if manifest.get('source_result', {}).get('remote_analysis'):
        from ..eagle_eye_remote.segmentation_review import submit
        return submit(session, cancel=cancel, progress=progress)
    from .service import _ANALYSIS_LOCK
    if not _ANALYSIS_LOCK.acquire(blocking=False):
        raise BrainError('Another brain analysis is running. Wait for it to finish before recalculating.')
    try:
        return _recalculate_review(session, cancel=cancel, progress=progress)
    finally:
        _ANALYSIS_LOCK.release()


def _recalculate_review(session, *, cancel=None, progress=None):
    import SimpleITK as sitk
    from .runtime import sha256
    directory = Path(session)
    if cancel is not None and cancel.is_set():
        raise BrainError('Manual recalculation cancelled.')
    manifest = json.loads((directory / 'session.json').read_text(encoding='utf-8'))
    edited_path = directory / 'corrected.nii.gz'
    if not edited_path.is_file():
        raise BrainError('In Advanced Image Analysis, click Save correction for AI-PACS before recalculating.')
    if sha256(manifest['source_mask']) != manifest['source_sha256']:
        raise BrainError('Original segmentation changed. Start a new review session.')
    original, edited = sitk.ReadImage(str(directory / 'original.nii.gz')), sitk.ReadImage(str(edited_path))
    validate_edit(original, edited, lesion=manifest['lesion'])
    if not manifest['lesion']:
        return brain_revision(directory, manifest, original, edited)
    from .lesions import measure_mask
    from .lesion_report import write_lesion_report
    result = manifest['source_result']
    if result.get('longitudinal'):
        raise BrainError('Re-run longitudinal comparison after correcting an individual examination.')
    out = directory / ('revision-' + uuid.uuid4().hex[:12]); out.mkdir()
    sitk.WriteImage(edited, str(out / 'corrected.nii.gz'))
    result.update(mask_path=str(out / 'corrected.nii.gz'), artifact_directory=str(out),
                  manual_correction={'source_mask_sha256': manifest['source_sha256'],
                                     'corrected_mask_sha256': sha256(out / 'corrected.nii.gz')},
                  pdf_available=False)
    image = sitk.ReadImage(str(directory / 'image.nii.gz'))
    for key in ('multisequence', 'enhancement_review', 'sampled_topography', 't1_support'):
        if result.get(key): result['source_' + key] = result.pop(key)
    if result.get('acquisition_mode') == '2d':
        from .lesions_2d import measure_slices, spatial_status
        if result.get('band_filter'):
            result['source_band_filter'] = result.pop('band_filter')
        result.pop('raw_mask_path', None)
        result.pop('band_mask_path', None)
        result['metrics'] = measure_slices(image, edited, thickness_mm=result['metrics']['slice_thickness_mm'])
        result['lesion_topography'] = spatial_status()
        sitk.WriteImage(image, str(out / 'flair.nii.gz'))
        for key in ('svd_spatial', 'ms_topography', 'wmh_reference'):
            result.pop(key, None)
        if cancel is not None and cancel.is_set():
            raise BrainError('Manual recalculation cancelled.')
        write_lesion_report(result, image, edited, out)
        result['pdf_available'] = True
        (out / 'result.json').write_text(json.dumps(result, allow_nan=False), encoding='utf-8')
        return result
    result['metrics'] = measure_mask(image, edited)
    for key in ('svd_spatial', 'ms_topography', 'wmh_reference', 'lesion_topography'):
        result.pop(key, None)
    root = Path(result['_review_context_root']) if result.get('_review_context_root') else next(p for p in Path(manifest['source_mask']).parents if (p / 'flair.nii.gz').is_file())
    result['_review_context_root'] = str(root)
    indication = result.get('clinical_context', {}).get('primary_disease')
    if indication == 'svd':
        from .svd_assessment import enrich_svd
        result['svd_spatial'] = enrich_svd(result, root, cancel=cancel, progress=progress)
    from .ms_assessment import enrich_ms
    topography = enrich_ms(result, root, cancel=cancel, progress=progress)
    result['lesion_topography'] = {k: v for k, v in topography.items()
                                  if k not in ('conclusion', 'potential_brain_dis_support', 'diagnosis')}
    if indication == 'ms':
        result['ms_topography'] = topography
    if cancel is not None and cancel.is_set():
        raise BrainError('Manual recalculation cancelled.')
    write_lesion_report(result, image, edited, out)
    result['pdf_available'] = True
    (out / 'result.json').write_text(json.dumps(result, allow_nan=False), encoding='utf-8')
    return result


def brain_revision(directory, manifest, original, edited):
    """A separately identified binary-label measurement addendum, not posterior inference."""
    import numpy as np
    import SimpleITK as sitk
    from html import escape
    from .organized_report import PAGE, _table, write_paged_pdf
    from .volbrain_reference import range_text, scientific_reference_page
    from .runtime import sha256
    result = manifest['source_result']
    before, after = sitk.GetArrayFromImage(original), sitk.GetArrayFromImage(edited)
    voxel_ml = abs(float(np.linalg.det(np.array(edited.GetDirection()).reshape(3, 3)))) * float(np.prod(edited.GetSpacing())) / 1000
    original_counts = dict(zip(*np.unique(before, return_counts=True)))
    corrected_counts = dict(zip(*np.unique(after, return_counts=True)))
    rows = []
    for label in sorted(int(x) for x in original_counts if x):
        old, new = original_counts[label] * voxel_ml, corrected_counts.get(label, 0) * voxel_ml
        rows.append(dict(label=label, structure=manifest['label_names'][str(label)],
                         before_cm3=float(old), volume_cm3=float(new), volume_mm3=float(new * 1000),
                         method='Manually corrected binary labelmap'))
    out = directory / ('revision-' + uuid.uuid4().hex[:12]); out.mkdir()
    sitk.WriteImage(edited, str(out / 'corrected.nii.gz'))
    context = result.get('patient_context', {})
    identity = ' | '.join(str(context.get(k) or 'Not supplied') for k in ('patient_name', 'patient_id', 'study_date'))
    intro = ('<h1>Manual brain segmentation measurement addendum</h1><p>' + escape(identity) + '</p>'
             '<p>Volumes below are voxel-count measurements before and after manual boundary editing. '
             'They do not replace or relabel SynthSeg posterior estimates. Original inference is retained. '
             'Reference intervals, when available, retain the original examination age, sex and ICV; '
             'cross-method qualification remains pending. No exact scores or automated diagnosis.</p>')
    pages = []
    for start in range(0, len(rows), 16):
        table = [[r['structure'], f'{r["before_cm3"]:.3f}', f'{r["volume_cm3"]:.3f}',
                  f'{r["volume_cm3"]-r["before_cm3"]:+.3f}', range_text(result.get('normative', {}), r['structure'])]
                 for r in rows[start:start + 16]]
        pages.append(intro + _table(['Region', 'Before cm3', 'Corrected cm3', 'Change cm3', 'Reference cm3'],
                                   table, [32, 15, 16, 15, 22]))
    pages.append(scientific_reference_page())
    html = ('<html><head><meta name="brain-patient" content="' + escape(identity, quote=True) + '">'
            '<style>body,p,td,th,h1,h2{color:#223344}body{font-family:Arial;font-size:9pt;background:white}h1{font-size:16pt}th{background:#dfeaf0} '
            'td{border-bottom:1px solid #dddddd}</style></head><body>' + PAGE.join(pages) + '</body></html>')
    write_paged_pdf(html, out / 'report.pdf', title='AI-PACS | Manual brain measurement addendum | Review required')
    result.update(artifact_directory=str(out), manual_rows=rows, pdf_available=True,
                  manual_correction={'source_mask_sha256': manifest['source_sha256'],
                                     'corrected_mask_sha256': sha256(out / 'corrected.nii.gz')})
    (out / 'report.html').write_text(html, encoding='utf-8')
    (out / 'result.json').write_text(json.dumps(result, allow_nan=False), encoding='utf-8')
    return result
