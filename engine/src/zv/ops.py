"""Geometry operations: the fixed vocabulary. New operations only by code change with tests."""
from __future__ import annotations
import unicodedata
import shapely
from shapely.geometry import Polygon
from shapely.geometry.base import BaseGeometry
from shapely.ops import polygonize, unary_union
from .base import Base


class SelectionEmpty(Exception):
    """A selection found nothing: the recipe stops and raises a review flag; geometry is never guessed."""


class AmbiguousName(SelectionEmpty):
    """An approximate name matched several different places: a reviewer must pick; never guess."""


# Barangay outlines (COD-AB) are indicative and can sit 50-100 m off the streets, so a barangay scope is generous.
SCOPE_M = 150.0  # names are looked for this close to the barangay
END_M = 300.0    # from/to limits are looked for this close to the barangay
EDGE_M = 50.0    # a street valued in one barangay is kept this far past its edge


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


_ABBR = {"sct": "scout", "gen": "general", "col": "colonel", "sgt": "sergeant", "hon": "honorable", "sto": "santo", "sta": "santa",
         "dr": "doctor", "atty": "attorney", "capt": "captain", "lt": "lieutenant", "pres": "president", "mt": "mount", "bgy": "barangay",
         "vill": "village", "subd": "subdivision", "ext": "extension"}


def _words(s: str) -> list[str]:
    """Significant words in order."""
    words = _norm(str(s).replace(".", ". ")).replace("-", " ").replace(",", " ").replace("ñ", "n").replace("'", "").split()
    if len(words) > 1 and words[-1] == "dr":  # "Bellevue Dr." is a drive, "Dr. Garcia" a doctor
        words[-1] = "drive"
    return [_ABBR.get(t, t) for t in words if t not in _STOP]


def _tokens(s: str) -> set[str]:
    return set(_words(s))


def _covers(have: set[str], want: set[str]) -> bool:
    """Every wanted token is in `have`; a one-letter token is an initial ("A. Bonifacio" = "Andres Bonifacio")."""
    return all(t in have or (len(t) == 1 and any(h.startswith(t) for h in have)) for t in want) and \
        any(len(t) > 1 for t in want)


def _name_match(series, name: str, log: list[str] | None = None, aliases: dict[str, list[str]] | None = None,
                scoped: bool = False, where: str | list[str] = ""):
    """A reviewed alias first; else exact (case/punctuation-insensitive); else every significant token of `name`
    must appear in the candidate's name. Approximate matches are logged for review. `scoped`: the candidates are
    already limited to a small area (one barangay), so a one-word name may match a candidate with exactly that word."""
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
    want = _tokens(name)
    if not want:
        return exact
    if len(want) < 2:  # one significant word ("Dao", "Walnut") is too weak to match loosely city-wide
        if not scoped:
            return exact
        loose = series.fillna("").map(lambda v: bool(v) and _tokens(v) == want)
    else:
        loose = series.fillna("").map(lambda v: bool(v) and _covers(_tokens(v), want))
    if loose.any():
        names = sorted(set(series[loose]))
        same = [x for x in names if _words(x) == _words(name)]  # "Tandang Sora Ave" is the avenue, not "... Avenue Extension"
        if len({_norm(x) for x in names}) > 1 and len({_norm(x) for x in same}) == 1:
            loose = series.fillna("").map(lambda v: _norm(v) == _norm(same[0]))
            names = sorted(set(series[loose]))
        if len({_norm(x) for x in names}) > 1:  # case/punctuation variants of one name are the same place
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
    """`within`: a barangay name (or several); only roads in it are searched and the result is kept to it (plus EDGE_M).
    `soft_limits`: if a from/to limit cannot be found, keep the whole road (inside `within`) and log it for review."""
    area = _within(b, within)
    if area is not None:
        near = area.buffer(SCOPE_M)
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
        g = g.intersection(area.buffer(EDGE_M))
        if g.is_empty or g.length == 0:
            # the named road is near but wholly outside the (indicative) outline: keep what lies within the search scope
            g = whole.intersection(near)
            b.match_log.append(f"{name!r} lies outside the {within} outline; kept within {SCOPE_M:.0f} m of it")
    if frm or to:
        try:
            g = _limit(b, g, name, frm, to, None if area is None else area.buffer(END_M))
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


def select_water(b: Base, *, kind: str = "", name: str = "") -> BaseGeometry:
    w = b.water
    if kind:
        w = w[w["kind"] == kind]
    if name:
        w = w[_name_match(w["name"], name, b.match_log)]
    if w.empty:
        raise SelectionEmpty(f"no water for kind={kind!r} name={name!r}")
    return unary_union(w.geometry.values)


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
        near = area.buffer(SCOPE_M)
    feats = _near(b.features, near)
    f = feats[_name_match(feats["name"], name, b.match_log, b.aliases, scoped=near is not None, where=within)]
    if f.empty:
        raise SelectionEmpty(f"feature not found: {name!r}" + (f" in {within}" if within else ""))
    g = unary_union(f.geometry.values)
    if area is not None and g.geom_type in ("Polygon", "MultiPolygon"):
        g = g.intersection(area)
    return g


def buffer(b: Base, g: BaseGeometry, *, width_m: float, measured_from: str = "centerline", sides: str = "both",
           road_class: str | None = None) -> BaseGeometry:
    if width_m <= 0:
        raise ValueError("width_m must be > 0")
    w = width_m
    if measured_from == "row_edge":
        w += b.row_half_width.get(road_class or "", 0.0)
    if g.geom_type in ("Polygon", "MultiPolygon", "Point", "MultiPoint"):
        return g.buffer(w)
    if sides == "both":
        return g.buffer(w, cap_style="flat")  # corridor ends where the road segment ends
    parts = g.geoms if hasattr(g, "geoms") else [g]
    if sides in ("north", "south", "east", "west"):
        # keep, per road part, the single-sided buffer that lies further toward that compass side
        axis, sign = {"north": (1, 1), "south": (1, -1), "east": (0, 1), "west": (0, -1)}[sides]
        out = []
        for p in parts:
            cands = [p.buffer(w, single_sided=True, cap_style="flat"), p.buffer(-w, single_sided=True, cap_style="flat")]
            out.append(max(cands, key=lambda c: sign * (c.centroid.y if axis else c.centroid.x)))
        return unary_union(out)
    if sides not in ("left", "right"):
        raise ValueError(f"sides must be both/left/right/north/south/east/west, got {sides!r}")
    d = w if sides == "left" else -w
    return unary_union([p.buffer(d, single_sided=True, cap_style="flat") for p in parts])


def between(b: Base, *geoms: BaseGeometry) -> BaseGeometry:
    u = unary_union([x.boundary if x.geom_type.endswith("Polygon") else x for x in geoms])
    polys = list(polygonize(u))
    if not polys:
        raise SelectionEmpty("boundary features do not enclose an area")
    return unary_union(polys)


def union(a: BaseGeometry, c: BaseGeometry) -> BaseGeometry:
    return a.union(c)


def intersect(a: BaseGeometry, c: BaseGeometry) -> BaseGeometry:
    return a.intersection(c)


def subtract(a: BaseGeometry, c: BaseGeometry) -> BaseGeometry:
    return a.difference(c)


def clip(b: Base, g: BaseGeometry, *, to: str = "lgu", names: list[str] | None = None) -> BaseGeometry:
    area = b.lgu if to == "lgu" else select_admin(b, names=names or [])
    return g.intersection(area)


def polygons_only(g: BaseGeometry) -> BaseGeometry:
    """Drop slivers/lines left by boolean ops; keep polygonal parts."""
    if g.is_empty:
        return g
    parts = [p for p in (g.geoms if hasattr(g, "geoms") else [g]) if p.geom_type in ("Polygon", "MultiPolygon")]
    return shapely.make_valid(unary_union(parts)) if parts else Polygon()
