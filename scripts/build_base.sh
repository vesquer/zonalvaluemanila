#!/usr/bin/env bash
# S2: the base for the cities in CITIES, read once from the national data, then everything runs from the clip.
#   data/base/boundaries.gpkg  city (name, pcode), barangay (name, pcode, city_pcode)
#   data/base/osm.gpkg         roads (class, name, ref), lanes (named service/living/pedestrian ways), sites (named
#                              polygons and points), water; all within the cities' bounding box plus MARGIN_DEG
#   tiles/base.pmtiles         roads + barangay outlines for the map
# NATIONAL points at the national inputs (COD-AB shapefiles in boundaries/, the OSM extract in osm/); only this
# script reads them. Re-runnable; the clip is skipped when it exists (delete data/base to redo it).
set -euo pipefail
cd "$(dirname "$0")/.."
NATIONAL=${NATIONAL:-../ph-land-use-map/data}
CITIES=${CITIES:-PH1307404 PH1303901 PH1307403}   # Quezon City, Manila, Pasig
MARGIN_DEG=${MARGIN_DEG:-0.02}                     # about 2 km: major roads between and around the cities
B=data/base; T=data/tmp; mkdir -p $B $T tiles
IN=$(printf "'%s'," $CITIES); IN=${IN%,}

if [ ! -f $B/boundaries.gpkg ]; then
  echo "== boundaries: $CITIES"
  ogr2ogr -f GPKG $B/boundaries.gpkg $NATIONAL/boundaries/phl_admin3.shp -nln city -nlt PROMOTE_TO_MULTI -t_srs EPSG:4326 \
    -sql "SELECT adm3_name AS name, adm3_pcode AS pcode FROM phl_admin3 WHERE adm3_pcode IN ($IN)"
  ogr2ogr -f GPKG -update $B/boundaries.gpkg $NATIONAL/boundaries/phl_admin4.shp -nln barangay -nlt PROMOTE_TO_MULTI -t_srs EPSG:4326 \
    -sql "SELECT adm4_name AS name, adm4_pcode AS pcode, adm3_pcode AS city_pcode FROM phl_admin4 WHERE adm3_pcode IN ($IN)"
fi
read -r W S E N < <(ogrinfo -ro -so -al $B/boundaries.gpkg city | awk -F'[(), ]+' '/^Extent/{print $2,$3,$5,$6}')
BBOX="$(echo "$W - $MARGIN_DEG" | bc) $(echo "$S - $MARGIN_DEG" | bc) $(echo "$E + $MARGIN_DEG" | bc) $(echo "$N + $MARGIN_DEG" | bc)"
echo "bbox: $BBOX"

if [ ! -f $B/osm.gpkg ]; then
  echo "== OSM clip (reads the national extract; once)"
  export OSM_CONFIG_FILE=$PWD/scripts/osmconf.ini
  PBF=$NATIONAL/osm/philippines-latest.osm.pbf
  ogr2ogr -f GPKG $T/osm_clip.gpkg $PBF lines -nln lines -spat $BBOX -where "highway IS NOT NULL OR waterway IS NOT NULL"
  ogr2ogr -f GPKG -update $T/osm_clip.gpkg $PBF points -nln points -spat $BBOX -where "name IS NOT NULL"
  ogr2ogr -f GPKG -update $T/osm_clip.gpkg $PBF multipolygons -nln multipolygons -spat $BBOX -where "name IS NOT NULL" -nlt PROMOTE_TO_MULTI
  M="'motorway','trunk','primary','secondary','motorway_link','trunk_link','primary_link'"
  m="'tertiary','unclassified','residential'"
  L="'service','living_street','pedestrian','road'"
  ogr2ogr -f GPKG $B/osm.gpkg $T/osm_clip.gpkg -nln roads -sql \
    "SELECT highway AS class, name, ref, CASE WHEN highway IN ($M) THEN 'major' ELSE 'minor' END AS tier, geom FROM lines WHERE highway IN ($M,$m)"
  ogr2ogr -f GPKG -update $B/osm.gpkg $T/osm_clip.gpkg -nln lanes -sql \
    "SELECT highway AS class, name, geom FROM lines WHERE highway IN ($L) AND name IS NOT NULL"
  ogr2ogr -f GPKG -update $B/osm.gpkg $T/osm_clip.gpkg -nln water -sql \
    "SELECT CASE WHEN waterway = 'river' THEN 'river' WHEN waterway = 'stream' THEN 'creek' ELSE 'canal' END AS kind, name, geom
     FROM lines WHERE waterway IN ('river','stream','canal','drain','ditch')"
  ogr2ogr -f GPKG -update $B/osm.gpkg $T/osm_clip.gpkg -nln sites -nlt GEOMETRY -sql "SELECT name, geom FROM multipolygons"
  ogr2ogr -f GPKG -append $B/osm.gpkg $T/osm_clip.gpkg -nln sites -nlt GEOMETRY -sql "SELECT name, geom FROM points"
  rm -f $T/osm_clip.gpkg
fi

echo "== base.pmtiles"
# minor roads inside the cities; major roads in the margin too, so the routes between them still show
ogr2ogr -f GeoJSONSeq $T/cities.geojsonl $B/boundaries.gpkg city -lco RS=NO
.venv/bin/python -I - <<'PY'
import geopandas as gpd
city = gpd.read_file("data/base/boundaries.gpkg", layer="city").union_all()
r = gpd.read_file("data/base/osm.gpkg", layer="roads")
r = r[(r["tier"] == "major") | r.intersects(city)]
r[["class", "name", "ref", "geometry"]].to_file("data/tmp/base_roads.geojsonl", driver="GeoJSONSeq")
print(len(r), "roads for the base map")
PY
ogr2ogr -f GeoJSONSeq $T/barangays.geojsonl $B/boundaries.gpkg barangay -lco RS=NO
tippecanoe -q -f -o tiles/base.pmtiles --no-tile-size-limit -Z10 -z16 --drop-densest-as-needed --simplification=4 \
  -L roads:$T/base_roads.geojsonl -L barangays:$T/barangays.geojsonl -L cities:$T/cities.geojsonl
du -sh $B tiles/base.pmtiles
