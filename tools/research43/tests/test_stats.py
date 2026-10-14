import sys
from pathlib import Path
import numpy as np
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from stats import temporal, regime_duration, cluster_ci, control_center


def test_closed_windows_distinguish_existing_signal_and_new_onset():
    x = np.zeros(80,bool)
    x[8:35] = True
    r = temporal(x,20,0,12)
    assert r['any'] and r['active_before'] and not r['post_onset']
    x[:] = False
    x[32:35] = True  # inclusive +120 endpoint
    r = temporal(x,20,0,12)
    assert r['fresh_onset'] and r['latency_seconds']==120
    assert r['onset_duration_seconds']==30
    x[19]=True
    assert not temporal(x,20,0,12)['fresh_onset']
    assert temporal(x,20,0,12)['post_onset']


def test_pre_only_and_censoring_are_explicit():
    x=np.zeros(60,bool); x[17:19]=True
    assert temporal(x,20,-3,18)['pre_only']
    x[:]=False; x[30:]=True
    r=temporal(x,20)
    assert r['fresh_onset'] and r['onset_run_censored']
    with pytest.raises(ValueError): temporal(x,5)


def test_midpoint_regime_return_and_wrong_direction():
    x=np.r_[np.zeros(20),np.ones(4)*10,np.zeros(10)]
    assert regime_duration(x,20,0,10,'rise')==dict(seconds=40,censored=False)
    assert regime_duration(x,20,10,0,'rise')['seconds'] is None
    assert regime_duration(np.ones(40)*10,20,0,10,'rise')==dict(seconds=200,censored=True)


def test_cluster_bootstrap_keeps_all_rows_of_cluster_together():
    # Cluster A contributes four positives; B contributes one negative.
    r=cluster_ci([1,1,1,1,-1],['A','A','A','A','B'],1999,43)
    assert r['clusters']==2 and r['difference']==pytest.approx(.6)
    assert r['interval95']==[-1,1]
    assert r==cluster_ci([1,1,1,1,-1],['A','A','A','A','B'],1999,43)


def test_matching_uses_only_power_host_hour_and_full_coverage():
    p=np.ones((100,1,3))*10; cov=np.zeros((100,1),bool)
    cov[38:60,0]=True
    p[20,0,0]=10; p[72,0,0]=10
    picked=control_center(50,0,0,p,[5,15],cov,set(),100)
    assert picked==72  # pre120 starts at 60, after the excluded interval
    picked2=control_center(50,0,0,p,[5,15],cov,{(72,0)},100)
    assert picked2!=72
    cov[:]=True
    assert control_center(50,0,0,p,[5,15],cov,set(),100) is None
