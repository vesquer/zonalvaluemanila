"""Selections that place a schedule row. New operations only by code change with tests."""
from __future__ import annotations
import unicodedata
import shapely
from shapely.geometry import Polygon
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union
from .base import Base


class SelectionEmpty(Exception):
    """A selection found nothing: the recipe stops and raises a review flag; geometry is never guessed."""


class AmbiguousName(SelectionEmpty):
    """An approximate name matched several different places: a reviewer must pick; never guess."""


# Barangay outlines (COD-AB) are indicative and can sit 50-100 m off the streets, so a barangay scope is generous:
# Base.scope_m (150 m), Base.end_m (300 m) and Base.edge_m (50 m) by default.


def _norm(s: str) -> str:
    s = "".join(c for c in unicodedata.normalize("NFKD", str(s)) if not unicodedata.combining(c))  # Argüelles = Arguelles
    s = s.lower().replace("hi-way", "highway").replace("hiway", "highway").replace(" hway", " highway")
    return " ".join(s.replace(".", "").replace(",", " ").replace("ñ", "n").split())


def alias_map(raw: dict[str, list[str] | str]) -> dict[str, list[str]]:
    """Reviewed name aliases (schedule or ordinance spelling -> names in the base data), keyed for lookup.
    A key "NAME @ Barangay" applies only to searches inside that barangay."""
    return {_alias_key(*k.split("@", 1)): ([v] if isinstance(v, str) else list(v)) for k, v in raw.items() if not k.startswith("_")}


def _alias_key(name: str, where: str | list[str] = "") -> str:
    where = ",".join(where) if isinstance(where, list) else where
    return _norm(name) + ("@" + _norm(where) if where.strip() else "")


_STOP = {"road", "street", "avenue", "highway", "st", "ave", "rd", "blvd", "boulevard", "the", "of", "and", "creek", "river"}
SUFFIX = {"sr", "jr"}  # optional in the wanted name: "LEON GUINTO SR" = "Leon Guinto Street", not the other way round


_ABBR = {"sct": "scout", "gen": "general", "col": "colonel", "sgt": "sergeant", "hon": "honorable", "sto": "santo", "sta": "santa",
         "dr": "doctor", "atty": "attorney", "capt": "captain", "cpl": "corporal", "pvt": "private", "maj": "major", "lt": "lieutenant", "pres": "president", "mt": "mount", "bgy": "barangay",
         "vill": "village", "subd": "subdivision", "cmpd": "compound", "exec": "executive", "ext": "extension"}
# Named places are often mapped without their designator ("CAPITOL 8 SUBD." is "Capitol 8" in OSM), so area names
# are compared without these words too.
_AREA = _STOP | {"subdivision", "subdivisions", "subd", "village", "vill", "compound", "cmpd", "homes", "townhomes", "townhouse",
                 "townhouses", "estate", "estates", "sitio"}


def _words(s: str, stop: set[str] = _STOP) -> list[str]:
    """Significant words in order."""
    words = _norm(str(s).replace(".", ". ")).replace("-", " ").replace(",", " ").replace("ñ", "n").replace("'", "").split()
    if len(words) > 1 and words[-1] == "dr":  # "Bellevue Dr." is a drive, "Dr. Garcia" a doctor
        words[-1] = "drive"
    if len(words) > 1 and words[0] == "st":  # "St. Paul" is a saint, "Paul St." a street
        words[0] = "saint"
    # run-together initials: "TM KALAW" = "T. M. Kalaw" (two or three letters, no vowel, not an abbreviation)
    split = [c for w in words for c in (list(w) if 2 <= len(w) <= 3 and w.isalpha() and not set(w) & set("aeiouy")
                                         and w not in _ABBR and w not in _STOP else [w])]
    if any(len(t) > 1 and t not in _STOP for t in split):  # "MRR ROAD" keeps MRR: nothing else would name it
        words = split
    words = [_ABBR.get(t, t) for t in words]
    return [t for t in words if t not in stop]


def _tokens(s: str, stop: set[str] = _STOP) -> set[str]:
    return set(_words(s, stop))


def _covers(have: set[str], want: set[str]) -> bool:
    """Every wanted token is in `have`; a one-letter token on either side is an initial ("A. Bonifacio" = "Andres
    Bonifacio", "Felipe Pike" = "F. Pike Street")."""
    def ok(t):
        return t in have or (len(t) == 1 and any(h.startswith(t) for h in have)) or \
            (len(t) > 1 and not t.isdigit() and t[0] in have)
    return all(ok(t) for t in want) and any(len(t) > 1 and t in have for t in want)


def _name_match(series, name: str, log: list[str] | None = None, aliases: dict[str, list[str]] | None = None,
                scoped: bool = False, where: str | list[str] = "", stop: set[str] = _STOP):
    """A reviewed alias first; else exact (case/punctuation-insensitive); else every significant token of `name`
    must appear in the candidate's name. Approximate matches are logged for review. `scoped`: the candidates are
    already limited to a small area (one barangay), so a one-word name may match a candidate with exactly that word.
    `stop`: words ignored when comparing (_AREA for named places)."""
    n = _norm(name)
    for key in ([_alias_key(name, where)] if where else []) + [n]:
        if aliases and key in aliases:
            wanted = {_norm(a) for a in aliases[key]}
            hit = series.fillna("").map(lambda v: _norm(v) in wanted)
            if hit.any():
                return hit
    exact = series.fillna("").map(lambda v: _norm(v) == n)
    if exact.any():
        return exact
    want = _tokens(name, stop) - SUFFIX
    if not want:
        return exact
    if len(want) < 2:  # one significant word ("Dao", "Walnut") is too weak to match loosely city-wide
        if not scoped:
            return exact
        loose = series.fillna("").map(lambda v: bool(v) and _tokens(v, stop) == want)
    else:
        loose = series.fillna("").map(lambda v: bool(v) and _covers(_tokens(v, stop), want))
    if loose.any():
        names = sorted(set(series[loose]))
        same = [x for x in names if _words(x, stop) == _words(name, stop)]  # "Tandang Sora Ave" is the avenue, not "... Avenue Extension"
        key = lambda x: tuple(_words(x, stop))  # "MH Del Pilar St" and "M. H. del Pilar Street" are one place
        if len({key(x) for x in names}) > 1 and len({key(x) for x in same}) == 1:
            loose = series.fillna("").map(lambda v: bool(v) and key(v) == key(same[0]))
            names = sorted(set(series[loose]))
        if len({key(x) for x in names}) > 1:  # spelling variants of one name are the same place
            raise AmbiguousName(f"{name!r} is ambiguous; candidates: " + "; ".join(names[:6]))
        if log is not None:
            log.append(f"approximate name match for {name!r}: {names[0]}")
    return loose


def _near(gdf, near: BaseGeometry | None):
    return gdf if near is None else gdf.iloc[gdf.sindex.query(near, predicate="intersects")]


def _within(b: Base, within: str | list[str]) -> BaseGeometry | None:
    if not within:
        return None
    return select_admin(b, names=[within] if isinstance(within, str) else list(within))


def select_roads(b: Base, *, name: str = "", cls: str = "", frm: str = "", to: str = "", within: str | list[str] = "",
                 soft_limits: bool = False, near: BaseGeometry | None = None) -> BaseGeometry:
    """`within`: a barangay name (or several); only roads in it are searched and the result is kept to it (plus b.edge_m).
    `soft_limits`: if a from/to limit cannot be found, keep the whole road (inside `within`) and log it for review."""
    area = _within(b, within)
    if area is not None:
        near = area.buffer(b.scope_m)
    r = _near(b.roads, near)
    if cls == "national":
        r = r[r["class"].isin(b.national_classes)]
    elif cls:
        r = r[r["class"] == cls]
    if name:
        r = r[_name_match(r["name"], name, b.match_log, b.aliases, scoped=near is not None, where=within)]
    if r.empty:
        what = f"no {cls} road" if cls else "no road"
        raise SelectionEmpty((f"{what} named {name!r}" if name else what) + (f" in {within}" if within else ""))
    g = unary_union(r.geometry.values)
    if area is not None:
        whole = g
        g = g.intersection(area.buffer(b.edge_m))
        if g.is_empty or g.length == 0:
            # the named road is near but wholly outside the (indicative) outline: keep what lies within the search scope
            g = whole.intersection(near)
            b.match_log.append(f"{name!r} lies outside the {within} outline; kept within {b.scope_m:.0f} m of it")
    if frm or to:
        try:
            g = _limit(b, g, name, frm, to, None if area is None else area.buffer(b.end_m))
        except SelectionEmpty as e:
            if not soft_limits:
                raise
            b.match_log.append(f"limits {frm!r} to {to!r} not found for {name!r} ({e}); the whole road" + (f" in {within}" if within else "") + " is valued")
    return g


def _limit(b: Base, g: BaseGeometry, name: str, frm: str, to: str, near: BaseGeometry | None) -> BaseGeometry:
    # Approximation (flagged in assumptions): keep the part of the road inside the hull of the
    # from/to features. A lineal end (another road) counts as the points where it crosses this road.
    ends = []
    for x in (frm, to):
        if not x:
            continue
        e = select_admin(b, names=[x]) if _has_admin(b, x) else _end_feature(b, x, near)
        if e.geom_type in ("LineString", "MultiLineString"):
            e = g.intersection(e.buffer(8))  # crossing area
            if e.is_empty:
                raise SelectionEmpty(f"road {name!r} does not cross {x!r}")
        ends.append(e)
    g = g.intersection(unary_union(ends).convex_hull.buffer(1))
    if g.is_empty:
        raise SelectionEmpty(f"road {name!r} does not pass between {frm!r} and {to!r}")
    return g


def _end_feature(b: Base, name: str, near: BaseGeometry | None = None) -> BaseGeometry:
    """A from/to limit: a named road first (limits are usually crossing roads), else a named site."""
    try:
        return select_roads(b, name=name, near=near)
    except SelectionEmpty as road_err:
        try:
            return select_feature(b, name=name, near=near)
        except SelectionEmpty:
            raise road_err


def _has_admin(b: Base, name: str) -> bool:
    n = _norm(name)
    return bool(b.admin["name"].fillna("").map(_norm).eq(n).any())


def select_admin(b: Base, *, names: list[str] | None = None, pcodes: list[str] | None = None, whole_lgu: bool = False) -> BaseGeometry:
    if whole_lgu:
        return b.lgu
    a = b.admin
    if pcodes:
        a = a[a["pcode"].isin(pcodes)]
    elif names:
        wanted = {_norm(n) for n in names}
        a = a[a["name"].fillna("").map(_norm).isin(wanted)]
        missing = wanted - set(a["name"].map(_norm))
        if missing:
            raise SelectionEmpty(f"admin names not found: {sorted(missing)}")
    if a.empty:
        raise SelectionEmpty("no admin areas selected")
    return unary_union(a.geometry.values)


def select_feature(b: Base, *, name: str, within: str | list[str] = "", near: BaseGeometry | None = None) -> BaseGeometry:
    """`within`: a barangay name (or several); only sites in it are searched and an outline is cut to it."""
    area = _within(b, within)
    if area is not None:
        near = area.buffer(b.scope_m)
    feats = _near(b.features, near)
    f = feats[_name_match(feats["name"], name, b.match_log, b.aliases, scoped=near is not None, where=within, stop=_AREA)]
    if f.empty:
        raise SelectionEmpty(f"feature not found: {name!r}" + (f" in {within}" if within else ""))
    g = unary_union(f.geometry.values)
    if area is not None and g.geom_type in ("Polygon", "MultiPolygon"):
        g = g.intersection(area)
    return g


def union(a: BaseGeometry, c: BaseGeometry) -> BaseGeometry:
    return a.union(c)


def polygons_only(g: BaseGeometry) -> BaseGeometry:
    """Drop slivers/lines left by boolean ops; keep polygonal parts."""
    if g.is_empty:
        return g
    parts = [p for p in (g.geoms if hasattr(g, "geoms") else [g]) if p.geom_type in ("Polygon", "MultiPolygon")]
    return shapely.make_valid(unary_union(parts)) if parts else Polygon()
