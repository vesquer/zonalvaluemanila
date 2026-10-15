"""Parses the BIR zonal value schedules for Quezon City (RDOs 28, 38, 39, 40) into rows.

In:  data/valuation/rdo<N>.zip (as downloaded) and the .xls inside it, unzipped to data/valuation/rdo<N>/.
Out: data/prep/qc_values_rows.json (one row per street/class/value) and lgus/PH1307404/valuation_sources.json.

Only the sheet of the department order marked "Present" on the NOTICE sheet is read. A blank street cell
continues the street above it (the schedules list one street with several classes that way)."""
import datetime as dt
import hashlib
import json
import pathlib
import re
import xlrd

ROOT = pathlib.Path(__file__).resolve().parents[1]
PC = "PH1307404"
PAGE = "https://www.bir.gov.ph/zonal-values"
CDN = "https://bir-cdn.bir.gov.ph/BIR/pdf/"
RDOS = {
    "28": ("Novaliches", "RDO No. 28 - Novaliches, Quezon City"),
    "38": ("North Quezon City", "RDO No. 38 - North Quezon City"),
    "39": ("South Quezon City", "RDO No. 39 - South Quezon City"),
    "40": ("Cubao", "RDO No. 40 - Cubao"),
}
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


def current_order(book):
    """The NOTICE row whose 'To' column reads Present: (DO, revision, effective date, sheet)."""
    n = book.sheet_by_index(0)
    for r in range(n.nrows):
        v = n.row_values(r)
        if any(cell(x).lower() == "present" for x in v):
            do, rev, frm = cell(v[0]), cell(v[1]), v[2]
            num = do.split("-")[0].lstrip("0")
            sheet = next(s for s in book.sheet_names() if re.search(rf"DO\s*0*{num}-", s) or s.strip().startswith("Sheet 8"))
            return re.sub(r"\s+", "", do), rev, to_date(frm, book), sheet
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


BRGY = re.compile(r"^(zone\s*/\s*)?barangay\b", re.I)
DO_LABEL = re.compile(r"^d\.?\s*o\.?\s*no\.?", re.I)


def parse(rdo: str, xls: pathlib.Path) -> tuple[dict, list[dict]]:
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
        if b:
            brgy = re.sub(r"\(\s*cont.*$", "", b, flags=re.I).strip(" .")
            if brgy not in brgys:
                brgys.append(brgy)
            in_table, prev = False, None
            continue
        if texts[0].upper().startswith("STREET"):
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
    src = {"rdo": rdo, "name": RDOS[rdo][0], "department_order": do, "revision": rev, "effective_date": eff, "sheet": sheet_name,
           "barangays": brgys}
    return src, rows


def main() -> None:
    sources, rows = [], []
    for rdo, (_, fname) in RDOS.items():
        z = ROOT / f"data/valuation/rdo{rdo}.zip"
        xls = next((ROOT / f"data/valuation/rdo{rdo}").glob("*.xls"))
        src, rr = parse(rdo, xls)
        src.update({"url": CDN + fname.replace(" ", "%20").replace(",", ",") + ".zip", "listed_on": PAGE,
                    "zip_sha256": sha256(z), "xls_filename": xls.name, "xls_sha256": sha256(xls),
                    "downloaded": "2026-10-12", "local": str(xls.relative_to(ROOT)), "rows": len(rr)})
        sources.append(src)
        rows += rr
        print(f"RDO {rdo}: DO {src['department_order']} ({src['revision']}, effective {src['effective_date']}), "
              f"{len(src['barangays'])} barangays, {len(rr)} rows")
    out = ROOT / "data/prep/qc_values_rows.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rows, indent=0, ensure_ascii=False))
    doc = {"lgu": "Quezon City", "adm3_pcode": PC, "valuation_base": "BIR zonal values",
           "smv": {"status": "none recorded", "note": "Under RA 12001 an approved City Schedule of Market Values replaces BIR zonal values; "
                                                      "record it here when approved and rebuild."},
           "schedules": sources}
    (ROOT / f"lgus/{PC}/valuation_sources.json").write_text(json.dumps(doc, indent=1, ensure_ascii=False))
    print(len(rows), "rows ->", out.relative_to(ROOT))


if __name__ == "__main__":
    main()
