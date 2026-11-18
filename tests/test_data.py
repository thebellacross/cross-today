import numpy as np
import pytest
from music.data import FAMILIES,OPERATIONS,signal,process

@pytest.mark.parametrize('family',list(FAMILIES))
def test_data_families_are_finite_repeatable_and_use_explicit_feed(family):
    feed=bytes(range(256))*10
    a,label=signal(np.random.default_rng(17),4096,kind=family,feed=feed)
    b,_=signal(np.random.default_rng(17),4096,kind=family,feed=feed)
    assert np.array_equal(a,b) and len(a)==4096 and np.isfinite(a).all()

@pytest.mark.parametrize('operation',sorted(set(OPERATIONS)))
def test_tape_operations_preserve_length_and_finite_samples(operation):
    signal=np.sin(np.arange(6000)*.03)*.2
    a,names=process(signal,np.random.default_rng(12),1,[operation])
    assert names and np.isfinite(a).all() and len(a)==len(signal)
