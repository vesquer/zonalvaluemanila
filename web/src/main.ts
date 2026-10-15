import maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { Protocol } from "pmtiles";

maplibregl.addProtocol("pmtiles", new Protocol().tile);

const TILES = (import.meta.env.VITE_TILES_URL as string | undefined) ?? "/tiles";
const src = (f: string) => ({ type: "vector" as const, url: `pmtiles://${location.origin}${TILES}/${f}` });

// ESA WorldCover class codes -> colours
const LC: [number, string][] = [
  [10, "#2d6a3e"], [20, "#a3b86c"], [30, "#d8e29c"], [40, "#f2d16b"], [50, "#c9565a"],
  [60, "#b9a88f"], [70, "#e8f1f7"], [80, "#4f86c6"], [90, "#79b6a8"], [95, "#3f9c7a"], [100, "#c8c6a0"],
];
const lcColor: any = ["match", ["get", "code"], ...LC.flat(), "#cccccc"];

// National harmonized zone classes -> colours
const ZONES: [string, string, string][] = [
  ["RESIDENTIAL", "#f2e55c", "Residential"], ["COMMERCIAL", "#e8453c", "Commercial"], ["INDUSTRIAL", "#8e5bc4", "Industrial"],
  ["INSTITUTIONAL", "#3f7fd9", "Institutional"], ["AGRICULTURAL", "#b5d68a", "Agricultural"], ["AGRO_INDUSTRIAL", "#c9a7e8", "Agro-industrial"],
  ["PARKS_OPEN_SPACE", "#4fbf6f", "Parks / open space"], ["CEMETERY", "#6fd48a", "Cemetery"], ["UTILITY", "#8a8f98", "Utility / transport"],
  ["TOURISM", "#f29e4c", "Tourism"], ["FOREST", "#2d6a3e", "Forest"],
];
const zoneColor: any = ["match", ["get", "zone_national"], ...ZONES.flatMap(([k, c]) => [k, c]), "#b0b0b0"];

// Zonal values (BIR schedules, Quezon City MVP): PHP per square metre bands, one blue ramp light -> dark
const BANDS: [number, string, string][] = [
  [0, "#b7d3f6", "Under 1k"], [1000, "#86b6ef", "1k–5k"], [5000, "#5598e7", "5k–20k"],
  [20000, "#2a78d6", "20k–50k"], [50000, "#1c5cab", "50k–100k"], [100000, "#104281", "Over 100k"],
];
const valueColor: any = ["step", ["get", "value_php_sqm"], BANDS[0][1], ...BANDS.slice(1).flatMap(([t, c]) => [t, c])];
const CLASSES: [string, string][] = [
  ["RR", "Residential"], ["CR", "Commercial"], ["I", "Industrial"], ["X", "Institutional"],
  ["GL", "Government land"], ["GP", "General purpose"], ["CL", "Cemetery lot"], ["APD", "Area for priority development"],
];
const CLASS_NAME = Object.fromEntries(CLASSES);
const VALUES_NOTE = "Official tax valuation, not market price";
// ?view=values opens the zonal value map: Quezon City, residential, zoning and land cover off
const VALUES_VIEW = new URLSearchParams(location.search).get("view") === "values";
const vis = (on: boolean) => ({ visibility: (on ? "visible" : "none") as "visible" | "none" });
const byClass = (c: string): any => ["==", ["get", "class_code"], c];

const map = new maplibregl.Map({
  container: "map",
  hash: true, // shareable URL: position, zoom
  center: VALUES_VIEW ? [121.04, 14.66] : [122, 12],
  zoom: VALUES_VIEW ? 12 : 5,
  minZoom: 4,
  maxZoom: 18,
  style: {
    version: 8,
    sources: {
      admin: src("admin.pmtiles"),
      landcover: src("landcover.pmtiles"),
      roads: src("roads.pmtiles"),
      zoning: src("zoning.pmtiles"),
      values: src("values.pmtiles"),
    },
    layers: [
      { id: "bg", type: "background", paint: { "background-color": "#dfe9f2" } },
      { id: "landcover", type: "fill", source: "landcover", "source-layer": "landcover", filter: ["!=", ["get", "code"], 80],
        layout: vis(!VALUES_VIEW), paint: { "fill-color": lcColor, "fill-opacity": 0.6 } },
      { id: "zoning", type: "fill", source: "zoning", "source-layer": "zoning",
        layout: vis(!VALUES_VIEW), paint: { "fill-color": zoneColor, "fill-opacity": 0.75 } },
      { id: "zoning-line", type: "line", source: "zoning", "source-layer": "zoning", minzoom: 11,
        layout: vis(!VALUES_VIEW), paint: { "line-color": "#333", "line-width": 0.6, "line-opacity": 0.6 } },
      // barangay interiors ("all other streets") under named areas (subdivisions, villages)
      { id: "values-areas", type: "fill", source: "values", "source-layer": "value_areas", filter: byClass("RR"),
        layout: vis(VALUES_VIEW),
        paint: { "fill-color": valueColor, "fill-opacity": ["case", ["==", ["get", "applies_to"], "interior"], 0.45, 0.7] } },
      { id: "values-areas-line", type: "line", source: "values", "source-layer": "value_areas", filter: byClass("RR"), minzoom: 13,
        layout: vis(VALUES_VIEW), paint: { "line-color": "#fcfcfb", "line-width": 1 } },
      { id: "roads", type: "line", source: "roads", "source-layer": "roads", minzoom: 7,
        paint: {
          "line-color": ["match", ["get", "class"], ["motorway", "trunk", "primary"], "#e0803a", ["secondary"], "#e8b04a", "#ffffff"],
          "line-width": ["interpolate", ["linear"], ["zoom"], 7, 0.5, 14, 2.5],
        } },
      { id: "admin4", type: "line", source: "admin", "source-layer": "admin4", minzoom: 12,
        paint: { "line-color": "#8a8f98", "line-width": 0.5, "line-dasharray": [2, 2] } },
      { id: "admin3", type: "line", source: "admin", "source-layer": "admin3", minzoom: 9,
        paint: { "line-color": "#6b7280", "line-width": 0.8 } },
      { id: "admin2", type: "line", source: "admin", "source-layer": "admin2", minzoom: 5,
        paint: { "line-color": "#4b5563", "line-width": 1 } },
      { id: "admin1", type: "line", source: "admin", "source-layer": "admin1",
        paint: { "line-color": "#1f2937", "line-width": 1.4 } },
      // valued street segments: dark casing so the light bands stay visible, then the value colour
      { id: "values-streets-casing", type: "line", source: "values", "source-layer": "value_streets", filter: byClass("RR"),
        layout: { ...vis(VALUES_VIEW), "line-cap": "round" },
        paint: { "line-color": "#1f2937", "line-opacity": 0.55, "line-width": ["interpolate", ["linear"], ["zoom"], 11, 2.5, 16, 7] } },
      { id: "values-streets", type: "line", source: "values", "source-layer": "value_streets", filter: byClass("RR"),
        layout: { ...vis(VALUES_VIEW), "line-cap": "round" },
        paint: { "line-color": valueColor, "line-width": ["interpolate", ["linear"], ["zoom"], 11, 1.5, 16, 5] } },
      // a street with two different values for one classification: never resolved, marked for review
      { id: "values-conflicts", type: "line", source: "values", "source-layer": "value_streets", minzoom: 13,
        filter: ["all", byClass("RR"), ["!=", ["get", "conflict_with"], ""]], layout: vis(VALUES_VIEW),
        paint: { "line-color": "#d03b3b", "line-width": 1.5, "line-dasharray": [1, 1.5], "line-offset": 5 } },
      // wide invisible line: a tap target bigger than the mark
      { id: "values-streets-hit", type: "line", source: "values", "source-layer": "value_streets", filter: byClass("RR"),
        layout: vis(VALUES_VIEW), paint: { "line-color": "#000", "line-opacity": 0, "line-width": 14 } },
    ],
  },
});
map.addControl(new maplibregl.NavigationControl());
map.addControl(new maplibregl.ScaleControl());

// --- layer panel: on/off + opacity ---
const VALUE_LAYERS = ["values-areas", "values-areas-line", "values-streets-casing", "values-streets", "values-conflicts", "values-streets-hit"];
const TOGGLES: { label: string; ids: string[]; on: boolean; opacity?: [string, string, number] }[] = [
  { label: "Zonal values (Quezon City)", ids: VALUE_LAYERS, on: VALUES_VIEW, opacity: ["values-areas", "fill-opacity", 0.6] },
  { label: "Zoning (pilot LGUs)", ids: ["zoning", "zoning-line"], on: !VALUES_VIEW, opacity: ["zoning", "fill-opacity", 0.75] },
  { label: "Land cover", ids: ["landcover"], on: !VALUES_VIEW, opacity: ["landcover", "fill-opacity", 0.6] },
  { label: "Roads", ids: ["roads"], on: true, opacity: ["roads", "line-opacity", 1] },
  { label: "Boundaries", ids: ["admin1", "admin2", "admin3", "admin4"], on: true },
];
const panel = document.getElementById("layers")!;
for (const t of TOGGLES) {
  const row = document.createElement("div");
  const cb = document.createElement("input");
  cb.type = "checkbox"; cb.checked = t.on;
  cb.onchange = () => t.ids.forEach((id) => map.setLayoutProperty(id, "visibility", cb.checked ? "visible" : "none"));
  const lab = document.createElement("label");
  lab.append(cb, " " + t.label);
  row.append(lab);
  if (t.opacity) {
    const r = document.createElement("input");
    r.type = "range"; r.min = "0"; r.max = "1"; r.step = "0.05"; r.value = String(t.opacity[2]);
    r.oninput = () => map.setPaintProperty(t.opacity![0], t.opacity![1], Number(r.value));
    row.append(r);
  }
  panel.append(row);
}

// --- legend ---
const NAMES: Record<number, string> = { 10: "Tree cover", 20: "Shrubland", 30: "Grassland", 40: "Cropland", 50: "Built-up", 60: "Bare", 70: "Snow/ice", 80: "Water", 90: "Wetland", 95: "Mangroves", 100: "Moss" };
document.getElementById("legend")!.innerHTML = LC.filter(([c]) => ![70, 100].includes(c))
  .map(([c, col]) => `<div><i style="background:${col}"></i>${NAMES[c]}</div>`).join("");

// --- zoning legend + click popup ---
document.getElementById("zlegend")!.innerHTML = ZONES.map(([, c, n]) => `<div><i style="background:${c}"></i>${n}</div>`).join("");
function zoningPopup(p: any) {
  return `<b>${esc(p.zone_local)}</b> (${esc(String(p.zone_national).toLowerCase().replace(/_/g, " "))})<br>Rule: ${esc(p.rule_ids)}<br>` +
    `<small>Derived from public zoning text for review. Not an official zoning certification.</small>`;
}
// One click handler: a valued street wins over the area under it, values over zoning.
const CLICKABLE = ["values-streets-hit", "values-areas", "zoning"];
map.on("click", (e) => {
  const layers = CLICKABLE.filter((id) => map.getLayoutProperty(id, "visibility") !== "none");
  const f = map.queryRenderedFeatures(e.point, { layers }).sort((a, b) => layers.indexOf(a.layer.id) - layers.indexOf(b.layer.id))[0];
  if (!f) return;
  const html = f.layer.id === "zoning" ? zoningPopup(f.properties) : valuePopup(f.properties);
  new maplibregl.Popup({ maxWidth: "300px" }).setLngLat(e.lngLat).setHTML(html).addTo(map);
});
for (const id of CLICKABLE) {
  map.on("mouseenter", id, () => (map.getCanvas().style.cursor = "pointer"));
  map.on("mouseleave", id, () => (map.getCanvas().style.cursor = ""));
}

// --- search: client-side over admin3 (cities/municipalities) names ---
const input = document.getElementById("q") as HTMLInputElement;
const results = document.getElementById("results")!;
let index: { name: string; pcode: string; province: string; c: [number, number] }[] | null = null;
async function loadIndex() {
  if (index) return index;
  index = await (await fetch(`${TILES}/search.json`)).json();
  return index!;
}
const norm = (s: string) => s.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
input.oninput = async () => {
  const q = norm(input.value.trim());
  results.innerHTML = "";
  if (q.length < 2) return;
  const hits = (await loadIndex()).filter((e) => norm(e.name).includes(q)).slice(0, 8);
  for (const h of hits) {
    const b = document.createElement("button");
    b.textContent = `${h.name}, ${h.province}`;
    b.onclick = () => { map.flyTo({ center: h.c, zoom: 11 }); results.innerHTML = ""; input.value = h.name; };
    results.append(b);
  }
};

// --- attribution panel from datasets.json ---
fetch("/datasets.json").then((r) => r.json()).then((d) => {
  document.getElementById("attrib")!.innerHTML = d.datasets
    .map((x: any) => `<li>${x.attribution} <a href="${x.url.startsWith("http") ? x.url : "#"}">${x.name}</a> (${x.version_date}, ${x.license})</li>`).join("");
});

// --- zonal values: classification filter, legend, popups, unmatched rows ---
function esc(v: unknown) {
  return String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]!);
}
const php = (n: number) => "₱" + Math.round(n).toLocaleString("en-PH");
const fmtDate = (d: string) => (/^\d{4}-\d{2}-\d{2}$/.test(d) ? new Date(d + "T00:00:00").toLocaleDateString("en-PH", { day: "numeric", month: "short", year: "numeric" }) : d);
type Meta = { schedules: Record<string, { name: string; department_order: string; revision: string; effective_date: string; url: string; listed_on: string }>;
  by_rdo: { rdo: string; in_scope: number; placed: number; match_rate: number }[]; conflicts: number; unmatched: Record<string, [string, string][]> };
let meta: Meta | null = null;

function valuePopup(p: any) {
  const s = meta?.schedules[p.rdo];
  const where = p.applies_to === "street" ? `Street segment in ${esc(p.barangay)}`
    : p.applies_to === "interior" ? `Barangay ${esc(p.barangay)}: all other streets` : `Area in ${esc(p.barangay)}`;
  const rdo = s ? `RDO ${esc(p.rdo)} ${esc(s.name)}` : `RDO ${esc(p.rdo)}`;
  const link = s ? ` · <a href="${esc(s.url)}" target="_blank" rel="noopener">schedule</a>` : "";
  return `<b style="font-size:15px">${php(Number(p.value_php_sqm))}/m²</b> · ${esc(CLASS_NAME[p.class_code] ?? p.class_code)} (${esc(p.class_code)})<br>` +
    `${where}<br><span style="color:#555">Schedule row:</span> ${esc(p.description)}<br>` +
    `BIR zonal value · ${rdo} · DO ${esc(p.department_order)}, effective ${esc(fmtDate(p.effective_date))}${link}` +
    (p.conflict_with ? `<br><span style="color:#b42318">&#9888; Another schedule row gives this street a different ${esc(p.class_code)} value (${esc(p.conflict_with)}). Not resolved; under review.</span>` : "") +
    (p.notes ? `<br><small style="color:#555">Review note: ${esc(p.notes)}</small>` : "") +
    `<br><small><b>${VALUES_NOTE}.</b></small>`;
}

const vpanel = document.getElementById("vpanel")!;
const select = document.createElement("select");
select.id = "vclass";
select.innerHTML = CLASSES.map(([c, n]) => `<option value="${c}">${n} (${c})</option>`).join("");
select.onchange = () => {
  const f = byClass(select.value);
  for (const id of VALUE_LAYERS) map.setFilter(id, id === "values-conflicts" ? ["all", f, ["!=", ["get", "conflict_with"], ""]] : f);
};
const lab = document.createElement("label");
lab.append("Classification ", select);
const legend = document.createElement("div");
legend.id = "vlegend";
legend.innerHTML = `<div class="vnote">${VALUES_NOTE}</div><div class="vunit">PHP per m²</div>` +
  BANDS.map(([, c, n]) => `<div><i style="background:${c}"></i>${n}</div>`).join("") +
  `<div><i class="vconf"></i>Two values, under review</div>`;
const gaps = document.createElement("details");
gaps.id = "vgaps";
vpanel.append(lab, legend, gaps);

fetch(`${TILES}/values_meta.json`).then((r) => r.json()).then((m: Meta) => {
  meta = m;
  const rows = Object.values(m.unmatched).reduce((a, v) => a + v.length, 0);
  const placed = m.by_rdo.reduce((a, r) => a + r.placed, 0), inScope = m.by_rdo.reduce((a, r) => a + r.in_scope, 0);
  const sched = Object.entries(m.schedules).map(([rdo, s]) =>
    `<li>RDO ${esc(rdo)} ${esc(s.name)}: <a href="${esc(s.url)}" target="_blank" rel="noopener">DO ${esc(s.department_order)}</a>, ${esc(fmtDate(s.effective_date))}</li>`).join("");
  gaps.innerHTML = `<summary>${placed.toLocaleString()} of ${inScope.toLocaleString()} schedule rows mapped; ${rows.toLocaleString()} not on the map</summary>` +
    `<ul>${sched}</ul><div id="vlist"></div>`;
  gaps.ontoggle = () => {
    const list = document.getElementById("vlist")!;
    if (!gaps.open || list.childElementCount) return;
    list.innerHTML = Object.entries(m.unmatched).sort(([a], [b]) => a.localeCompare(b)).map(([b, items]) =>
      `<details><summary>${esc(b)} (${items.length})</summary><ul>` +
      items.map(([t, why]) => `<li>${esc(t)}<br><span class="why">${esc(why)}</span></li>`).join("") + "</ul></details>").join("");
  };
}).catch(() => { gaps.innerHTML = "<summary>Schedule details unavailable</summary>"; });
