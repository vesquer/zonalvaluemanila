"""Base layers a city's schedule rows are placed against. All geometry is held in a metric CRS."""
from __future__ import annotations
from dataclasses import dataclass, field
import geopandas as gpd
from shapely.geometry.base import BaseGeometry


def utm_epsg(lon: float, lat: float) -> int:
    """PH sits in UTM 50N-52N (EPSG:32650-32652)."""
    zone = int((lon + 180) // 6) + 1
    zone = min(max(zone, 50), 52)
    return 32600 + zone


@dataclass
class Base:
    lgu: BaseGeometry                      # LGU boundary, metric CRS
    crs: int                               # metric EPSG
    roads: gpd.GeoDataFrame                # class, name, geometry
    admin: gpd.GeoDataFrame                # name, pcode, geometry (barangays)
    features: gpd.GeoDataFrame             # name, geometry (named sites)
    national_classes: tuple[str, ...] = ("motorway", "trunk", "primary")  # OSM proxy for class="national"
    match_log: list[str] = field(default_factory=list)  # approximate name matches, surfaced to reviewers
    aliases: dict[str, list[str]] = field(default_factory=dict)  # reviewed names, from ops.alias_map(lgus/<pcode>/aliases.json)
