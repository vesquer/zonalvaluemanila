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
