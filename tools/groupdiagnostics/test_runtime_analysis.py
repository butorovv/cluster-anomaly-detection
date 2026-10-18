import pytest
from tools.groupdiagnostics.analyze_runtime import dependency


def test_contingency_with_known_overlap_and_conditionals():
    d=dependency([True,True,False,False],[True,False,True,False])
    assert [d[k] for k in ['joint','r_only','b_only','neither']]==[1,1,1,1]
    assert d['phi']==0
    assert d['jaccard']==pytest.approx(1/3)
    assert d['p_b_given_r']==d['p_r_given_b']==.5


def test_identical_nonconstant_signals_are_fully_dependent():
    d=dependency([True,False,True],[True,False,True])
    assert d['phi']==d['jaccard']==1


def test_constant_negative_signals_do_not_invent_phi_or_jaccard():
    d=dependency([False,False],[False,False])
    assert d['phi'] is None and d['jaccard'] is None
    assert d['p_b_given_r'] is None and d['p_r_given_b'] is None
