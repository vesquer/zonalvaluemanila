import pytest
from shapely.geometry import LineString, box
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


def test_select_water(base):
    assert ops.select_water(base, kind="river").length == 1000
    with pytest.raises(SelectionEmpty):
        ops.select_water(base, kind="lake")


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


def test_buffer_both_sides_and_row_edge(base):
    road = ops.select_roads(base, name="Maharlika Highway")
    assert ops.buffer(base, road, width_m=30).area == pytest.approx(1000 * 60, rel=0.01)
    wide = ops.buffer(base, road, width_m=30, measured_from="row_edge", road_class="primary")
    assert wide.area > ops.buffer(base, road, width_m=30).area  # ROW half width (10 m) added


def test_buffer_single_side(base):
    road = ops.select_roads(base, name="Maharlika Highway")
    one = ops.buffer(base, road, width_m=30, sides="left")
    assert one.area == pytest.approx(1000 * 30, rel=0.01)
    assert one.bounds[1] >= 500 - 1 or one.bounds[3] <= 500 + 1  # all on one side


def test_buffer_rejects_nonpositive(base):
    with pytest.raises(ValueError):
        ops.buffer(base, box(0, 0, 1, 1), width_m=0)


def test_between_encloses(base):
    a = LineString([(0, 0), (0, 100)]); b = LineString([(100, 0), (100, 100)])
    c = LineString([(0, 0), (100, 0)]); d = LineString([(0, 100), (100, 100)])
    assert ops.between(base, a, b, c, d).area == pytest.approx(10_000)
    with pytest.raises(SelectionEmpty):
        ops.between(base, a, b)


def test_set_ops():
    a, b = box(0, 0, 10, 10), box(5, 0, 15, 10)
    assert ops.union(a, b).area == 150
    assert ops.intersect(a, b).area == 50
    assert ops.subtract(a, b).area == 50


def test_clip(base):
    g = box(-100, -100, 100, 100)
    assert ops.clip(base, g, to="lgu").area == 10_000
    assert ops.clip(base, box(0, 0, 900, 900), to="barangay", names=["San Isidro"]).area == 500 * 900


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


def test_buffer_compass_sides(base):
    road = ops.select_roads(base, name="Maharlika Highway")  # runs east-west at y=500
    n = ops.buffer(base, road, width_m=30, sides="north")
    assert n.bounds[1] >= 499 and n.area == pytest.approx(30_000, rel=0.01)
    s = ops.buffer(base, road, width_m=30, sides="south")
    assert s.bounds[3] <= 501
    road2 = ops.select_roads(base, name="Side St")  # north-south at x=500
    e = ops.buffer(base, road2, width_m=30, sides="east")
    assert e.bounds[0] >= 499


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
