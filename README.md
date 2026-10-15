# Zonal Value Map

BIR zonal values for Quezon City, Manila and Pasig on a light base map. Seeded from `ph-land-use-map` at commit
`8a08a4a` (copied, not forked). Spec: "Zonal Value Map — Standalone Spec" (Claude Docs).

```
make setup                 # venv + web deps (Python 3.11+)
make test
make build PSGC=PH1307404  # lgus/<pcode>/values.json -> lgus/<pcode>/out/
make serve
```

`lgus/<pcode>/aliases.json` and the generated `values.json` are the reviewed record; their git history is the audit log.
`data/` and `tiles/` are git-ignored and rebuilt by `scripts/`.

## Rebuild a city

```
.venv/bin/python scripts/parse_schedules.py <pcode>   # data/valuation/rdo<N>/*.xls -> data/prep, valuation_sources.json
.venv/bin/python scripts/gen_values.py <pcode>        # -> lgus/<pcode>/values.json
make build PSGC=<pcode>                               # -> lgus/<pcode>/out/
.venv/bin/python scripts/alias_suggest.py <pcode> all 0.8 > lgus/<pcode>/alias_suggestions.json
./scripts/build_tiles.sh                              # every built city -> tiles/, checks the size budget
```

Cities and their schedule links are in `scripts/cities.json`. A reviewer copies accepted suggestions from
`alias_suggestions.json` into `aliases.json` (`"roads": {"SCHEDULE NAME": "OSM name"}`, or `"NAME @ Barangay"` to
hold in one barangay only), then rebuilds. Suggestions are never accepted automatically: many are wrong.

## Deploy (GitHub Pages)

`make deploy` builds `web/dist` (page + tiles), checks the budget (site under 20 MB, no file over 25 MB) and that
`values_meta.json` matches every city's build report, then force-pushes the site as a single commit to the
`gh-pages` branch of `origin`. `make deploy-check` does all of it except the push.

One-time setup: create the GitHub repo, `git remote add origin <repo url>`, `git push -u origin main`, then in the
repo's Settings → Pages choose "Deploy from a branch", `gh-pages`, `/ (root)`. The map is served at
`https://<user>.github.io/<repo>/`; paths are relative, so the folder name does not matter.
