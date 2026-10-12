"""Sparse scoring preserves full-map tile ownership and candidate scores."""
import contextlib
import sys
from types import SimpleNamespace
import numpy as np
import pytest
from tools.eagle_eye import calcium_candidate as worker

class Tensor(np.ndarray):
    def numpy(self):return np.asarray(self)

class Net:
    def __init__(self):self.calls=0
    def __call__(self,tensor):
        self.calls+=1
        plane=(tensor[0,0]+1)/8 + (float(tensor.mean())+1)/8
        return plane[None,None].view(Tensor)

@pytest.mark.parametrize('shape',[(512,512),(777,1025),(1024,1400)])
def test_sparse_matches_last_writer_edges(shape,monkeypatch):
    monkeypatch.setitem(sys.modules,'torch',SimpleNamespace(inference_mode=contextlib.nullcontext,from_numpy=lambda a:a.view(Tensor)))
    im=np.random.default_rng(42).random(shape,dtype=np.float32)
    xy=np.array([[0,0],[shape[1]-1,shape[0]-1],[384,384],[500,500]],dtype=float)
    full=worker.probability_map(im,Net());net=Net()
    scores,stats=worker.candidate_scores(im,net,xy)
    np.testing.assert_array_equal(scores,full[xy[:,1].astype(int),xy[:,0].astype(int)])
    assert net.calls==stats['evaluated_tiles']<=stats['total_tiles']
    if shape!=(512,512):assert stats['evaluated_tiles']<stats['total_tiles']


def test_empty_candidates_do_not_run_network():
    net=Net();scores,stats=worker.candidate_scores(np.zeros((777,1025),np.float32),net,np.empty((0,2)))
    assert len(scores)==0 and net.calls==stats['evaluated_tiles']==0


@pytest.mark.parametrize('xy',[[[-1,0]],[[512,0]],[[1.2,2]],[[float('nan'),0]]])
def test_invalid_sampling_is_rejected(xy):
    with pytest.raises(ValueError):worker.candidate_scores(np.zeros((512,512),np.float32),Net(),np.array(xy))
