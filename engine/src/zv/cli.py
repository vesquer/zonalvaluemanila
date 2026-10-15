from __future__ import annotations
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def _load_rules(path: Path) -> list[dict]:
    data = json.loads(path.read_text())
    return data["rules"] if isinstance(data, dict) else data


def _is_values(path: Path) -> bool:
    data = json.loads(path.read_text())
    return isinstance(data, dict) and data.get("kind") == "zonal_values"


def cmd_validate(args: list[str]) -> int:
    from .validate import validate_all, validate_provenance
    if not args:
        print("usage: zv validate <recipes.json>")
        return 2
    rules = _load_rules(Path(args[0]))
    schema = "value.schema.json" if _is_values(Path(args[0])) else "recipe.schema.json"
    errs = validate_all(rules) + validate_provenance(rules, schema)
    print("\n".join(errs) if errs else "ok: recipes valid")
    return 1 if errs else 0


def load_base(pcode: str):
    """Build the metric-CRS base for one LGU (municipality/city pcode) from data/."""
    import geopandas as gpd
    import pandas as pd
    from .base import Base, utm_epsg
    from .ops import alias_map
    b = ROOT / "data/boundaries"
    city = gpd.read_file(b / "phl_admin3.shp", where=f"adm3_pcode = '{pcode}'")
    if city.empty:
        raise SystemExit(f"PSGC/pcode {pcode} not found in data/boundaries/phl_admin3.shp")
    c = city.geometry.iloc[0].centroid
    epsg = utm_epsg(c.x, c.y)
    brgy = gpd.read_file(b / "phl_admin4.shp", where=f"adm3_pcode = '{pcode}'").rename(
        columns={"adm4_name": "name", "adm4_pcode": "pcode"})[["name", "pcode", "geometry"]]
    minx, miny, maxx, maxy = city.total_bounds
    roads = []
    for tier in ("major", "minor"):
        f = ROOT / f"data/tmp/roads_{tier}.geojsonl"
        if f.exists():
            roads.append(gpd.read_file(f, bbox=(minx, miny, maxx, maxy)))
    r = pd.concat(roads) if roads else gpd.GeoDataFrame({"class": [], "name": []}, geometry=[], crs=4326)
    lgu = city.to_crs(epsg).geometry.iloc[0]
    r = gpd.GeoDataFrame(r, crs=4326).to_crs(epsg)
    r = r[r.intersects(lgu)]
    feats, water, lanes = _osm_extras(pcode, (minx, miny, maxx, maxy), epsg, lgu)
    r = pd.concat([r, lanes[lanes.intersects(lgu)]], ignore_index=True)
    af = ROOT / "lgus" / pcode / "aliases.json"
    raw = json.loads(af.read_text()) if af.exists() else {}
    aliases = alias_map({**raw.get("roads", {}), **raw.get("features", {})})
    return Base(lgu=lgu, crs=epsg, roads=r[["class", "name", "geometry"]].reset_index(drop=True), water=water,
                admin=brgy.to_crs(epsg), features=feats.reset_index(drop=True), aliases=aliases)


LANES = ("service", "living_street", "pedestrian", "road")  # named ways the base road tiers leave out


def _osm_extras(pcode: str, bbox, epsg: int, lgu):
    """Named sites (schools, churches, resorts...), waterways and named minor ways (service roads, living streets:
    many subdivision streets are tagged so) from the OSM extract; cached per LGU."""
    import os
    import geopandas as gpd
    import pyogrio
    cache = ROOT / f"data/cache/{pcode}_osm.gpkg"
    if cache.exists() and "lanes" not in {n for n, _ in pyogrio.list_layers(cache)}:
        os.environ["OSM_CONFIG_FILE"] = str(ROOT / "scripts/osmconf.ini")
        lines = gpd.read_file(ROOT / "data/osm/philippines-latest.osm.pbf", layer="lines", bbox=bbox)
        _lanes(lines).to_file(cache, layer="lanes", driver="GPKG")
    if not cache.exists():
        cache.parent.mkdir(parents=True, exist_ok=True)
        os.environ["OSM_CONFIG_FILE"] = str(ROOT / "scripts/osmconf.ini")
        pbf = ROOT / "data/osm/philippines-latest.osm.pbf"
        poly = gpd.read_file(pbf, layer="multipolygons", bbox=bbox)
        pts = gpd.read_file(pbf, layer="points", bbox=bbox)
        lines = gpd.read_file(pbf, layer="lines", bbox=bbox)
        sites = gpd.GeoDataFrame(
            list(poly[poly["name"].notna()][["name", "geometry"]].itertuples(index=False))
            + list(pts[pts["name"].notna()][["name", "geometry"]].itertuples(index=False)),
            columns=["name", "geometry"], crs=4326)
        ww = lines[lines["waterway"].isin(["river", "stream", "canal", "drain", "ditch"])].copy()
        ww["kind"] = ww["waterway"].map({"river": "river", "stream": "creek", "canal": "canal", "drain": "canal", "ditch": "canal"})
        ww[["kind", "name", "geometry"]].to_file(cache, layer="water", driver="GPKG")
        sites.to_file(cache, layer="features", driver="GPKG")
        _lanes(lines).to_file(cache, layer="lanes", driver="GPKG")
    sites = gpd.read_file(cache, layer="features").to_crs(epsg)
    water = gpd.read_file(cache, layer="water").to_crs(epsg)
    lanes = gpd.read_file(cache, layer="lanes").to_crs(epsg)
    return sites[sites.intersects(lgu.buffer(500))], water[water.intersects(lgu)], lanes[["class", "name", "geometry"]]


def _lanes(lines):
    ln = lines[lines["highway"].isin(LANES) & lines["name"].notna()].copy()
    ln["class"] = ln["highway"]
    return ln[["class", "name", "geometry"]]


def cmd_build_lgu(args: list[str]) -> int:
    from .run import run, coverage_report
    if not args:
        print("usage: zv build-lgu <adm3 pcode>")
        return 2
    pcode = args[0]
    d = ROOT / "lgus" / pcode
    rules = _load_rules(d / "recipes.json")
    base = load_base(pcode)
    res = run(base, rules)
    out = d / "out"
    out.mkdir(exist_ok=True)
    for name, gdf in (("zones_base", res.base), ("zones_overlay", res.overlay)):
        if not gdf.empty:
            g = gdf.to_crs(4326).copy()
            g["rule_ids"] = g["rule_ids"].map(lambda x: ",".join(x))
            g.to_file(out / f"{name}.geojson", driver="GeoJSON")
    rep = coverage_report(base.lgu, res.base)
    (out / "report.json").write_text(json.dumps({"coverage": rep, "flags": res.flags, "manual": res.manual, "notes": res.notes}, indent=2))
    print(f"{pcode}: {len(res.base)} base zones, {len(res.overlay)} overlays; gap {rep['gap_m2']:.0f} m2, "
          f"overlap {rep['overlap_m2']:.0f} m2; {len(res.flags)} review flags; {len(res.manual)} manual")
    return 0


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


def _parse_pages(spec: str, n: int) -> list[int]:
    out: list[int] = []
    for part in spec.split(","):
        a, _, b = part.partition("-")
        out += range(int(a), int(b or a) + 1)
    return [p for p in out if 1 <= p <= n]


def cmd_prep_pdf(args: list[str]) -> int:
    """zv prep-pdf <pdf> <outdir> [pages, e.g. 43-53,60]: text per page, page images, scanned-page list."""
    import pymupdf
    if len(args) < 2:
        print("usage: zv prep-pdf <pdf> <outdir> [pages]")
        return 2
    doc = pymupdf.open(args[0])
    out = Path(args[1])
    out.mkdir(parents=True, exist_ok=True)
    pages = _parse_pages(args[2], len(doc)) if len(args) > 2 else list(range(1, len(doc) + 1))
    scanned = []
    for n in pages:
        pg = doc[n - 1]
        text = pg.get_text().strip()
        if len(text) < 80:  # image-only page: needs OCR (Tesseract) or reading from the image
            scanned.append(n)
        (out / f"p{n:03d}.txt").write_text(text)
        pg.get_pixmap(dpi=110).save(out / f"p{n:03d}.png")
    (out / "scanned_pages.json").write_text(json.dumps(scanned))
    print(f"{len(pages)} pages -> {out}; {len(scanned)} look scanned (need OCR): {scanned[:20]}")
    return 0


def main() -> None:
    cmds = {"validate": cmd_validate, "build": cmd_build_values, "build-lgu": cmd_build_lgu, "prep-pdf": cmd_prep_pdf}
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd not in cmds:
        sys.exit("usage: zv {validate|build|build-lgu|prep-pdf}")
    sys.exit(cmds[cmd](sys.argv[2:]))
