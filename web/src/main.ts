import maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { Protocol } from "pmtiles";

maplibregl.addProtocol("pmtiles", new Protocol().tile);

const TILES = (import.meta.env.VITE_TILES_URL as string | undefined) ?? "tiles";
const tileUrl = (f: string) => new URL(`${TILES}/${f}`, location.href).href;
const src = (f: string) => ({ type: "vector" as const, url: `pmtiles://${tileUrl(f)}` });

// Zonal values: PHP per square metre bands, green (low) -> yellow -> red (high)
const BANDS: [number, string, string][] = [
  [0, "#1a9850", "Under 1k"], [1000, "#91cf60", "1k–5k"], [5000, "#d9ef8b", "5k–20k"],
  [20000, "#fee08b", "20k–50k"], [50000, "#fc8d59", "50k–100k"], [100000, "#d73027", "Over 100k"],
];
const valueColor: any = ["step", ["get", "value_php_sqm"], BANDS[0][1], ...BANDS.slice(1).flatMap(([t, c]) => [t, c])];
const CLASSES: [string, string][] = [
  ["RR", "Residential"], ["CR", "Commercial"], ["I", "Industrial"], ["X", "Institutional"],
  ["GL", "Government land"], ["GP", "General purpose"], ["CL", "Cemetery lot"], ["APD", "Area for priority development"],
];
const CLASS_NAME = Object.fromEntries(CLASSES);
const VALUES_NOTE = "Official tax valuation, not market price";
const byClass = (c: string): any => ["==", ["get", "class_code"], c];

// Quezon City, Manila and Pasig with a margin; the map does not pan beyond it
const VIEW: [number, number, number, number] = [120.95, 14.55, 121.13, 14.77];
const MAX_BOUNDS: [number, number, number, number] = [120.85, 14.45, 121.25, 14.88];
// A shared #zoom/lat/lon outside the cities (or the #10/0/0 written before the first fit) would open on empty sea:
// drop it so the map opens on VIEW.
{
  const [, lat, lon] = location.hash.slice(1).split("/").map(Number);
  const [w, s, e, n] = MAX_BOUNDS;
  if (location.hash && !(lat >= s && lat <= n && lon >= w && lon <= e)) history.replaceState(null, "", location.pathname + location.search);
}

const map = new maplibregl.Map({
  container: "map",
  hash: true, // shareable URL: position, zoom
  bounds: VIEW,
  maxBounds: MAX_BOUNDS,
  minZoom: 10,
  maxZoom: 18,
  style: {
    version: 8,
    sources: { base: src("base.pmtiles"), values: src("values.pmtiles") },
    layers: [
      { id: "bg", type: "background", paint: { "background-color": "#eef0f2" } },
      { id: "cities-fill", type: "fill", source: "base", "source-layer": "cities", paint: { "fill-color": "#f8f8f6" } },
      // barangay interiors ("all other streets") under named areas (subdivisions, villages)
      { id: "values-areas", type: "fill", source: "values", "source-layer": "value_areas", filter: byClass("RR"),
        paint: { "fill-color": valueColor, "fill-opacity": ["case", ["==", ["get", "applies_to"], "interior"], 0.45, 0.7] } },
      { id: "values-areas-line", type: "line", source: "values", "source-layer": "value_areas", filter: byClass("RR"), minzoom: 13,
        paint: { "line-color": "#fcfcfb", "line-width": 1 } },
      { id: "roads", type: "line", source: "base", "source-layer": "roads",
        paint: {
          "line-color": ["match", ["get", "class"], ["motorway", "trunk", "primary"], "#e7d9c6", "#ffffff"],
          "line-width": ["interpolate", ["linear"], ["zoom"], 10, ["match", ["get", "class"], ["motorway", "trunk", "primary"], 1.2, 0.3], 16, 5],
        } },
      { id: "barangays", type: "line", source: "base", "source-layer": "barangays", minzoom: 12,
        paint: { "line-color": "#8a8f98", "line-width": 0.5, "line-dasharray": [2, 2] } },
      { id: "cities", type: "line", source: "base", "source-layer": "cities", paint: { "line-color": "#4b5563", "line-width": 1.4 } },
      // valued street segments: dark casing so the light bands stay visible, then the value colour
      { id: "values-streets-casing", type: "line", source: "values", "source-layer": "value_streets", filter: byClass("RR"),
        layout: { "line-cap": "round" },
        paint: { "line-color": "#1f2937", "line-opacity": 0.55, "line-width": ["interpolate", ["linear"], ["zoom"], 11, 2.5, 16, 7] } },
      { id: "values-streets", type: "line", source: "values", "source-layer": "value_streets", filter: byClass("RR"),
        layout: { "line-cap": "round" },
        paint: { "line-color": valueColor, "line-width": ["interpolate", ["linear"], ["zoom"], 11, 1.5, 16, 5] } },
      // a street with two different values for one classification: never resolved, marked for review
      { id: "values-conflicts", type: "line", source: "values", "source-layer": "value_streets", minzoom: 13,
        filter: ["all", byClass("RR"), ["!=", ["get", "conflict_with"], ""]],
        paint: { "line-color": "#7e22ce", "line-width": 1.5, "line-dasharray": [1, 1.5], "line-offset": 5 } },
      // wide invisible line: a tap target bigger than the mark
      { id: "values-streets-hit", type: "line", source: "values", "source-layer": "value_streets", filter: byClass("RR"),
        paint: { "line-color": "#000", "line-opacity": 0, "line-width": 14 } },
    ],
  },
});
map.addControl(new maplibregl.NavigationControl());
map.addControl(new maplibregl.ScaleControl());
map.addControl(new maplibregl.AttributionControl({
  compact: true,
  customAttribution: '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors · Boundaries: OCHA COD-AB · Values: BIR',
}));
const VALUE_LAYERS = ["values-areas", "values-areas-line", "values-streets-casing", "values-streets", "values-conflicts", "values-streets-hit"];

function esc(v: unknown) {
  return String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]!);
}
const php = (n: number) => "₱" + Math.round(n).toLocaleString("en-PH");
const fmtDate = (d: string) => (/^\d{4}-\d{2}-\d{2}$/.test(d) ? new Date(d + "T00:00:00").toLocaleDateString("en-PH", { day: "numeric", month: "short", year: "numeric" }) : d);

type Schedule = { city: string; name: string; department_order: string; revision: string; effective_date: string; url: string; listed_on: string };
type City = { name: string; bounds: [number, number, number, number]; built: boolean; valuation_base?: string };
type Entry = { n: string; k: "city" | "barangay" | "street"; c: [number, number]; city?: string; brgy?: string; b?: [number, number, number, number] };
type Meta = { cities: Record<string, City>; schedules: Record<string, Schedule>;
  by_rdo: { rdo: string; city: string; in_scope: number; placed: number; match_rate: number }[]; conflicts: number;
  unmatched: Record<string, [string, string][]>; search: Entry[] };
let meta: Meta | null = null;

// --- popups: a valued street wins over the area under it ---
function valuePopup(p: any) {
  const s = meta?.schedules[p.rdo];
  const where = p.applies_to === "street" ? `Street segment in ${esc(p.barangay)}`
    : p.applies_to === "interior" ? `Barangay ${esc(p.barangay)}: all other streets` : `Area in ${esc(p.barangay)}`;
  const rdo = s ? `RDO ${esc(p.rdo)} ${esc(s.name)}` : `RDO ${esc(p.rdo)}`;
  const link = s ? ` · <a href="${esc(s.url)}" target="_blank" rel="noopener">schedule</a>` : "";
  return `<b style="font-size:15px">${php(Number(p.value_php_sqm))}/m²</b> · ${esc(CLASS_NAME[p.class_code] ?? p.class_code)} (${esc(p.class_code)})<br>` +
    `${where}, ${esc(p.city)}<br><span class="muted">Schedule row:</span> ${esc(p.description)}<br>` +
    `BIR zonal value · ${rdo} · DO ${esc(p.department_order)}, effective ${esc(fmtDate(p.effective_date))}${link}` +
    (p.conflict_with ? `<br><span class="warn">&#9888; Another schedule row gives this street a different ${esc(p.class_code)} value (${esc(p.conflict_with)}). Not resolved; under review.</span>` : "") +
    (p.notes ? `<br><small class="muted">Review note: ${esc(p.notes)}</small>` : "") +
    `<br><small><b>${VALUES_NOTE}.</b></small>`;
}
const CLICKABLE = ["values-streets-hit", "values-areas"];
map.on("click", (e) => {
  const f = map.queryRenderedFeatures(e.point, { layers: CLICKABLE })
    .sort((a, b) => CLICKABLE.indexOf(a.layer.id) - CLICKABLE.indexOf(b.layer.id))[0];
  if (!f) return;
  new maplibregl.Popup({ maxWidth: "300px" }).setLngLat(e.lngLat).setHTML(valuePopup(f.properties)).addTo(map);
});
for (const id of CLICKABLE) {
  map.on("mouseenter", id, () => (map.getCanvas().style.cursor = "pointer"));
  map.on("mouseleave", id, () => (map.getCanvas().style.cursor = ""));
}

// --- classification filter and legend ---
const select = document.getElementById("vclass") as HTMLSelectElement;
select.innerHTML = CLASSES.map(([c, n]) => `<option value="${c}">${n} (${c})</option>`).join("");
select.onchange = () => {
  const f = byClass(select.value);
  for (const id of VALUE_LAYERS) map.setFilter(id, id === "values-conflicts" ? ["all", f, ["!=", ["get", "conflict_with"], ""]] : f);
};
document.getElementById("vlegend")!.innerHTML = `<div class="vnote">${VALUES_NOTE}</div><div class="vunit">PHP per m²</div>` +
  BANDS.map(([, c, n]) => `<div><i style="background:${c}"></i>${n}</div>`).join("") +
  `<div><i class="vconf"></i>Two values, under review</div>`;

// --- city picker and search (cities, barangays, valued streets) ---
const picker = document.getElementById("cities")!;
const input = document.getElementById("q") as HTMLInputElement;
const results = document.getElementById("results")!;
const norm = (s: string) => s.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase().replace(/\./g, "").replace(/\s+/g, " ");
// "Brgy 649", "bgy. 649" and "649" find Manila's "Barangay 649"
const query = (s: string) => norm(s).replace(/^(brgy|bgy|barangay) ?/, "barangay ").trim();
const KIND = { city: 0, barangay: 1, street: 2 };
function go(e: Entry) {
  if (e.b) map.fitBounds([[e.b[0], e.b[1]], [e.b[2], e.b[3]]], { padding: 30 });
  else map.flyTo({ center: e.c, zoom: e.k === "street" ? 16 : 15 });
  results.innerHTML = ""; input.value = e.n;
}
input.oninput = () => {
  const q = query(input.value);
  results.innerHTML = "";
  if (q.length < 2 || !meta) return;
  const num = /^\d+$/.test(q) ? `barangay ${q}` : null;
  const hits = meta.search.filter((e) => { const n = norm(e.n); return num ? n === num : n.includes(q); })
    .sort((a, b) => KIND[a.k] - KIND[b.k] || (norm(a.n).startsWith(q) ? 0 : 1) - (norm(b.n).startsWith(q) ? 0 : 1) || a.n.localeCompare(b.n))
    .slice(0, 10);
  for (const h of hits) {
    const b = document.createElement("button");
    const where = h.k === "street" ? `${h.brgy}, ${h.city}` : h.k === "barangay" ? `Barangay, ${h.city}` : "City";
    b.innerHTML = `${esc(h.n)} <span class="muted">${esc(where)}</span>`;
    b.onclick = () => go(h);
    results.append(b);
  }
};

// --- rows not on the map ---
const gaps = document.getElementById("vgaps") as HTMLDetailsElement;
fetch(tileUrl("values_meta.json")).then((r) => r.json()).then((m: Meta) => {
  meta = m;
  for (const c of Object.values(m.cities)) {
    const b = document.createElement("button");
    b.textContent = c.name + (c.built ? "" : " (coming)");
    b.onclick = () => map.fitBounds([[c.bounds[0], c.bounds[1]], [c.bounds[2], c.bounds[3]]], { padding: 20 });
    picker.append(b);
  }
  const rows = Object.values(m.unmatched).reduce((a, v) => a + v.length, 0);
  const placed = m.by_rdo.reduce((a, r) => a + r.placed, 0), inScope = m.by_rdo.reduce((a, r) => a + r.in_scope, 0);
  const sched = Object.entries(m.schedules).map(([rdo, s]) =>
    `<li>${esc(s.city)}, RDO ${esc(rdo)} ${esc(s.name)}: <a href="${esc(s.url)}" target="_blank" rel="noopener">DO ${esc(s.department_order)}</a>, ${esc(fmtDate(s.effective_date))}</li>`).join("");
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
