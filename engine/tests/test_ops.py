import pytest
from shapely.geometry import box
from zv import ops
from zv.ops import SelectionEmpty


def test_select_roads_by_name_and_class(base):
    assert ops.select_roads(base, name="maharlika highway").length == 1000
    assert ops.select_roads(base, cls="national").length == 1000  # primary is the national proxy
    assert ops.select_roads(base, cls="tertiary").length == 1000


def test_select_roads_from_to(base):
    g = ops.select_roads(base, name="Maharlika Highway", frm="San Isidro", to="Poblacion")
    assert g.length == pytest.approx(1000)
    g = ops.select_roads(base, name="Maharlika Highway", frm="San Isidro")
    assert g.length == pytest.approx(500, abs=1)  # hull of San Isidro only


def test_select_roads_missing_stops(base):
    with pytest.raises(SelectionEmpty):
        ops.select_roads(base, name="Nowhere Road")


def test_select_admin(base):
    assert ops.select_admin(base, names=["Poblacion"]).area == 500_000
    assert ops.select_admin(base, pcodes=["B1"]).area == 500_000
    assert ops.select_admin(base, whole_lgu=True).area == 1_000_000
    with pytest.raises(SelectionEmpty):
        ops.select_admin(base, names=["Atlantis"])


def test_select_feature(base):
    assert ops.select_feature(base, name="City Hall").geom_type == "Point"
    with pytest.raises(SelectionEmpty):
        ops.select_feature(base, name="Gone")


def test_union():
    a, b = box(0, 0, 10, 10), box(5, 0, 15, 10)
    assert ops.union(a, b).area == 150


def test_approximate_road_name_is_logged(base):
    base.roads.loc[0, "name"] = "San Felipe-Pacol-Carolina-Panicuason Road"
    assert ops.select_roads(base, name="Carolina-Panicuason Road").length == 1000
    assert any("approximate name match" in m for m in base.match_log)
    base.match_log.clear()
    ops.select_roads(base, name="Side St")
    assert base.match_log == []  # exact matches are not logged


def test_ambiguous_approximate_name_flags_instead_of_guessing(base):
    base.roads.loc[0, "name"] = "Ramon Felipe Jr. Street"
    base.roads.loc[1, "name"] = "Felipe Ramon Avenue"
    with pytest.raises(ops.AmbiguousName):
        ops.select_roads(base, name="Ramon Felipe Road")


def test_select_roads_between_two_roads(base):
    g = ops.select_roads(base, name="Side St", frm="Maharlika Highway", to="Maharlika Highway")
    assert 0 < g.length < 1000  # clipped to the crossing, not the whole street
    g2 = ops.select_roads(base, name="Maharlika Highway", frm="Side St")
    assert g2.length < 1000


def test_abbreviations_and_case_variants(base):
    base.roads.loc[0, "name"] = "Scout Tobias Street"
    assert ops.select_roads(base, name="Sct. Tobias Street,").length == 1000
    base.features.loc[len(base.features)] = ["Saint Joseph The Worker Parish Church", base.features.geometry.iloc[0].buffer(5)]
    base.features.loc[len(base.features)] = ["Saint Joseph the Worker Parish Church", base.features.geometry.iloc[0].buffer(7)]
    assert ops.select_feature(base, name="St. Joseph the Worker Parish Church").area > 0  # variants, not ambiguity


def test_loose_barangay_name_is_not_an_end_limit(base):
    base.roads.loc[1, "name"] = "San Isidro Avenue"  # looks like the barangay "San Isidro" but is a road
    g = ops.select_roads(base, name="Maharlika Highway", frm="San Isidro Avenue")
    assert 0 < g.length < 1000  # used the road crossing, did not crash looking up an admin


def test_single_word_names_do_not_match_loosely_and_roads_beat_sites(base):
    base.features.loc[len(base.features)] = ["Side Bar Cafe", base.features.geometry.iloc[0].buffer(5)]
    with pytest.raises(SelectionEmpty):
        ops.select_feature(base, name="Side Street")  # one significant word -> exact only
    # a road limit resolves to the road "Side St", not the cafe
    g = ops.select_roads(base, name="Maharlika Highway", frm="Side St")
    assert 0 < g.length < 1000
