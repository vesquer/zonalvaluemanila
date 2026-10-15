"""Generates lgus/<pcode>/values.json (zonal value rows) from the parsed BIR schedule rows
(data/prep/<pcode>_rows.json, made by parse_schedules.py).

usage: python scripts/gen_values.py <pcode>

Row forms: "ALL OTHER STREETS" -> the barangay interior; a subdivision, village or compound -> its OSM outline;
anything else -> the named street inside the row's barangay, between its two vicinity streets when it has two.
Condominium, townhouse-unit and parking-slot classes (RC, CC, PS) are out of the MVP's scope and kept as such."""
import json
import pathlib
import re
import sys
import geopandas as gpd

ROOT = pathlib.Path(__file__).resolve().parents[1]
PC = sys.argv[1] if __name__ == "__main__" else "PH1307404"
PREFIX = json.loads((ROOT / "scripts/cities.json").read_text())[PC]["prefix"]
SRC = json.loads((ROOT / f"lgus/{PC}/valuation_sources.json").read_text())["schedules"]
ALIASES = json.loads((ROOT / f"lgus/{PC}/aliases.json").read_text()) if (ROOT / f"lgus/{PC}/aliases.json").exists() else {}
OUT_OF_SCOPE = {"RC": "residential condominium unit", "CC": "commercial condominium unit", "PS": "parking slot"}
AREA = re.compile(r"\b(VILL(AGE)?|SUBD(IVISION)?S?|COMPOUND|CMPD|HOMES|HEIGHTS|ESTATES?|HOUSING|PROJECT|SITIO|TOWNHOMES?|"
                  r"RESIDENCES|PHASE|PH\.?\s*[IVX\d]+|GK|GAWAD KALINGA|CONDO(MINIUM)?S?|TOWN ?HOUSES?|CAMP|CAMPUS|COMPLEX)\b")
STREET_END = re.compile(r"\b(ST|STREET|AVE|AVENUE|RD|ROAD|DR|DRIVE|LANE|EXT|EXTENSION|BLVD|BOULEVARD|HI-?WAY|HIGHWAY)\.?$")
UNITS = re.compile(r"\b(CONDO(MINIUM)?S?|TOWN ?HOUSES?|T'HOUSE|CCT|TCT)\b")
# hyphenated words that are one name, not "from - to"
COMPOUND = re.compile(r"\b(PAG-ASA|PAG-IBIG|HI-WAY|DUYAN-DUYAN|STO\.?-|STA\.?-|BAGONG-|SAN-|DE-|LA-)", re.I)


def norm_brgy(s: str) -> str:
    s = s.upper().replace("Ñ", "N")
    s = re.sub(r"\bSTA\.?\s", "SANTA ", s)
    s = re.sub(r"\bSTO\.?\s", "SANTO ", s)
    s = re.sub(r"\bST\.?\s", "SAINT ", s)
    s = re.sub(r"\bSR\.?$", "", s.strip())
    return re.sub(r"[^A-Z0-9]", "", s)


def barangay_names() -> dict[str, str]:
    adm = gpd.read_file(ROOT / "data/base/boundaries.gpkg", layer="barangay", where=f"city_pcode = '{PC}'", ignore_geometry=True)
    out = {}
    for n in adm["name"]:
        out[norm_brgy(n)] = n
        out.setdefault(norm_brgy(re.sub(r"\(.*?\)", "", n)), n)       # "N.S. Amoranto (Gintong Silahis)"
        inner = re.search(r"\((.*?)\)", n)
        if inner:
            out.setdefault(norm_brgy(inner.group(1)), n)
    return out


def split_vicinity(v: list[str]) -> tuple[str, str] | None:
    """Two vicinity cells, or one 'A - B' / 'A-B' cell -> (from, to). One plain cell is the neighbourhood, not a limit."""
    if len(v) >= 2:
        return v[0], v[1]
    if len(v) == 1 and not COMPOUND.search(v[0]):
        parts = [p.strip() for p in re.split(r"\s*-\s*", v[0])]
        if len(parts) == 2 and all(len(p) >= 3 for p in parts):
            return parts[0], parts[1]
    return None


def street_names(s: str) -> list[str]:
    """'TUAYAN ST./FAMILARA ST.' -> two streets; 'KALAWAG(CALAUAG)' -> the first spelling."""
    s = re.sub(r"\s*\(.*?\)\s*", " ", s).strip()
    return [p.strip() for p in re.split(r"\s*/\s*|\s+&\s+", s) if len(p.strip()) >= 2]


def main() -> None:
    rows = json.loads((ROOT / f"data/prep/{PC}_rows.json").read_text())
    src = {s["rdo"]: s for s in SRC}
    bnames = barangay_names()
    balias = {norm_brgy(k): v for k, v in ALIASES.get("barangays", {}).items() if not k.startswith("_")}
    rules, seq, unknown_brgy = [], {}, set()
    for r in rows:
        rdo, s = r["rdo"], src[r["rdo"]]
        seq[rdo] = n = seq.get(rdo, 0) + 1
        code, street, vic = r["class_code"], r["street"], r["vicinity"]
        brgy = balias.get(norm_brgy(r["barangay"])) or bnames.get(norm_brgy(r["barangay"]))
        if not brgy:
            unknown_brgy.add(r["barangay"])
        text = " | ".join([street, *vic, code, f"{r['value_php_sqm']:,.0f}"])
        label = (", ".join(brgy) if isinstance(brgy, list) else brgy) or r["barangay"]
        rule = {"rule_id": f"{PREFIX}-{rdo}-{n:04d}", "lgu_psgc": PC, "rdo": rdo, "barangay": label,
                "source": {"file_sha256": s["xls_sha256"], "department_order": s["department_order"], "sheet": r["sheet"],
                           "row": r["row"], "text": text}}
        av = {"op": "assign_value", "value_php_sqm": r["value_php_sqm"], "class_code": code, "rdo": rdo,
              "department_order": s["department_order"], "effective_date": s["effective_date"]}
        up = street.upper()
        if code in OUT_OF_SCOPE:
            rule.update(interpretation=f"{OUT_OF_SCOPE[code].capitalize()} value: out of the MVP's scope (land only).",
                        recipe=None, assumptions=[], confidence=1.0, status="out_of_scope")
        elif not brgy:
            rule.update(interpretation=f"Barangay {r['barangay']!r} is not in the boundary data; add it to aliases.json.",
                        recipe=None, assumptions=[], confidence=0.0, status="manual_geometry")
        elif up.startswith("ALL ") and UNITS.search(up):
            rule.update(interpretation="Applies to townhouse or condominium lots in the barangay, which the map cannot locate.",
                        recipe=None, assumptions=[], confidence=0.0, status="manual_geometry")
        elif up.startswith("ALL "):
            rule.update(interpretation=f"{code} value for the rest of barangay {label} (the schedule's '{street}').",
                        recipe=[{"id": "b", "op": "select_admin", "names": brgy if isinstance(brgy, list) else [brgy]}, {**av, "input": "b", "applies_to": "interior"}],
                        assumptions=["Drawn as the whole barangay; named streets and areas in it carry their own values on top"],
                        confidence=0.8, status="pending_review")
        elif AREA.search(up) and not STREET_END.search(up):
            rule.update(interpretation=f"{code} value for {street} in {label}.",
                        recipe=[{"id": "a", "op": "select_feature", "name": street_names(street)[0], "within": brgy},
                                {**av, "input": "a", "applies_to": "area"}],
                        assumptions=["The named place's OSM outline, cut to the barangay, stands for its lots"],
                        confidence=0.5, status="pending_review")
        else:
            names = street_names(street) or [street]
            lim = split_vicinity(vic)
            steps, ids = [], []
            for i, nm in enumerate(names):
                st = {"id": f"s{i}", "op": "select_roads", "name": nm, "within": brgy}
                if lim:
                    st.update({"from": lim[0], "to": lim[1], "soft_limits": True})
                steps.append(st)
                ids.append(f"s{i}")
            while len(ids) > 1:
                u = f"u{len(steps)}"
                steps.append({"id": u, "op": "union", "a": ids.pop(0), "b": ids.pop(0)})
                ids.insert(0, u)
            steps.append({**av, "input": ids[0], "applies_to": "street"})
            ass = ["Kept to the stretch inside the row's barangay (plus 20 m past its edge)"]
            if lim:
                ass.append(f"Vicinity read as limits from {lim[0]!r} to {lim[1]!r}; if a limit is not found the whole street "
                           "in the barangay is valued and the row notes it")
            elif vic:
                ass.append(f"Vicinity {vic[0]!r} read as the neighbourhood, not as a limit")
            if len(names) > 1:
                ass.append(f"Row names {len(names)} streets; all are valued")
            rule.update(interpretation=f"{code} value along {street} in {label}.", recipe=steps, assumptions=ass,
                        confidence=0.6 if lim else 0.5, status="pending_review")
        rules.append(rule)
    (ROOT / f"lgus/{PC}/values.json").write_text(json.dumps({"kind": "zonal_values", "lgu_psgc": PC, "rules": rules},
                                                            indent=1, ensure_ascii=False))
    import collections
    k = collections.Counter(r["status"] if r["recipe"] is None else r["recipe"][-1]["applies_to"] for r in rules)
    print(len(rules), "rows", dict(k))
    if unknown_brgy:
        print("barangays not in boundary data:", sorted(unknown_brgy))


if __name__ == "__main__":
    main()
