#!/usr/bin/env bash
# Value tiles for every city in scripts/cities.json that has been built (lgus/<pcode>/out from `zv build`). Re-runnable.
#   tiles/values.pmtiles     layers value_streets (lines) and value_areas (barangay interiors, named areas)
#   tiles/values_meta.json   cities, schedules (DO, date, link) per RDO, counts, unmatched rows per barangay for the
#                            panel, and the search index (cities, barangays, valued streets)
# Then checks the size budget: whole site under 20 MB, no file over 25 MB.
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p tiles data/tmp
.venv/bin/python -I - <<'PY'
import json, pathlib, re
import geopandas as gpd
import pandas as pd
root = pathlib.Path(".")
cities = {k: v for k, v in json.loads((root / "scripts/cities.json").read_text()).items() if not k.startswith("_")}
built = [pc for pc in cities if (root / f"lgus/{pc}/out/values_report.json").exists()]
bnd = gpd.read_file("data/base/boundaries.gpkg", layer="city")
brg = gpd.read_file("data/base/boundaries.gpkg", layer="barangay")
meta = {"cities": {}, "schedules": {}, "by_rdo": [], "conflicts": 0, "unmatched": {}, "search": []}
streets, areas = [], []
pt = lambda g: [round(g.x, 5), round(g.y, 5)]
for pc in cities:
    c = bnd[bnd.pcode == pc]
    if c.empty:
        continue
    b = c.total_bounds
    meta["cities"][pc] = {"name": cities[pc]["lgu"], "bounds": [round(x, 4) for x in b], "built": pc in built}
    meta["search"].append({"n": cities[pc]["lgu"], "k": "city", "c": pt(c.representative_point().iloc[0]), "b": [round(x, 4) for x in b]})
    for _, r in brg[brg.city_pcode == pc].iterrows():
        meta["search"].append({"n": r["name"], "k": "barangay", "city": cities[pc]["lgu"], "c": pt(r.geometry.representative_point())})
for pc in built:
    src = json.loads((root / f"lgus/{pc}/valuation_sources.json").read_text())
    rep = json.loads((root / f"lgus/{pc}/out/values_report.json").read_text())
    city = cities[pc]["lgu"]
    meta["cities"][pc].update({"valuation_base": src["valuation_base"], "smv": src["smv"]})
    for s in src["schedules"]:
        meta["schedules"][s["rdo"]] = {"city": city, **{k: s[k] for k in ("name", "department_order", "revision", "effective_date", "url", "listed_on")}}
    meta["by_rdo"] += [{**r, "city": city} for r in rep["by_rdo"]]
    meta["conflicts"] += len(rep["conflicts"])
    for brgy, items in rep["unmatched_by_barangay"].items():
        meta["unmatched"][f"{brgy}, {city}"] = [[i["text"], i["reason"]] for i in items]
    s = gpd.read_file(root / f"lgus/{pc}/out/values_streets.geojson"); s["effective_date"] = s["effective_date"].astype(str).str[:10]; s["city"] = city; streets.append(s)
    a = gpd.read_file(root / f"lgus/{pc}/out/values_areas.geojson"); a["effective_date"] = a["effective_date"].astype(str).str[:10]; a["city"] = city; areas.append(a)
    # valued streets: the schedule's own spelling, one entry per street and barangay
    s = s.to_crs(32651)
    s["sname"] = s["description"].str.split(" | ", regex=False).str[0].str.strip()
    for (name, brgy), g in s.groupby(["sname", "barangay"]):
        if re.match(r"^ALL\b", name):
            continue
        p = g.geometry.union_all().representative_point()
        meta["search"].append({"n": name, "k": "street", "city": city, "brgy": brgy,
                               "c": pt(gpd.GeoSeries([p], crs=32651).to_crs(4326).iloc[0])})
pd.concat(streets).to_file("data/tmp/values_streets.geojson", driver="GeoJSON")
pd.concat(areas).to_file("data/tmp/values_areas.geojson", driver="GeoJSON")
json.dump(meta, open("tiles/values_meta.json", "w"), ensure_ascii=False, separators=(",", ":"))
print("cities built:", ", ".join(cities[p]["lgu"] for p in built), "|", sum(len(v) for v in meta["unmatched"].values()),
      "unmatched rows |", len(meta["search"]), "search entries")
PY
tippecanoe -q -f -o tiles/values.pmtiles --no-tile-size-limit -Z10 -z16 --no-feature-limit \
  -L value_areas:data/tmp/values_areas.geojson -L value_streets:data/tmp/values_streets.geojson
total=$(du -ck tiles/* | tail -1 | cut -f1); big=$(find tiles -type f -size +25M)
echo "tiles: $((total / 1024)) MB"
[ -z "$big" ] || { echo "over the 25 MB per-file limit: $big"; exit 1; }
ls -lh tiles
