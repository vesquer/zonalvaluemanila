from __future__ import annotations
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def _load_rules(path: Path) -> list[dict]:
    data = json.loads(path.read_text())
    return data["rules"] if isinstance(data, dict) else data


def cmd_validate(args: list[str]) -> int:
    from .validate import validate_all, validate_provenance
    if not args:
        print("usage: zv validate <values.json>")
        return 2
    rules = _load_rules(Path(args[0]))
    errs = validate_all(rules) + validate_provenance(rules)
    print("\n".join(errs) if errs else "ok: rows valid")
    return 1 if errs else 0


BASE = ROOT / "data/base"  # the clip made once by scripts/build_base.sh; nothing national is read after it


def load_base(pcode: str):
    """Build the metric-CRS base for one city (adm3 pcode) from the clip in data/base/."""
    import geopandas as gpd
    import pandas as pd
    from .base import Base, utm_epsg
    from .ops import alias_map
    bf, of = BASE / "boundaries.gpkg", BASE / "osm.gpkg"
    if not (bf.exists() and of.exists()):
        raise SystemExit("data/base is missing: run scripts/build_base.sh")
    city = gpd.read_file(bf, layer="city", where=f"pcode = '{pcode}'")
    if city.empty:
        raise SystemExit(f"PSGC/pcode {pcode} not in data/base/boundaries.gpkg (add it to CITIES in scripts/build_base.sh)")
    c = city.geometry.iloc[0].centroid
    epsg = utm_epsg(c.x, c.y)
    brgy = gpd.read_file(bf, layer="barangay", where=f"city_pcode = '{pcode}'")[["name", "pcode", "geometry"]]
    bbox = tuple(city.total_bounds)
    lgu = city.to_crs(epsg).geometry.iloc[0]
    r = gpd.read_file(of, layer="roads", bbox=bbox).to_crs(epsg)
    r = r[r.intersects(lgu)]
    lanes = gpd.read_file(of, layer="lanes", bbox=bbox).to_crs(epsg)
    sites = gpd.read_file(of, layer="sites", bbox=bbox).to_crs(epsg)
    r = pd.concat([r, lanes[lanes.intersects(lgu)]], ignore_index=True)
    af = ROOT / "lgus" / pcode / "aliases.json"
    raw = json.loads(af.read_text()) if af.exists() else {}
    aliases = alias_map({**raw.get("roads", {}), **raw.get("features", {})})
    sf = ROOT / "lgus" / pcode / "settings.json"
    scope = {k: float(v) for k, v in json.loads(sf.read_text()).items() if k in ("scope_m", "end_m", "edge_m")} if sf.exists() else {}
    return Base(lgu=lgu, crs=epsg, **scope, roads=r[["class", "name", "geometry"]].reset_index(drop=True), admin=brgy.to_crs(epsg),
                features=sites[sites.intersects(lgu.buffer(500))][["name", "geometry"]].reset_index(drop=True), aliases=aliases)


def cmd_build_values(args: list[str]) -> int:
    """zv build <adm3 pcode>: lgus/<pcode>/values.json -> out/values_streets.geojson, out/values_areas.geojson,
    out/values_report.json (every row is placed, listed as unmatched with its reason, manual, or out of scope)."""
    from .run import run_values
    if not args:
        print("usage: zv build <adm3 pcode>")
        return 2
    pcode = args[0]
    d = ROOT / "lgus" / pcode
    rules = _load_rules(d / "values.json")
    res = run_values(load_base(pcode), rules)
    out = d / "out"
    out.mkdir(exist_ok=True)
    for name, gdf in (("values_streets", res.streets), ("values_areas", res.areas)):
        gdf.to_crs(4326).to_file(out / f"{name}.geojson", driver="GeoJSON")
    rep = values_report(rules, res)
    (out / "values_report.json").write_text(json.dumps(rep, indent=1, ensure_ascii=False))
    for r in rep["by_rdo"]:
        print(f"RDO {r['rdo']}: {r['placed']}/{r['in_scope']} rows placed ({r['match_rate']:.0%}), {r['unmatched']} unmatched, "
              f"{r['manual']} manual, {r['out_of_scope']} out of scope")
    print(f"{pcode}: {len(res.streets)} street values, {len(res.areas)} area values, {len(res.conflicts)} conflicts flagged")
    return 0


def values_report(rules: list[dict], res) -> dict:
    placed = set(res.streets["rule_id"]) | set(res.areas["rule_id"]) if len(res.streets) + len(res.areas) else set()
    flagged = {f["rule_id"]: f for f in res.flags}
    manual, skipped = set(res.manual), set(res.skipped)
    by_rdo = []
    for rdo in sorted({str(r.get("rdo", "")) for r in rules}):
        rr = [r["rule_id"] for r in rules if str(r.get("rdo", "")) == rdo]
        n_in = sum(1 for x in rr if x not in skipped)
        n_ok = sum(1 for x in rr if x in placed)
        by_rdo.append({"rdo": rdo, "rows": len(rr), "in_scope": n_in, "placed": n_ok, "unmatched": sum(1 for x in rr if x in flagged),
                       "manual": sum(1 for x in rr if x in manual), "out_of_scope": sum(1 for x in rr if x in skipped),
                       "match_rate": round(n_ok / n_in, 4) if n_in else 0.0})
    unmatched: dict[str, list[dict]] = {}
    for f in res.flags:
        unmatched.setdefault(f["barangay"], []).append({"rule_id": f["rule_id"], "text": f["text"], "reason": f["flag"]})
    for r in rules:
        if r["rule_id"] in manual:
            unmatched.setdefault(r.get("barangay", ""), []).append(
                {"rule_id": r["rule_id"], "text": r["source"]["text"], "reason": r["interpretation"]})
    return {"by_rdo": by_rdo, "conflicts": res.conflicts, "unmatched_by_barangay": dict(sorted(unmatched.items()))}


def main() -> None:
    cmds = {"validate": cmd_validate, "build": cmd_build_values}
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd not in cmds:
        sys.exit("usage: zv {validate|build}")
    sys.exit(cmds[cmd](sys.argv[2:]))
