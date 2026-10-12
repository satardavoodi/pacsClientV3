"""Isolated offline MR vertebral-body inference in the pinned lumbar runtime."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys


def verify_manifest(manifest):
    """Seal the complete reviewed supplement inventory, not a mutable checksum list."""
    files = manifest.get('files', [])
    inventory = json.dumps(sorted(files, key=lambda item:item['path']), sort_keys=True, separators=(',', ':')).encode()
    if ((manifest.get('task'), manifest.get('dataset'), manifest.get('engine')) != ('total_mr', 850, '2.14.0')
            or hashlib.sha256(inventory).hexdigest() !=
            'c855575de62a34bf2cb3204c18063a4629bd2b595485dde4adeeb05142e40de2'):
        raise ValueError('Unsupported or modified marrow-body model manifest.')


def deny_network(event, args):
    if event in {'socket.connect','socket.connect_ex','socket.getaddrinfo','socket.bind'}:
        raise PermissionError('Marrow inference is offline.')


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--assets',type=Path,required=True)
    parser.add_argument('--job',type=Path,required=True)
    args=parser.parse_args()
    root,job=args.assets.resolve(strict=True),args.job.resolve(strict=True)
    manifest=json.loads((root/'manifest.json').read_text())
    verify_manifest(manifest)
    for item in manifest['files']:
        path=(root/item['path']).resolve(strict=True)
        if not path.is_relative_to(root) or hashlib.file_digest(path.open('rb'),'sha256').hexdigest()!=item['sha256']:
            raise ValueError('Marrow-body asset integrity failed.')
    state=job/'engine-state';state.mkdir(exist_ok=True)
    (state/'config.json').write_text(json.dumps({'totalseg_id':'offline','send_usage_stats':False,'prediction_counter':0}))
    os.environ.update(TOTALSEG_HOME_DIR=str(state),TOTALSEG_WEIGHTS_PATH=str(root/'weights'),
        nnUNet_raw=str(root/'weights'),nnUNet_preprocessed=str(root/'weights'),nnUNet_results=str(root/'weights'),
        OMP_NUM_THREADS='2',MKL_NUM_THREADS='2',nnUNet_compile='false',HF_HUB_OFFLINE='1',
        TEMP=str(job),TMP=str(job),DO_NOT_TRACK='1')
    sys.addaudithook(deny_network)
    import importlib.metadata
    import numpy as np
    import nibabel as nib
    import torch
    if importlib.metadata.version('TotalSegmentator')!='2.14.0':
        raise ValueError('Unexpected body inference runtime.')
    torch.set_num_threads(2)
    from totalsegmentator.config import setup_nnunet
    from totalsegmentator.nnunet import nnUNet_predict_image
    setup_nnunet()
    # Use the installed high-resolution MR organs model directly. It includes
    # vertebral bodies and discs; no rough crop model or online download is needed.
    image=nib.load(job/'input.nii.gz')
    result,_,_=nnUNet_predict_image(image,None,[850],model='3d_fullres',folds=[0],
        trainer='nnUNetTrainer_2000epochs_NoMirroring',tta=False,multilabel_image=True,
        resample=1.5,task_name='total_mr',roi_subset=['vertebrae'],device='cpu',
        nr_threads_resampling=1,nr_threads_saving=1,quiet=True,skip_saving=True)
    if result.shape!=image.shape or not np.allclose(result.affine,image.affine,atol=1e-4):
        raise ValueError('Body inference geometry changed.')
    data=np.asarray(result.dataobj)
    if not np.isin(data,[0,19]).all():
        raise ValueError('Unexpected MR body label.')
    nib.save(nib.Nifti1Image((data==19).astype(np.uint8),image.affine),job/'body.nii.gz')


if __name__=='__main__':
    main()
