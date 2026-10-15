"""Run recipes deterministically and resolve zones by precedence."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any
import geopandas as gpd
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union
from . import ops
from .base import Base
from .validate import validate_all

MIN_AREA_M2 = 1.0
MIN_LEN_M = 1.0
CONFLICT_LEN_M = 2 * ops.EDGE_M + 10  # two values on one street conflict past this shared length (a street's pieces in
                                      # neighbouring barangays overlap by up to 2 x EDGE_M at the boundary by design)
CONFLICT_AREA_M2 = 100.0   # ... and on one area past this shared area


@dataclass
class Assigned:
    rule_id: str
    geom: BaseGeometry
    zone_local: str
    zone_national: str | None
    layer: str
    precedence: float


@dataclass
class AssignedValue:
    rule_id: str
    geom: BaseGeometry
    applies_to: str            # street | interior | area
    value_php_sqm: float
    class_code: str
    rdo: str
    department_order: str
    effective_date: str
    description: str           # the schedule's own words for the row, shown verbatim
    barangay: str
    notes: list[str] = field(default_factory=list)


@dataclass
class Result:
    base: gpd.GeoDataFrame
    overlay: gpd.GeoDataFrame
    flags: list[dict[str, str]] = field(default_factory=list)  # review flags
    manual: list[str] = field(default_factory=list)            # rules needing hand-drawn geometry
    notes: list[str] = field(default_factory=list)             # approximate matches etc.


def _run_steps(b: Base, rule: dict[str, Any], assigned: list[Assigned]) -> Assigned:
    env: dict[str, BaseGeometry] = {}
    road_class: str | None = None
    last: BaseGeometry | None = None
    for s in rule["recipe"]:
        op = s["op"]
        if op == "select_roads":
            road_class = s.get("class") or None
            g = ops.select_roads(b, name=s.get("name", ""), cls=s.get("class", ""), frm=s.get("from", ""), to=s.get("to", ""),
                                 within=s.get("within", ""), soft_limits=bool(s.get("soft_limits")))
        elif op == "select_water":
            g = ops.select_water(b, kind=s.get("kind", ""), name=s.get("name", ""))
        elif op == "select_admin":
            g = ops.select_admin(b, names=s.get("names"), pcodes=s.get("pcodes"), whole_lgu=bool(s.get("whole_lgu")))
        elif op == "select_feature":
            g = ops.select_feature(b, name=s["name"], within=s.get("within", ""))
        elif op == "buffer":
            g = ops.buffer(b, env[s["input"]], width_m=s["width_m"], measured_from=s.get("measured_from", "centerline"),
                           sides=s.get("sides", "both"), road_class=road_class)
        elif op == "between":
            g = ops.between(b, *[env[i] for i in s["inputs"]])
        elif op in ("union", "intersect", "subtract"):
            g = getattr(ops, op)(env[s["a"]], env[s["b"]])
        elif op == "clip":
            g = ops.clip(b, env[s["input"]], to=s["to"], names=s.get("names"))
        elif op == "residual":
            taken = unary_union([a.geom for a in assigned if a.layer == "base"]) if assigned else None
            area = env[s["area"]]
            g = area.difference(taken) if taken is not None else area
        elif op == "assign":
            geom = ops.polygons_only(env[s["input"]].intersection(b.lgu))
            if geom.is_empty or geom.area <= MIN_AREA_M2:
                raise ops.SelectionEmpty("result has no area inside the LGU (e.g. the named feature is only a point in the data)")
            return Assigned(rule["rule_id"], geom, s["zone_code_local"], s.get("zone_code_national"), s["layer"], float(s["precedence"]))
        elif op == "assign_value":
            return _assign_value(b, rule, s, env[s["input"]])
        if "id" in s:
            env[s["id"]] = g
        last = g
    raise ValueError(f"{rule['rule_id']}: no assign step ran")  # validator prevents this


def run(b: Base, rules: list[dict[str, Any]]) -> Result:
    errs = validate_all(rules)
    if errs:
        raise ValueError("invalid recipes:\n" + "\n".join(errs))
    res = Result(gpd.GeoDataFrame(), gpd.GeoDataFrame())
    assigned: list[Assigned] = []
    # run in precedence order so `residual` sees what was already assigned
    def prec(r):
        steps = r.get("recipe") or []
        a = [s for s in steps if s.get("op") == "assign"]
        return (a[-1]["precedence"] if a else 0)
    for rule in sorted(rules, key=lambda r: -prec(r)):
        if rule["recipe"] is None:
            res.manual.append(rule["rule_id"])
            continue
        try:
            assigned.append(_run_steps(b, rule, assigned))
        except ops.SelectionEmpty as e:
            res.flags.append({"rule_id": rule["rule_id"], "flag": str(e), "note": rule.get("interpretation", "")})
    res.notes = list(b.match_log)
    res.base = _resolve([a for a in assigned if a.layer == "base"], b.crs)
    res.overlay = _to_gdf([a for a in assigned if a.layer == "overlay"], b.crs)
    return res


def _to_gdf(items: list[Assigned], crs: int) -> gpd.GeoDataFrame:
    rows = [{"rule_ids": [a.rule_id], "zone_local": a.zone_local, "zone_national": a.zone_national, "precedence": a.precedence, "geometry": a.geom}
            for a in items if not a.geom.is_empty and a.geom.area > MIN_AREA_M2]
    return gpd.GeoDataFrame(rows, geometry="geometry", crs=crs) if rows else gpd.GeoDataFrame(
        {"rule_ids": [], "zone_local": [], "zone_national": [], "precedence": []}, geometry=[], crs=crs)


def _resolve(items: list[Assigned], crs: int) -> gpd.GeoDataFrame:
    """Higher precedence wins; base zones never overlap. Overlays never cut base (handled by layer)."""
    items = sorted(items, key=lambda a: -a.precedence)
    taken: BaseGeometry | None = None
    out: list[Assigned] = []
    for a in items:
        g = a.geom if taken is None else a.geom.difference(taken)
        g = ops.polygons_only(g)
        if not g.is_empty and g.area > MIN_AREA_M2:
            out.append(Assigned(a.rule_id, g, a.zone_local, a.zone_national, a.layer, a.precedence))
        taken = a.geom if taken is None else taken.union(a.geom)
    return _to_gdf(out, crs)


def coverage_report(lgu: BaseGeometry, base: gpd.GeoDataFrame, tol_m2: float = 1.0) -> dict[str, float]:
    """Acceptance: base zones cover the LGU with no gaps or overlaps."""
    if base.empty:
        return {"gap_m2": lgu.area, "overlap_m2": 0.0}
    u = unary_union(base.geometry.values)
    gap = lgu.difference(u).area
    sum_area = float(base.geometry.area.sum())
    overlap = max(0.0, sum_area - u.area)
    return {"gap_m2": 0.0 if gap < tol_m2 else gap, "overlap_m2": 0.0 if overlap < tol_m2 else overlap}


# --- zonal values -------------------------------------------------------------------------------------------

@dataclass
class ValueResult:
    streets: gpd.GeoDataFrame                                     # applies_to = street (lines)
    areas: gpd.GeoDataFrame                                       # applies_to = interior | area (polygons)
    flags: list[dict[str, str]] = field(default_factory=list)     # unmatched rows, with the reason
    manual: list[str] = field(default_factory=list)               # rows the map cannot place (recipe null)
    skipped: list[str] = field(default_factory=list)              # rows outside scope (status out_of_scope)
    conflicts: list[dict[str, Any]] = field(default_factory=list)


def _lines_only(g: BaseGeometry) -> BaseGeometry:
    parts = [p for p in (g.geoms if hasattr(g, "geoms") else [g]) if p.geom_type in ("LineString", "MultiLineString")]
    return unary_union(parts) if parts else g.__class__()


def _assign_value(b: Base, rule: dict[str, Any], s: dict[str, Any], g: BaseGeometry) -> AssignedValue:
    g = g.intersection(b.lgu)
    if s["applies_to"] == "street":
        geom = _lines_only(g)
        if geom.is_empty or geom.length <= MIN_LEN_M:
            raise ops.SelectionEmpty("no street length inside the LGU")
    else:
        geom = ops.polygons_only(g)
        if geom.is_empty or geom.area <= MIN_AREA_M2:
            raise ops.SelectionEmpty("result has no area inside the LGU (e.g. the named place is only a point in the data)")
    src = rule.get("source", {})
    return AssignedValue(rule["rule_id"], geom, s["applies_to"], float(s["value_php_sqm"]), s["class_code"], str(s.get("rdo", "")),
                         s.get("department_order", ""), s.get("effective_date", ""), src.get("text", ""), rule.get("barangay", ""))


def run_values(b: Base, rules: list[dict[str, Any]]) -> ValueResult:
    """Each row stands alone: no precedence, nothing is resolved away. Overlapping different values of one
    classification are reported as conflicts and both kept; the build never picks one."""
    errs = validate_all(rules)
    if errs:
        raise ValueError("invalid recipes:\n" + "\n".join(errs))
    res = ValueResult(gpd.GeoDataFrame(), gpd.GeoDataFrame())
    got: list[AssignedValue] = []
    for rule in rules:
        if rule.get("status") == "out_of_scope":
            res.skipped.append(rule["rule_id"])
            continue
        if rule["recipe"] is None:
            res.manual.append(rule["rule_id"])
            continue
        mark = len(b.match_log)
        try:
            a = _run_steps(b, rule, [])
            a.notes = b.match_log[mark:]
            got.append(a)
        except ops.SelectionEmpty as e:
            res.flags.append({"rule_id": rule["rule_id"], "barangay": rule.get("barangay", ""), "rdo": str(rule.get("rdo", "")),
                              "flag": str(e), "text": rule.get("source", {}).get("text", "")})
    res.conflicts = find_conflicts(got)
    clash: dict[str, list[str]] = {}
    for c in res.conflicts:
        clash.setdefault(c["a"], []).append(c["b"])
        clash.setdefault(c["b"], []).append(c["a"])
    res.streets = _values_gdf([a for a in got if a.applies_to == "street"], b.crs, clash)
    res.areas = _values_gdf([a for a in got if a.applies_to != "street"], b.crs, clash)
    return res


def find_conflicts(items: list[AssignedValue]) -> list[dict[str, Any]]:
    """Pairs of rows of the same classification and kind (street with street, interior with interior, area with
    area) that put different values on the same ground."""
    import shapely
    out = []
    groups: dict[tuple[str, str], list[AssignedValue]] = {}
    for a in items:
        groups.setdefault((a.class_code, a.applies_to), []).append(a)
    for (code, kind), g in groups.items():
        tree = shapely.STRtree([a.geom for a in g])
        for i, a in enumerate(g):
            for j in tree.query(a.geom.buffer(2)):
                if j <= i or g[j].value_php_sqm == a.value_php_sqm:
                    continue
                o = g[j]
                if kind == "street":
                    shared = a.geom.intersection(o.geom.buffer(2)).length
                    if shared <= CONFLICT_LEN_M:
                        continue
                else:
                    shared = a.geom.intersection(o.geom).area
                    if shared <= CONFLICT_AREA_M2:
                        continue
                out.append({"a": a.rule_id, "b": o.rule_id, "class_code": code, "applies_to": kind,
                            "values": [a.value_php_sqm, o.value_php_sqm], "shared": round(shared, 1),
                            "barangays": sorted({a.barangay, o.barangay})})
    return out


def _values_gdf(items: list[AssignedValue], crs: int, clash: dict[str, list[str]]) -> gpd.GeoDataFrame:
    cols = ["rule_id", "applies_to", "value_php_sqm", "class_code", "rdo", "department_order", "effective_date",
            "description", "barangay", "notes", "conflict_with"]
    rows = [{"rule_id": a.rule_id, "applies_to": a.applies_to, "value_php_sqm": a.value_php_sqm, "class_code": a.class_code,
             "rdo": a.rdo, "department_order": a.department_order, "effective_date": a.effective_date,
             "description": a.description, "barangay": a.barangay, "notes": "; ".join(a.notes),
             "conflict_with": ",".join(sorted(clash.get(a.rule_id, []))), "geometry": a.geom} for a in items]
    return gpd.GeoDataFrame(rows, geometry="geometry", crs=crs) if rows else gpd.GeoDataFrame(
        {c: [] for c in cols}, geometry=[], crs=crs)
