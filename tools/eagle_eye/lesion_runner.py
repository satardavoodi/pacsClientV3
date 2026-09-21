"""Pinned LST-AI Windows adapter, copied into the isolated Eagle Eye payload."""
import inspect
import os
from pathlib import Path
import runpy
import socket
import sys


class QuotedPath(str):
    """Greedy's command-string parser needs quotes around paths containing spaces."""
    def __format__(self, spec):
        if '"' in self:
            raise ValueError('Unsupported quote in image path')
        return '"' + str(self).replace('\\', '/') + '"'


def adapt_registration(module):
    def wrap(function):
        signature = inspect.signature(function)
        def call(*args, **kwargs):
            bound = signature.bind(*args, **kwargs)
            for key, value in bound.arguments.items():
                if isinstance(value, str):
                    bound.arguments[key] = QuotedPath(value)
            return function(*bound.args, **bound.kwargs)
        return call
    for name in ('mni_registration', 'rigid_reg', 'apply_warp_label', 'apply_warp_interp'):
        setattr(module, name, wrap(getattr(module, name)))


def main():
    root = Path(__file__).resolve().parent
    job = Path(sys.argv[1]).resolve()
    os.chdir(job)
    os.environ['LST_AI_DATA_DIR'] = str(root / 'data')
    def offline(*args, **kwargs):
        raise RuntimeError('Offline lesion runtime: required assets must be installed before analysis.')
    socket.socket.connect = offline
    socket.socket.connect_ex = offline
    import torch
    torch.set_num_threads(2)
    torch.set_num_interop_threads(1)
    import lst_ai.register as registration
    adapt_registration(registration)
    sys.argv = ['lst', '--t1', 't1.nii.gz', '--flair', 'flair.nii.gz', '--output', 'output',
                '--temp', 'work', '--segment_only', '--device', 'cpu', '--threads', '2',
                '--threshold', '0.5', '--lesion_threshold', '0', '--probability_map']
    runpy.run_path(str(root / 'python/Scripts/lst'), run_name='__main__')


if __name__ == '__main__':
    main()
