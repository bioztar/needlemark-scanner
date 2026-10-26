"""Scoring rules: cumulative ladder, outcome cap, weakest link."""
from aems.model import Check, DimScore, OutcomeCheck
from aems.scoring import overall, score_dim


def _checks(passed_by_level: dict[int, bool]) -> tuple[Check, ...]:
    return tuple(Check(level=lvl, label=f"L{lvl}", passed=ok) for lvl, ok in passed_by_level.items())


OK = OutcomeCheck(passed=True, label="rework healthy")
NO = OutcomeCheck(passed=False, label="insufficient outcome evidence")


def test_ladder_is_cumulative_gap_stops_climb():
    dim = score_dim(1, _checks({1: True, 2: False, 3: True, 4: True}), OK)
    assert dim.raw_level == 1
    assert dim.level == 1
    assert not dim.capped


def test_level_requires_every_check_at_that_level():
    checks = (
        Check(1, "a", True), Check(2, "b", True), Check(2, "c", False), Check(3, "d", True),
    )
    assert score_dim(2, checks, OK).raw_level == 1


def test_no_checks_passed_is_level_zero():
    assert score_dim(3, _checks({1: False, 2: True}), OK).level == 0


def test_cap_fires_without_outcome_evidence():
    dim = score_dim(3, _checks({1: True, 2: True, 3: True, 4: True}), NO)
    assert dim.raw_level == 4
    assert dim.level == 2
    assert dim.capped
    assert dim.label == "presence, not maturity"


def test_cap_fires_when_outcome_missing_entirely():
    dim = score_dim(3, _checks({1: True, 2: True, 3: True}), None)
    assert dim.level == 2 and dim.capped


def test_cap_does_not_fire_with_outcome_evidence():
    dim = score_dim(3, _checks({1: True, 2: True, 3: True, 4: True}), OK)
    assert dim.level == 4
    assert not dim.capped


def test_cap_irrelevant_at_level_two_or_below():
    dim = score_dim(8, _checks({1: True, 2: True, 3: False}), NO)
    assert dim.level == 2
    assert not dim.capped


def _dim(d, level, assessed=True):
    return DimScore(dim=d, raw_level=level, level=level, capped=False, checks=(), outcome=None, assessed=assessed)


def test_overall_is_weakest_link_with_median():
    dims = (_dim(1, 4), _dim(2, 3), _dim(3, 1), _dim(5, 4), _dim(8, 2), _dim(9, 3))
    low, med, weakest = overall(dims)
    assert low == 1
    assert med == 3.0
    assert weakest == (3,)


def test_overall_excludes_unassessed_dims():
    dims = (_dim(1, 3), _dim(2, 3), _dim(4, 0, assessed=False), _dim(6, 0, assessed=False))
    low, med, weakest = overall(dims)
    assert low == 3
    assert med == 3.0
    assert weakest == (1, 2)


def test_autonomy_trap_does_not_average_up():
    dims = (_dim(5, 4), _dim(3, 1))
    low, med, _ = overall(dims)
    assert low == 1
    assert med == 2.5
