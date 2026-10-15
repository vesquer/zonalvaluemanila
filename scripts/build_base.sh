#!/usr/bin/env bash
# M1: build base-layer PMTiles from data/ into tiles/. Re-runnable.
set -euo pipefail
cd "$(dirname "$0")/.."
T=data/tmp; mkdir -p $T tiles

echo "== boundaries"
if [ ! -f tiles/admin.pmtiles ]; then
for l in 1 2 3 4; do
  ogr2ogr -f GeoJSONSeq $T/admin$l.geojsonl data/boundaries/phl_admin$l.shp \
    -lco RS=NO -t_srs EPSG:4326 -nlt PROMOTE_TO_MULTI \
    -sql "SELECT adm${l}_name AS name, adm${l}_pcode AS pcode FROM phl_admin$l"
done
tippecanoe -f -o tiles/admin.pmtiles --no-tile-size-limit -pk -pf \
  -L admin1:$T/admin1.geojsonl --minimum-zoom=0 --maximum-zoom=8 \
  -L admin2:$T/admin2.geojsonl --minimum-zoom=5 --maximum-zoom=11 \
  -L admin3:$T/admin3.geojsonl --minimum-zoom=8 --maximum-zoom=14 \
  -L admin4:$T/admin4.geojsonl --minimum-zoom=11 --maximum-zoom=14 \
  --simplification=4 --detect-shared-borders --coalesce-densest-as-needed

fi

echo "== roads"
export OSM_CONFIG_FILE=$PWD/scripts/osmconf.ini
for tier in major minor; do
  if [ $tier = major ]; then W="highway IN ('motorway','trunk','primary','secondary','motorway_link','trunk_link','primary_link')"
  else W="highway IN ('tertiary','unclassified','residential')"; fi
  ogr2ogr -f GeoJSONSeq $T/roads_$tier.geojsonl data/osm/philippines-latest.osm.pbf lines -lco RS=NO \
    -sql "SELECT highway AS class, name, ref FROM lines WHERE $W"
done
tippecanoe -f -o tiles/roads.pmtiles --no-tile-size-limit -Z5 -z14 \
  --drop-densest-as-needed --simplification=4 \
  -L roads:$T/roads_major.geojsonl --minimum-zoom=5 \
  -L roads:$T/roads_minor.geojsonl --minimum-zoom=11

echo "== land cover (WorldCover 10 m -> ~100 m, polygonised)"
gdalbuildvrt -overwrite $T/wc.vrt data/worldcover/*.tif
gdalwarp -overwrite -q -r mode -tr 0.001 0.001 -t_srs EPSG:4326 -ot Byte -co COMPRESS=DEFLATE $T/wc.vrt $T/wc100.tif
gdal_polygonize.py -q $T/wc100.tif -f GeoJSONSeq $T/lc.geojsonl lc code 2>/dev/null || \
  gdal_polygonize $T/wc100.tif -f GeoJSONSeq $T/lc.geojsonl lc code
tippecanoe -f -o tiles/landcover.pmtiles -l landcover --no-tile-size-limit \
  -Z4 -z12 --drop-densest-as-needed --coalesce-densest-as-needed --simplification=8 $T/lc.geojsonl
ls -lh tiles

echo "== search index"
ogr2ogr -f GeoJSONSeq $T/search3.geojsonl data/boundaries/phl_admin3.shp -lco RS=NO -nlt PROMOTE_TO_MULTI -sql "SELECT adm3_name AS name, adm3_pcode AS pcode, adm2_name AS province FROM phl_admin3"
python3 -I - <<'PY'
import json
out=[]
for line in open("data/tmp/search3.geojsonl"):
    f=json.loads(line); g=f["geometry"]
    pts=[p for poly in g["coordinates"] for ring in poly[:1] for p in ring]
    c=[round(sum(p[0] for p in pts)/len(pts),5), round(sum(p[1] for p in pts)/len(pts),5)]
    out.append({"name":f["properties"]["name"],"pcode":f["properties"]["pcode"],"province":f["properties"]["province"],"c":c})
json.dump(out,open("tiles/search.json","w"),ensure_ascii=False,separators=(",",":"))
print(len(out),"places")
PY
