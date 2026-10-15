import pytest
from zv.run import run, coverage_report
from zv.validate import validate_all, validate_recipe

CORRIDOR = {
    "rule_id": "ZO-014", "interpretation": "C-2 strip minus river easement",
    "recipe": [
        {"id": "road", "op": "select_roads", "class": "national", "name": "Maharlika Highway"},
        {"id": "strip", "op": "buffer", "input": "road", "width_m": 30, "measured_from": "centerline", "sides": "both"},
        {"id": "river", "op": "select_water", "kind": "river"},
        {"id": "ease", "op": "buffer", "input": "river", "width_m": 20},
        {"id": "zone", "op": "subtract", "a": "strip", "b": "ease"},
        {"op": "assign", "input": "zone", "zone_code_local": "C-2", "zone_code_national": "COMMERCIAL_MEDIUM", "layer": "base", "precedence": 50},
    ]}
RESIDUAL = {
    "rule_id": "ZO-001", "interpretation": "Everything else is R-1",
    "recipe": [
        {"id": "all", "op": "select_admin", "whole_lgu": True},
        {"id": "rest", "op": "residual", "area": "all", "zone_code_local": "R-1"},
        {"op": "assign", "input": "rest", "zone_code_local": "R-1", "zone_code_national": "RESIDENTIAL", "layer": "base", "precedence": 10},
    ]}


def test_corridor_with_residual_covers_lgu_without_gaps_or_overlaps(base):
    r = run(base, [RESIDUAL, CORRIDOR])
    assert set(r.base["zone_local"]) == {"C-2", "R-1"}
    rep = coverage_report(base.lgu, r.base)
    assert rep == {"gap_m2": 0.0, "overlap_m2": 0.0}
    c2 = r.base[r.base.zone_local == "C-2"].geometry.iloc[0]
    assert c2.area == pytest.approx(1000 * 60 - 40 * 60, rel=0.02)  # strip minus river easement crossing
    assert r.base[r.base.zone_local == "C-2"].rule_ids.iloc[0] == ["ZO-014"]


def test_run_is_deterministic(base):
    a = run(base, [RESIDUAL, CORRIDOR]).base.geometry.area.round(3).tolist()
    b = run(base, [CORRIDOR, RESIDUAL]).base.geometry.area.round(3).tolist()
    assert sorted(a) == sorted(b)


def test_missing_road_flags_and_stops_recipe(base):
    bad = {**CORRIDOR, "rule_id": "ZO-X", "recipe": [{**CORRIDOR["recipe"][0], "name": "Ghost Road"}] + CORRIDOR["recipe"][1:]}
    r = run(base, [RESIDUAL, bad])
    assert [f["rule_id"] for f in r.flags] == ["ZO-X"]
    assert set(r.base["zone_local"]) == {"R-1"}  # geometry never guessed


def test_null_recipe_goes_to_manual(base):
    r = run(base, [RESIDUAL, {"rule_id": "ZO-M", "recipe": None, "interpretation": "Refers to an unmapped landmark"}])
    assert r.manual == ["ZO-M"]


def test_overlay_never_cuts_base(base):
    ov = {"rule_id": "ZO-OV", "recipe": [
        {"id": "r", "op": "select_water", "kind": "river"}, {"id": "e", "op": "buffer", "input": "r", "width_m": 50},
        {"op": "assign", "input": "e", "zone_local": "FLOOD", "zone_code_local": "FLOOD", "layer": "overlay", "precedence": 99}]}
    r = run(base, [RESIDUAL, ov])
    assert coverage_report(base.lgu, r.base)["gap_m2"] == 0.0
    assert list(r.overlay["zone_local"]) == ["FLOOD"]


def test_higher_precedence_wins(base):
    hi = {**RESIDUAL, "rule_id": "HI", "recipe": [
        {"id": "a", "op": "select_admin", "names": ["Poblacion"]},
        {"op": "assign", "input": "a", "zone_code_local": "C-1", "layer": "base", "precedence": 90}]}
    r = run(base, [RESIDUAL, hi])
    assert r.base[r.base.zone_local == "R-1"].geometry.iloc[0].area == pytest.approx(500_000)


def test_validator_catches_problems():
    bad = {"rule_id": "B", "recipe": [
        {"id": "x", "op": "teleport"},
        {"id": "y", "op": "buffer", "input": "nope", "width_m": -5},
        {"op": "select_roads"}]}
    errs = validate_recipe(bad)
    joined = " | ".join(errs)
    assert "unknown operation" in joined and "unknown step 'nope'" in joined
    assert "positive number of metres" in joined and "last step must be assign" in joined


def test_validator_duplicates_and_null_needs_reason():
    assert any("duplicate rule_id" in e for e in validate_all([CORRIDOR, CORRIDOR]))
    assert validate_recipe({"rule_id": "N", "recipe": None})


def test_point_feature_assign_flags_instead_of_vanishing(base):
    rule = {"rule_id": "PT", "interpretation": "site", "recipe": [
        {"id": "s", "op": "select_feature", "name": "City Hall"},
        {"op": "assign", "input": "s", "zone_code_local": "IN", "layer": "base", "precedence": 70}]}
    r = run(base, [rule])
    assert [f["rule_id"] for f in r.flags] == ["PT"] and r.base.empty
