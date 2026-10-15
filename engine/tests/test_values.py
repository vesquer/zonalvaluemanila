import pytest
from shapely.geometry import LineString, box
from zv import ops
from zv.ops import SelectionEmpty
from zv.run import run_values
from zv.validate import validate_recipe


def street_row(rid, name, value, cls="RR", brgy="San Isidro", **sel):
    return {"rule_id": rid, "barangay": brgy, "rdo": "38", "interpretation": "street row",
            "source": {"text": f"{name.upper()} | {cls} | {value}"},
            "recipe": [{"id": "s", "op": "select_roads", "name": name, "within": brgy, **sel},
                       {"op": "assign_value", "input": "s", "value_php_sqm": value, "class_code": cls, "applies_to": "street",
                        "rdo": "38", "department_order": "033-2024"}]}


def interior_row(rid, value, cls="RR", brgy="San Isidro"):
    return {"rule_id": rid, "barangay": brgy, "rdo": "38", "interpretation": "all other streets",
            "source": {"text": f"ALL OTHER STREETS | {cls} | {value}"},
            "recipe": [{"id": "b", "op": "select_admin", "names": [brgy]},
                       {"op": "assign_value", "input": "b", "value_php_sqm": value, "class_code": cls, "applies_to": "interior"}]}


@pytest.fixture
def vbase(base):
    base.roads.loc[len(base.roads)] = ["residential", "Albay Street", LineString([(100, 0), (100, 1000)])]
    return base


def test_street_and_interior_rows_build_end_to_end(vbase):
    r = run_values(vbase, [street_row("V1", "Maharlika Highway", 84000), interior_row("V2", 28000)])
    assert r.flags == [] and r.conflicts == []
    s = r.streets.iloc[0]
    assert s.geometry.geom_type in ("LineString", "MultiLineString")
    assert s.geometry.length == pytest.approx(500 + ops.EDGE_M, abs=1)  # kept to San Isidro plus the edge allowance
    assert (s.value_php_sqm, s.class_code, s.department_order) == (84000, "RR", "033-2024")
    assert s.description == "MAHARLIKA HIGHWAY | RR | 84000"  # schedule text kept verbatim for the popup
    a = r.areas.iloc[0]
    assert a.applies_to == "interior" and a.geometry.area == pytest.approx(500_000)


def test_one_word_name_matches_only_inside_a_barangay(vbase):
    assert ops.select_roads(vbase, name="ALBAY", within="San Isidro").length == pytest.approx(1000)
    with pytest.raises(SelectionEmpty):
        ops.select_roads(vbase, name="ALBAY")  # city-wide, one word stays exact-only
    with pytest.raises(SelectionEmpty):
        ops.select_roads(vbase, name="ALBAY", within="Poblacion")  # not in that barangay


def test_alias_lookup(vbase):
    with pytest.raises(SelectionEmpty):
        ops.select_roads(vbase, name="M. HI-WAY", within="San Isidro")
    vbase.aliases = ops.alias_map({"M. HI-WAY": "Maharlika Highway", "_note": "ignored"})
    assert ops.select_roads(vbase, name="M. HI-WAY", within="San Isidro").length > 0
    assert "_note" not in vbase.aliases


def test_hi_way_and_drive_spellings(vbase):
    vbase.roads.loc[len(vbase.roads)] = ["residential", "Bellevue Drive", LineString([(200, 0), (200, 1000)])]
    assert ops.select_roads(vbase, name="MAHARLIKA HI-WAY").length == 1000
    assert ops.select_roads(vbase, name="BELLEVUE DR.", within="San Isidro").length == pytest.approx(1000)


def test_soft_limits_keep_whole_street_and_log(vbase):
    with pytest.raises(SelectionEmpty):
        ops.select_roads(vbase, name="Albay", within="San Isidro", frm="Nowhere", to="Side St")
    g = ops.select_roads(vbase, name="Albay", within="San Isidro", frm="Nowhere", to="Side St", soft_limits=True)
    assert g.length == pytest.approx(1000)
    assert any("not found for 'Albay'" in m for m in vbase.match_log)
    r = run_values(vbase, [street_row("V1", "Albay", 30000, frm="Nowhere", to="Side St", soft_limits=True)])
    assert "not found for 'Albay'" in r.streets.iloc[0].notes  # notes travel with the row


def test_limits_cut_the_street_between_crossings(vbase):
    vbase.roads.loc[len(vbase.roads)] = ["residential", "Davao", LineString([(0, 800), (400, 800)])]
    g = ops.select_roads(vbase, name="Albay", within="San Isidro", frm="Maharlika Highway", to="DAVAO")
    assert g.length == pytest.approx(300, abs=20)  # y=500 to y=800, plus the 8 m crossing allowance at each end


def test_conflicting_values_are_flagged_not_resolved(vbase):
    rows = [street_row("A", "Albay", 34000), street_row("B", "Albay", 38000),
            street_row("C", "Albay", 50000, cls="CR"),   # other class: no conflict
            street_row("D", "Albay", 34000)]             # same value: a duplicate, not a conflict
    r = run_values(vbase, rows)
    assert [(c["a"], c["b"]) for c in r.conflicts] == [("A", "B"), ("B", "D")]
    assert len(r.streets) == 4  # nothing dropped
    assert r.streets.set_index("rule_id").loc["B", "conflict_with"] == "A,D"


def test_interior_conflict_and_point_site_flag(vbase):
    r = run_values(vbase, [interior_row("I1", 28000), interior_row("I2", 30000)])
    assert len(r.conflicts) == 1 and r.conflicts[0]["applies_to"] == "interior"
    site = {"rule_id": "S", "barangay": "Poblacion", "interpretation": "subdivision", "source": {"text": "CITY HALL | RR | 1"},
            "recipe": [{"id": "s", "op": "select_feature", "name": "City Hall", "within": "Poblacion"},
                       {"op": "assign_value", "input": "s", "value_php_sqm": 1, "class_code": "RR", "applies_to": "area"}]}
    r = run_values(vbase, [site])
    assert [f["rule_id"] for f in r.flags] == ["S"] and "only a point" in r.flags[0]["flag"]


def test_unmatched_manual_and_out_of_scope_are_kept_apart(vbase):
    rows = [street_row("U", "Ghost Street", 1000),
            {"rule_id": "M", "recipe": None, "interpretation": "townhouse lots cannot be located"},
            {"rule_id": "O", "recipe": None, "interpretation": "condominium unit", "status": "out_of_scope"}]
    r = run_values(vbase, rows)
    assert ([f["rule_id"] for f in r.flags], r.manual, r.skipped) == (["U"], ["M"], ["O"])


def test_validator_checks_assign_value():
    bad = {"rule_id": "B", "recipe": [{"id": "s", "op": "select_admin", "whole_lgu": True},
                                      {"op": "assign_value", "input": "s", "value_php_sqm": -1, "class_code": "RR", "applies_to": "lot"}]}
    joined = " | ".join(validate_recipe(bad))
    assert "positive number of PHP" in joined and "applies_to must be" in joined
    early = {"rule_id": "E", "recipe": [{"id": "s", "op": "select_admin", "whole_lgu": True},
                                        {"op": "assign_value", "input": "s", "value_php_sqm": 1, "class_code": "RR", "applies_to": "interior"},
                                        {"op": "buffer", "input": "s", "width_m": 5}]}
    assert any("only be the last step" in e for e in validate_recipe(early))


def test_initials_accents_and_scoped_aliases(vbase):
    vbase.roads.loc[len(vbase.roads)] = ["residential", "Tomás Argüelles Street", LineString([(300, 0), (300, 1000)])]
    vbase.roads.loc[len(vbase.roads)] = ["residential", "S. Santos Street", LineString([(700, 0), (700, 1000)])]
    assert ops.select_roads(vbase, name="TOMAS ARGUELLES ST.").length == 1000          # accents folded
    assert ops.select_roads(vbase, name="T. ARGUELLES ST.").length == 1000             # initial = first letter
    with pytest.raises(ops.AmbiguousName):
        vbase.roads.loc[len(vbase.roads)] = ["residential", "Teodoro Argüelles Street", LineString([(350, 0), (350, 1000)])]
        ops.select_roads(vbase, name="T. ARGUELLES ST.")                                # two T. Argüelles: flag, never pick
    vbase.aliases = ops.alias_map({"SANTOS ST. @ Poblacion": "S. Santos Street"})
    assert ops.select_roads(vbase, name="SANTOS ST.", within="Poblacion").length > 0
    with pytest.raises(SelectionEmpty):
        ops.select_roads(vbase, name="SANTOS ST.")  # the alias holds only inside Poblacion


def test_plain_name_beats_its_extension_but_different_people_stay_ambiguous(vbase):
    vbase.roads.loc[len(vbase.roads)] = ["residential", "Calla Lily Extension", LineString([(300, 0), (300, 400)])]
    vbase.roads.loc[len(vbase.roads)] = ["residential", "Calla Lily Street", LineString([(300, 600), (300, 1000)])]
    assert ops.select_roads(vbase, name="CALLA LILY", within="San Isidro").length == pytest.approx(400)
    vbase.roads.loc[len(vbase.roads)] = ["residential", "Luis Pariñas Street", LineString([(200, 0), (200, 400)])]
    vbase.roads.loc[len(vbase.roads)] = ["residential", "Rafael Pariñas Street", LineString([(200, 600), (200, 1000)])]
    with pytest.raises(ops.AmbiguousName):
        ops.select_roads(vbase, name="P. PARINAS", within="San Isidro")


def test_street_just_outside_an_indicative_outline_is_kept_and_noted(vbase):
    vbase.roads.loc[len(vbase.roads)] = ["residential", "Andromeda Street", LineString([(580, 0), (580, 1000)])]
    g = ops.select_roads(vbase, name="ANDROMEDA ST.", within="San Isidro")  # 80 m past San Isidro's edge
    assert g.length == pytest.approx(1000)
    assert any("lies outside the San Isidro outline" in m for m in vbase.match_log)
