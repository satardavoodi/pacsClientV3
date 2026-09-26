"""Offline MindGlide subprocess entry point, copied into the optional engine bundle."""
import multiprocessing
import os
from pathlib import Path
import sys

ENGINE = Path(__file__).resolve().parent
sys.path.insert(0, str(ENGINE / 'site-packages-v1'))
os.environ['HF_HUB_OFFLINE'] = '1'
os.environ['OMP_NUM_THREADS'] = '2'
os.environ['MKL_NUM_THREADS'] = '2'


def main():
    import torch
    from mindglide.infer import segment
    torch.set_num_threads(2)
    torch.set_num_interop_threads(1)
    torch.manual_seed(1729)
    directory = Path(sys.argv[1]).resolve()
    segment(str(directory / 'flair.nii.gz'), str(directory / 'anatomy.nii.gz'),
            device='cpu', model_path=str(ENGINE / 'model.pt'), sw_batch_size=1)
    if not (directory / 'anatomy.nii.gz').is_file():
        raise RuntimeError('MindGlide did not produce its native segmentation.')


if __name__ == '__main__':
    multiprocessing.freeze_support()
    main()
