"""Recommendation selection: rule data file, weakest-dim targeting, VDR trigger."""
import re

from aems.model import DimScore
from aems.recommend import load_rules, select


def _dim(d, level, capped=False, assessed=True):
    return DimScore(dim=d, raw_level=level if not capped else 4, level=level, capped=capped,
                    checks=(), outcome=None, assessed=assessed)


BASE = (_dim(1, 3), _dim(2, 3), _dim(3, 3), _dim(5, 3), _dim(8, 3), _dim(9, 3))


def _replace(dims, d, level, capped=False):
    return tuple(_dim(d, level, capped) if x.dim == d else x for x in dims)


def test_rules_file_is_versioned_dated_and_cited():
    rules = load_rules()
    assert rules["version"]
    assert re.match(r"\d{4}-\d{2}-\d{2}$", rules["dated"])
    for rule in rules["rules"]:
        assert rule["source"], rule["id"]
        assert rule["review_by"], rule["id"]
        assert rule["confidence"] in ("high", "medium", "low")


def test_targets_weakest_dims_first():
    dims = _replace(_replace(BASE, 3, 1), 9, 0)
    recs = select(dims, facts={}, rules=load_rules())
    assert len(recs) == 3
    assert recs[0].dim == 9
    assert recs[1].dim == 3


def test_at_most_three_moves_and_unique_rules():
    dims = tuple(_dim(d, 0) for d in (1, 2, 3, 5, 8, 9))
    recs = select(dims, facts={}, rules=load_rules())
    assert len(recs) == 3
    assert len({r.rule_id for r in recs}) == 3


def test_vdr_rule_fires_first_when_debt_is_high():
    dims = _replace(BASE, 9, 1)
    recs = select(dims, facts={"vdr": 4.2}, rules=load_rules())
    assert recs[0].rule_id == "sensors-before-agents"


def test_vdr_rule_silent_when_covered():
    recs = select(BASE, facts={"vdr": 0.5}, rules=load_rules())
    assert all(r.rule_id != "sensors-before-agents" for r in recs)


def test_capped_dim_gets_outcome_measurement_move():
    dims = _replace(BASE, 3, 2, capped=True)
    recs = select(dims, facts={}, rules=load_rules())
    assert any(r.rule_id == "prove-gates-run" for r in recs)


def test_stale_references_trigger_ablation_move():
    dims = _replace(BASE, 1, 2)
    recs = select(dims, facts={"stale_refs": 4}, rules=load_rules())
    assert any(r.rule_id == "prune-instructions" for r in recs)


def test_unassessed_dims_never_targeted():
    dims = BASE + (_dim(4, 0, assessed=False),)
    recs = select(dims, facts={}, rules=load_rules())
    assert all(r.dim != 4 for r in recs)
