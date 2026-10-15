#!/usr/bin/env bash
# S8: publish web/dist (page + tiles) to the gh-pages branch of a GitHub repo, served by GitHub Pages.
#   REMOTE   git remote to push to (default origin); Pages must serve "Deploy from a branch: gh-pages / (root)"
#   DRY_RUN  1 = build and check, commit into data/tmp/site, push nothing
# Checks before pushing: whole site under 20 MB, no file over 25 MB, every built city's counts in values_meta.json
# match its lgus/<pcode>/out/values_report.json.
set -euo pipefail
cd "$(dirname "$0")/.."
REMOTE=${REMOTE:-origin}
DRY_RUN=${DRY_RUN:-0}

[ -f tiles/base.pmtiles ] && [ -f tiles/values.pmtiles ] && [ -f tiles/values_meta.json ] || \
  { echo "tiles/ is incomplete: run scripts/build_base.sh and scripts/build_tiles.sh"; exit 1; }
(cd web && npm run -s build >/dev/null)

total_kb=$(du -skL web/dist | cut -f1)
big=$(find -L web/dist -type f -size +25M)
echo "site: $((total_kb / 1024)) MB in web/dist"
[ "$total_kb" -lt $((20 * 1024)) ] || { echo "over the 20 MB site budget"; exit 1; }
[ -z "$big" ] || { echo "over the 25 MB per-file limit: $big"; exit 1; }

python3 -I - <<'PY'
import json, pathlib
meta = json.load(open("web/dist/tiles/values_meta.json"))
cities = {k: v for k, v in json.load(open("scripts/cities.json")).items() if not k.startswith("_")}
bad = []
for pc, c in cities.items():
    rep = pathlib.Path(f"lgus/{pc}/out/values_report.json")
    if not rep.exists():
        continue
    want = {(r["rdo"], r["placed"], r["in_scope"]) for r in json.load(open(rep))["by_rdo"]}
    have = {(r["rdo"], r["placed"], r["in_scope"]) for r in meta["by_rdo"] if r["city"] == c["lgu"]}
    if want != have:
        bad.append(c["lgu"])
if bad:
    raise SystemExit("values_meta.json differs from the build report for " + ", ".join(bad) + ": run scripts/build_tiles.sh")
placed = sum(r["placed"] for r in meta["by_rdo"]); in_scope = sum(r["in_scope"] for r in meta["by_rdo"])
print(f"counts match the build reports: {placed:,} of {in_scope:,} rows placed")
PY

URL=$(git remote get-url "$REMOTE" 2>/dev/null) || { [ "$DRY_RUN" = 1 ] || { echo "no git remote '$REMOTE': git remote add $REMOTE <github repo url>"; exit 1; }; }
SITE=data/tmp/site
rm -rf $SITE && mkdir -p $SITE
cp -RL web/dist/. $SITE/
touch $SITE/.nojekyll  # serve files as they are, no Jekyll build
REV=$(git rev-parse --short HEAD)$(git diff --quiet HEAD -- . ':!data' || echo "-dirty")
git -C $SITE init -q -b gh-pages
git -C $SITE add -A
git -C $SITE commit -qm "Deploy zonal-value-map $REV"
if [ "$DRY_RUN" = 1 ]; then
  echo "dry run: site committed in $SITE ($REV); nothing pushed"
else
  git -C $SITE push -f "$URL" gh-pages
  echo "pushed $REV to $REMOTE gh-pages"
fi
