import json
import sys
from pathlib import Path
import numpy as np
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from channels import fit_h1,h1,deltas,fit_h2,h2


def times(n):
    return np.datetime64('2022-01-18T00:00','ns')+np.arange(n)*np.timedelta64(10,'s')


def test_h1_preserves_raw_scores_and_does_not_or_flags():
    training=np.column_stack([np.linspace(.1,.2,100),np.linspace(.8,.9,100),np.full(100,.3)])
    profile=fit_h1(training,times(100),['a','b','c'])
    raw=np.array([[.1,.898,.3],[.4,.8,np.nan]])
    result=h1(raw,json.loads(json.dumps(profile)))
    np.testing.assert_array_equal(result['absolute'],raw)
    assert result['absolute_flag'][0,1] and not result['context'][0,1]
    assert result['context'][1,0] and not result['absolute_flag'][1,0]
    assert not result['valid'][1,2] and np.isnan(result['margin'][1,2])
    assert profile['host_threshold'][0]==sorted(training[:,0])[98]
    assert not h1(np.array([profile['host_threshold']]),profile)['context'].any()


@pytest.mark.parametrize('bad',['2022-01-18T08:00','2022-01-18T16:00'])
def test_both_fits_reject_mixed_window_input(bad):
    ts=times(10);ts[-1]=np.datetime64(bad,'ns')
    with pytest.raises(ValueError,match='D1'):fit_h1(np.ones((10,1)),ts,['a'])
    with pytest.raises(ValueError,match='D1'):fit_h2(np.ones((10,1,3)),np.ones((10,1),bool),ts,['a'])


def test_deltas_require_exact_lag_and_all_seven_observations():
    raw=np.arange(20,dtype=float)[:,None,None]*np.ones((1,2,3))
    ds,valid=deltas(raw,times(20))
    assert not valid[:6].any() and np.isnan(ds[:6]).all()
    np.testing.assert_array_equal(ds[6:],np.ones((14,2,3))*6)
    available=np.ones(raw.shape,bool);available[8,0,1]=False
    _,valid=deltas(raw,times(20),available)
    assert not valid[8:15,0].any() and valid[15,0]
    assert valid[6:,1].all()
    ts=times(20);ts[9:]+=np.timedelta64(10,'s')
    _,valid=deltas(raw,ts)
    assert not valid[9:15].any() and valid[15].all()
    bad=times(20);bad[1]=np.datetime64('NaT')
    with pytest.raises(ValueError):deltas(raw,bad)


def test_h2_fixed_floor_centering_and_directions_hand_calculated():
    ds=np.broadcast_to([[2.,-3.,0.],[4.,-6.,0.]],(100,2,3)).copy()
    valid=np.ones((100,2),bool)
    profile=fit_h2(ds,valid,times(100),['a','b'])
    assert profile['epsilon']==[2.,3.,1.]
    assert profile['MAD']==[[0.,0.,0.],[0.,0.,0.]]
    assert profile['scale']==[[2.,3.,1.],[2.,3.,1.]]
    assert profile['positive_threshold']==profile['negative_threshold']==0
    query=ds[:3].copy();query[0,0]+=[2,-3,0]
    v=valid[:3].copy();v[1,0]=False
    result=h2(query,v,json.loads(json.dumps(profile)))
    assert result['positive'][0,0]==result['negative'][0,0]==1
    assert result['positive_flag'][0,0] and result['negative_flag'][0,0]
    assert np.isnan(result['u'][1,0]).all() and not result['valid'][1,0]
    assert not result['positive_flag'][2].any() and not result['negative_flag'][2].any()
    profile['scale'][0][0]=.5
    with pytest.raises(ValueError,match='scale'):h2(query,v,profile)


def test_h2_quantiles_are_pooled_strict_and_nearest_rank():
    ds=np.repeat(np.arange(100,dtype=float)[:,None,None],6,axis=1).reshape(100,2,3)
    v=np.ones((100,2),bool);profile=fit_h2(ds,v,times(100),['a','b'])
    med=np.median(ds,axis=0);mad=np.median(np.abs(ds-med),axis=0)
    eps=np.maximum(1.,np.sort(np.abs(ds).reshape(-1,3),axis=0)[99])
    expected=(ds-med)/np.maximum(1.4826*mad,eps)
    pos=np.maximum(expected,0).max(axis=2).ravel();neg=np.maximum(-expected,0).max(axis=2).ravel()
    assert profile['positive_threshold']==sorted(pos)[198]
    assert profile['negative_threshold']==sorted(neg)[198]
    result=h2(ds,v,profile)
    np.testing.assert_array_equal(result['positive_flag'],np.maximum(expected,0).max(axis=2)>profile['positive_threshold'])
