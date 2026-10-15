"""Validate recipes before running: known operations only, references resolve, units in metres."""
from __future__ import annotations
from typing import Any

# op -> (required fields, fields that hold a step id)
OPS: dict[str, tuple[set[str], set[str]]] = {
    "select_roads": (set(), set()),
    "select_water": (set(), set()),
    "select_admin": (set(), set()),
    "select_feature": ({"name"}, set()),
    "buffer": ({"input", "width_m"}, {"input"}),
    "between": ({"inputs"}, set()),          # inputs: list of step ids
    "union": ({"a", "b"}, {"a", "b"}),
    "intersect": ({"a", "b"}, {"a", "b"}),
    "subtract": ({"a", "b"}, {"a", "b"}),
    "clip": ({"input", "to"}, {"input"}),
    "residual": ({"area", "zone_code_local"}, {"area"}),
    "assign": ({"input", "zone_code_local", "layer", "precedence"}, {"input"}),
    "assign_value": ({"input", "value_php_sqm", "class_code", "applies_to"}, {"input"}),
}
LAYERS = {"base", "overlay"}
APPLIES_TO = {"street", "interior", "area"}
FINAL = {"assign", "assign_value"}


def validate_recipe(rule: dict[str, Any]) -> list[str]:
    errs: list[str] = []
    rid = rule.get("rule_id", "?")
    if "recipe" not in rule:
        return [f"{rid}: missing 'recipe' (use null for manual geometry)"]
    steps = rule["recipe"]
    if steps is None:
        if not rule.get("interpretation"):
            errs.append(f"{rid}: recipe is null, so 'interpretation' must explain why")
        return errs
    if not steps:
        return [f"{rid}: empty recipe"]
    seen: set[str] = set()
    for i, s in enumerate(steps):
        op = s.get("op")
        where = f"{rid} step {i} ({op})"
        if op not in OPS:
            errs.append(f"{where}: unknown operation")
            continue
        req, refs = OPS[op]
        for f in req:
            if f not in s:
                errs.append(f"{where}: missing field '{f}'")
        for f in refs:
            if f in s and s[f] not in seen:
                errs.append(f"{where}: '{f}' refers to unknown step {s[f]!r}")
        if op == "between":
            for x in s.get("inputs", []):
                if x not in seen:
                    errs.append(f"{where}: input {x!r} is not an earlier step")
        if op == "buffer" and not (isinstance(s.get("width_m"), (int, float)) and s["width_m"] > 0):
            errs.append(f"{where}: width_m must be a positive number of metres")
        if op == "buffer" and s.get("measured_from", "centerline") not in {"centerline", "row_edge"}:
            errs.append(f"{where}: measured_from must be centerline or row_edge")
        if op == "assign":
            if s.get("layer") not in LAYERS:
                errs.append(f"{where}: layer must be base or overlay")
            if not isinstance(s.get("precedence"), (int, float)):
                errs.append(f"{where}: precedence must be a number")
        if op == "assign_value":
            if not (isinstance(s.get("value_php_sqm"), (int, float)) and s["value_php_sqm"] > 0):
                errs.append(f"{where}: value_php_sqm must be a positive number of PHP per square metre")
            if s.get("applies_to") not in APPLIES_TO:
                errs.append(f"{where}: applies_to must be street, interior or area")
        if "id" in s:
            if s["id"] in seen:
                errs.append(f"{where}: duplicate step id {s['id']!r}")
            seen.add(s["id"])
    if steps[-1].get("op") not in FINAL:
        errs.append(f"{rid}: last step must be assign")
    if any(s.get("op") in FINAL for s in steps[:-1]):
        errs.append(f"{rid}: assign may only be the last step")
    return errs


def validate_all(rules: list[dict[str, Any]]) -> list[str]:
    errs: list[str] = []
    ids = [r.get("rule_id") for r in rules]
    for d in {x for x in ids if ids.count(x) > 1}:
        errs.append(f"duplicate rule_id {d!r}")
    for r in rules:
        errs += validate_recipe(r)
    return errs


def validate_provenance(rules: list[dict[str, Any]], schema_name: str = "recipe.schema.json") -> list[str]:
    """Structure and provenance check against a schema (every rule must cite its source).
    recipe.schema.json for zoning rules, value.schema.json for zonal value rows."""
    import json
    from importlib import resources
    import jsonschema
    schema = json.loads(resources.files("zv").joinpath(f"schema/{schema_name}").read_text())
    v = jsonschema.Draft202012Validator(schema)
    return [f"{r.get('rule_id', '?')}: {'/'.join(map(str, e.path)) or 'rule'}: {e.message}"
            for r in rules for e in v.iter_errors(r)]
