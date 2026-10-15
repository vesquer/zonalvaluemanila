"""Suggests road aliases for unmatched zonal value rows: for each unmatched street name, the most similar OSM road
name near the row's barangay. A reviewer accepts a suggestion by copying it into lgus/<pcode>/aliases.json.

usage: python scripts/alias_suggest.py <pcode> [rdo] [min_score]   ->  prints JSON {schedule name: [osm name, score, barangay]}"""
import difflib
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "engine/src"))
from zv import ops  # noqa: E402
from zv.cli import load_base  # noqa: E402


def main() -> None:
    pcode = sys.argv[1]
    rdo = sys.argv[2] if len(sys.argv) > 2 and sys.argv[2] != "all" else None
    min_score = float(sys.argv[3]) if len(sys.argv) > 3 else 0.8
    d = ROOT / "lgus" / pcode
    rules = {r["rule_id"]: r for r in json.loads((d / "values.json").read_text())["rules"]}
    rep = json.loads((d / "out/values_report.json").read_text())
    b = load_base(pcode)
    known = set(b.aliases)
    out = {}
    for items in rep["unmatched_by_barangay"].values():
        for it in items:
            r = rules[it["rule_id"]]
            if (rdo and r["rdo"] != rdo) or not r["recipe"] or not it["reason"].startswith("no road"):
                continue
            for st in r["recipe"]:
                if st["op"] != "select_roads" or ops._norm(st["name"]) in known or st["name"] in out:
                    continue
                area = ops._within(b, st["within"]).buffer(ops.SCOPE_M)
                near = sorted(set(ops._near(b.roads, area)["name"].dropna()))
                want = " ".join(sorted(ops._tokens(st["name"])))
                scored = sorted(((difflib.SequenceMatcher(None, want, " ".join(sorted(ops._tokens(n)))).ratio(), n) for n in near),
                                reverse=True)
                if scored and scored[0][0] >= min_score and (len(scored) == 1 or scored[1][0] < scored[0][0] - 0.05):
                    out[st["name"]] = [scored[0][1], round(scored[0][0], 2), r["barangay"]]
    print(json.dumps(out, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()
