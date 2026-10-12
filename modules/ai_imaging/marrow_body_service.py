"""Server worker invocation; never imported for client-side model execution."""
import os
from pathlib import Path
import subprocess
import time


def run_body(bundle, assets, image, directory, cancel, timeout=1800):
    import SimpleITK as sitk
    root=Path(directory)/'body-engine';root.mkdir(parents=True)
    sitk.WriteImage(image,str(root/'input.nii.gz'))
    command=[str(Path(bundle)/'python/python.exe'),'-I','-B',
             str(Path(__file__).with_name('marrow_body_worker.py')),'--assets',str(Path(assets).resolve()),'--job',str(root.resolve())]
    env=os.environ.copy()
    for key in list(env):
        if key.startswith(('PYTHON','QT_')):
            env.pop(key)
    flags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0
    with (root/'engine.log').open('wb') as log:
        process=subprocess.Popen(command,cwd=root,env=env,stdout=log,stderr=log,creationflags=flags)
        started=time.monotonic()
        try:
            while process.poll() is None:
                if cancel.is_set() or time.monotonic()-started>timeout:
                    raise RuntimeError('Body inference cancelled or timed out.')
                time.sleep(.1)
            if process.returncode or cancel.is_set() or not (root/'body.nii.gz').is_file():
                raise RuntimeError('Body inference failed; inspect the protected engine log.')
        finally:
            if process.poll() is None:
                if os.name=='nt':
                    subprocess.run(['taskkill','/PID',str(process.pid),'/T','/F'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=flags)
                else:
                    process.terminate()
                process.wait(timeout=15)
    result=sitk.ReadImage(str(root/'body.nii.gz'))
    for getter in ('GetSize','GetOrigin','GetSpacing','GetDirection'):
        import numpy as np
        if not np.allclose(getattr(result,getter)(),getattr(image,getter)(),atol=1e-4):
            raise ValueError('Body mask geometry differs from reference.')
    return sitk.GetArrayFromImage(result)
