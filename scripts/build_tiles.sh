#!/usr/bin/env bash
# V5: zonal value tiles for one LGU from lgus/<pcode>/out (made by `zv build`). Re-runnable.
#   tiles/values.pmtiles     layers value_streets (lines) and value_areas (barangay interiors, named areas)
#   tiles/values_meta.json   schedules (DO, date, link) per RDO, counts, and unmatched rows per barangay for the panel
set -euo pipefail
cd "$(dirname "$0")/.."
PC=${1:-PH1307404}
O=lgus/$PC/out
mkdir -p tiles
tippecanoe -q -f -o tiles/values.pmtiles --no-tile-size-limit -Z10 -z16 --no-feature-limit \
  -L value_areas:$O/values_areas.geojson -L value_streets:$O/values_streets.geojson
python3 -I - "$PC" <<'PY'
import json, sys
pc = sys.argv[1]
src = json.load(open(f"lgus/{pc}/valuation_sources.json"))
rep = json.load(open(f"lgus/{pc}/out/values_report.json"))
meta = {"lgu": src["lgu"], "adm3_pcode": pc, "valuation_base": src["valuation_base"], "smv": src["smv"],
        "schedules": {s["rdo"]: {k: s[k] for k in ("name", "department_order", "revision", "effective_date", "url", "listed_on")}
                      for s in src["schedules"]},
        "by_rdo": rep["by_rdo"], "conflicts": len(rep["conflicts"]),
        "unmatched": {b: [[i["text"], i["reason"]] for i in items] for b, items in rep["unmatched_by_barangay"].items()}}
json.dump(meta, open("tiles/values_meta.json", "w"), ensure_ascii=False, separators=(",", ":"))
print("tiles/values_meta.json:", sum(len(v) for v in meta["unmatched"].values()), "unmatched rows in", len(meta["unmatched"]), "barangays")
PY
ls -lh tiles/values.pmtiles tiles/values_meta.json
