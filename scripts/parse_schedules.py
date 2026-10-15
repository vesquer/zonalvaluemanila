"""Parses one city's BIR zonal value schedules (its RDOs in scripts/cities.json) into rows.

usage: python scripts/parse_schedules.py <pcode>
In:  data/valuation/rdo<N>.zip (as downloaded) and the .xls inside it, unzipped to data/valuation/rdo<N>/.
Out: data/prep/<pcode>_rows.json (one row per street/class/value) and lgus/<pcode>/valuation_sources.json.

Only the sheet of the department order marked "Present" on the NOTICE sheet is read. A blank street cell
continues the street above it (the schedules list one street with several classes that way)."""
import datetime as dt
import hashlib
import json
import pathlib
import re
import sys
import xlrd

ROOT = pathlib.Path(__file__).resolve().parents[1]
CITIES = json.loads((ROOT / "scripts/cities.json").read_text())
PAGE = "https://www.bir.gov.ph/zonal-values"
CODE = re.compile(r"^(RR|CR|RC|CC|PS|I|X|GP|CL|GL|APD|A\d{0,2})$")


def sha256(p: pathlib.Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def cell(v) -> str:
    return re.sub(r"\s+", " ", str(v)).strip()


def to_date(v, book) -> str:
    """Effectivity dates come as Excel serials, '2/17/2024' or 'April 19, 2024'."""
    if isinstance(v, float):
        return dt.datetime(*xlrd.xldate_as_tuple(v, book.datemode)).date().isoformat()
    s = cell(v)
    for f in ("%m/%d/%Y", "%B %d, %Y", "%b %d, %Y"):
        try:
            return dt.datetime.strptime(s, f).date().isoformat()
        except ValueError:
            pass
    return s


def norm_do(do: str) -> str:
    """'037-2024' stays; Manila's NOTICE sheets write '27-19' or '077-18' for 027-2019 and 077-2018."""
    do = re.sub(r"\s+", "", do)
    m = re.fullmatch(r"(\d{1,3})-(\d{2}|\d{4})", do)
    return f"{int(m.group(1)):03d}-{m.group(2) if len(m.group(2)) == 4 else '20' + m.group(2)}" if m else do


def current_order(book):
    """The NOTICE row whose 'To' column reads Present: (DO, revision, effective date, sheet)."""
    n = book.sheet_by_index(0)
    for r in range(n.nrows):
        v = n.row_values(r)
        if any(cell(x).lower() == "present" for x in v):
            do, rev, frm = cell(v[0]), cell(v[1]), v[2]
            num = do.split("-")[0].lstrip("0")
            sheet = next(s for s in book.sheet_names() if re.search(rf"DO\s*0*{num}-", s) or s.strip().startswith("Sheet 8"))
            return norm_do(do), rev, to_date(frm, book), sheet
    raise SystemExit("no 'Present' row on NOTICE sheet")


def label_value(vals: list, label: re.Pattern) -> str | None:
    """'BARANGAY | AMIHAN', 'BARANGAY : ALICIA' or 'Zone/Barangay | | :   BOTOCAN' -> the name."""
    for i, v in enumerate(vals):
        m = label.match(cell(v))
        if m:
            rest = cell(v)[m.end():].lstrip(" :")
            if rest:
                return rest
            for w in vals[i + 1:]:
                w = cell(w).lstrip(" :")
                if w:
                    return w
    return None


BRGY = re.compile(r"^(zone\s*/\s*)?barangay(\s*/\s*zone)?\b", re.I)


def numbered(b: str) -> str | None:
    """Manila's barangays are numbered and each RDO file heads them its own way: '206', '649.0', '1/1' (barangay/zone),
    'Zone 30 / Brgy 306', 'ZONE 71 / Brgy 663 - A', or zone and barangay run together ('71661.0' = zone 71, 661).
    -> 'Barangay 661', 'Barangay 663-A', the names in the boundary data. None for a heading without a number."""
    m = re.search(r"\b(?:br?gy|barangay)\.?\s*(\d+)\s*(?:-\s*([A-Z])\b)?", b, re.I)
    if m:
        return f"Barangay {int(m.group(1))}" + (f"-{m.group(2).upper()}" if m.group(2) else "")
    m = re.match(r"^\s*(\d+(?:\.0)?)\s*(?:/\s*\d+)?", b)
    if not m:
        return None
    n = int(float(m.group(1)))
    return f"Barangay {n % 1000 if n >= 10000 else n}"
DO_LABEL = re.compile(r"^d\.?\s*o\.?\s*no\.?", re.I)


def parse(rdo: str, name: str, xls: pathlib.Path, numbered_brgys: bool = False) -> tuple[dict, list[dict]]:
    book = xlrd.open_workbook(str(xls))
    do, rev, eff, sheet_name = current_order(book)
    s = book.sheet_by_name(sheet_name)
    rows, brgys = [], []
    brgy = None
    in_table = False
    prev = None
    for r in range(s.nrows):
        vals = s.row_values(r)
        texts = [cell(v) for v in vals]
        if not any(texts):
            continue
        b = label_value(vals, BRGY)
        if b and numbered_brgys:
            b = numbered(b)  # a heading without a number is a footnote: the barangay above continues
            if b is None:
                continue
        if b:
            brgy = re.sub(r"\(\s*cont.*$", "", b, flags=re.I).strip(" .")
            if brgy not in brgys:
                brgys.append(brgy)
            in_table, prev = False, None
            continue
        if re.sub(r"\s+", "", texts[0]).upper().startswith("STREET"):  # also 'S T R E E T  N A M E'
            in_table = True
            continue
        if not in_table or brgy is None:
            continue
        ci = next((i for i, t in enumerate(texts) if CODE.match(t)), None)
        num = [i for i, v in enumerate(vals) if isinstance(v, float) and v > 0]
        if ci is None or not num or num[-1] < ci:
            continue  # notes, footnotes, page furniture
        street = texts[0].lstrip("* ").strip()
        vicinity = [t.lstrip("* ") for t in texts[1:ci] if t]
        if not street:
            if prev is None:
                continue
            street, vicinity = prev["street"], prev["vicinity"]
        row = {"rdo": rdo, "department_order": do, "barangay": brgy, "street": street, "vicinity": vicinity,
               "class_code": texts[ci], "value_php_sqm": float(vals[num[-1]]), "sheet": sheet_name, "row": r + 1}
        rows.append(row)
        prev = row
    src = {"rdo": rdo, "name": name, "department_order": do, "revision": rev, "effective_date": eff, "sheet": sheet_name,
           "barangays": brgys}
    return src, rows


def main() -> None:
    pc = sys.argv[1]
    city = CITIES[pc]
    vs = ROOT / f"lgus/{pc}/valuation_sources.json"
    before = {x["xls_sha256"]: x["downloaded"] for x in json.loads(vs.read_text())["schedules"]} if vs.exists() else {}
    sources, rows = [], []
    for rdo, (name, url) in city["rdos"].items():
        z = ROOT / f"data/valuation/rdo{rdo}.zip"
        xls = next((ROOT / f"data/valuation/rdo{rdo}").glob("*.xls*"))
        src, rr = parse(rdo, name, xls, city.get("numbered_barangays", False))
        h = sha256(xls)
        src.update({"url": url, "listed_on": PAGE,
                    "zip_sha256": sha256(z), "xls_filename": xls.name, "xls_sha256": h,
                    "downloaded": before.get(h) or dt.datetime.fromtimestamp(z.stat().st_mtime).date().isoformat(),
                    "local": str(xls.relative_to(ROOT)), "rows": len(rr)})
        sources.append(src)
        rows += rr
        print(f"RDO {rdo}: DO {src['department_order']} ({src['revision']}, effective {src['effective_date']}), "
              f"{len(src['barangays'])} barangays, {len(rr)} rows")
    out = ROOT / f"data/prep/{pc}_rows.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rows, indent=0, ensure_ascii=False))
    doc = {"lgu": city["lgu"], "adm3_pcode": pc, "valuation_base": "BIR zonal values",
           "smv": {"status": "none recorded", "note": "Under RA 12001 an approved City Schedule of Market Values replaces BIR zonal values; "
                                                      "record it here when approved and rebuild."},
           "schedules": sources}
    vs.parent.mkdir(parents=True, exist_ok=True)
    vs.write_text(json.dumps(doc, indent=1, ensure_ascii=False))
    print(len(rows), "rows ->", out.relative_to(ROOT))


if __name__ == "__main__":
    main()
