import geopandas as gpd
import pytest
from shapely.geometry import LineString, Point, box
from zv.base import Base

CRS = 32651


@pytest.fixture
def base() -> Base:
    lgu = box(0, 0, 1000, 1000)
    roads = gpd.GeoDataFrame({
        "class": ["primary", "tertiary"], "name": ["Maharlika Highway", "Side St"],
        "geometry": [LineString([(0, 500), (1000, 500)]), LineString([(500, 0), (500, 1000)])]}, crs=CRS)
    water = gpd.GeoDataFrame({"kind": ["river"], "name": ["Naga River"],
                              "geometry": [LineString([(700, 0), (700, 1000)])]}, crs=CRS)
    admin = gpd.GeoDataFrame({"name": ["San Isidro", "Poblacion"], "pcode": ["B1", "B2"],
                              "geometry": [box(0, 0, 500, 1000), box(500, 0, 1000, 1000)]}, crs=CRS)
    feats = gpd.GeoDataFrame({"name": ["City Hall"], "geometry": [Point(500, 500)]}, crs=CRS)
    return Base(lgu=lgu, crs=CRS, roads=roads, water=water, admin=admin, features=feats)
