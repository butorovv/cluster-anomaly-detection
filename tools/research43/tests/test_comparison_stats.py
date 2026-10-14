import sys
from pathlib import Path
import numpy as np
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from comparison_stats import onsets,group_arrays,cooccurrence,partition_pairs,pair_stats,equal_budget


def test_pair_matrix_permutations_equal_direct_time_counts():
    x=np.array([[1,1,0,1,0,0],[0,1,1,0,1,1],[1,0,1,1,1,0]],bool)
    c=cooccurrence(x)
    for p in [np.arange(6).reshape(2,3),np.array([[0,2,4],[1,3,5]])]:
        k=x[:,p].sum(axis=2)
        assert partition_pairs(c,p)==int((k*(k-1)//2).sum())
    assert pair_stats(x,3)['all_pairs']==15
    assert pair_stats(x,3)['random_expectation']==6


def test_missing_and_initial_positive_are_not_new_onsets():
    x=np.array([[1,0],[1,1],[0,1],[1,1]],bool)
    v=np.ones_like(x);v[2,0]=False
    np.testing.assert_array_equal(onsets(x,v),[[0,0],[0,1],[0,0],[0,0]])
    k,n,s,e,local=group_arrays(x,v,size=1)
    assert np.isnan(s[2,0]) and not local[2].any()


def test_localized_support_separates_clusterwide_activity():
    x=np.array([[1,1,0,0],[1,1,1,1],[1,0,1,0]],bool)
    k,n,s,e,loc=group_arrays(x,np.ones_like(x),2)
    np.testing.assert_array_equal(loc,[[1,0],[0,0],[0,0]])
    assert e[0,0]==1 and e[1,0]==0


def test_equal_budget_common_availability_and_stable_ties():
    scores=np.array([[9,9,9],[8,7,6]],float);valid=np.ones(scores.shape,bool);valid[0,0]=False
    result,meta=equal_budget(scores,valid,.4)
    np.testing.assert_array_equal(result,[[0,1,1],[0,0,0]])
    assert meta['eligible']==5 and meta['count']==2 and meta['tied_at_cutoff']==2
    with pytest.raises(ValueError):equal_budget(scores,valid,0)
