/* ORBIT — shared state, constants and small helpers */

export const S = {
  user: null,          // profile payload from the server
  config: {},          // /api/config: google_client_id, live_places
  countries: [],       // [{code, name, continent, iso2, feature}]
  byCode: {},
  byIso2: {},
  compare: null,       // {id, username, codes:Set}
  hover: null,
  hoverContinent: null,
  mode: "continent",   // continent | country | city | town (zoom level)
  cityGrid: null,      // lazily-loaded GeoNames places in 5° cells, so a zoomed-in
                       // view only scans the places near it
  searchMarker: null,
  destinations: [],
  plan: null,          // itinerary currently open in the planner
  lastPlan: null,      // {place, coords} — so the radius selector can re-run it
  planWith: null,      // friend to auto-invite when the next trip is saved
  trip: null,          // saved trip currently open in My trips
};

export const C = {
  page: "#0d0d0d",
  ocean: "#122741",     // deep navy sea — lifts the globe off the black page
  none: "#2b303b",      // unvisited land: graphite, clearly lighter than the sea
  noneHover: "#3a4150",
  you: "#3987e5",
  wish: "#c98500",
  friend: "#199e70",
  both: "#9085e9",
};
export const CAT_ORDER = ["Must-see", "Activity", "Food & drink", "Night out"];
export const CAT_DOT = { "Must-see": C.you, "Activity": C.friend, "Food & drink": C.wish, "Night out": C.both };
// Natural Earth leaves ISO_A2 as -99 for a few countries
export const ISO2_FIX = { FRA: "FR", NOR: "NO", CYN: "CY", SOL: "SO" };

export const $ = (id) => document.getElementById(id);

/* phones and tablets: no hover, fingers instead of a pointer */
export const isTouch = () => window.matchMedia("(hover: none)").matches;
export const isPhone = () => window.matchMedia("(max-width: 720px)").matches;

/* whoever renders the app registers here, so setUser can redraw everything */
export const hooks = { render: () => {} };

export function setUser(payload) {
  S.user = payload;
  hooks.render();
}

/* ── formatting ──────────────────────────────────────── */

export function esc(s) {
  return String(s).replace(/[&<>"']/g, (ch) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch]));
}

export function flag(iso2) {
  if (!iso2 || iso2.length !== 2 || /[^A-Z]/.test(iso2)) return "🌍";
  return String.fromCodePoint(...[...iso2].map((c) => 0x1f1e6 + c.charCodeAt(0) - 65));
}

let toastTimer;
export function toast(msg) {
  const el = $("toast");
  el.textContent = msg;
  el.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (el.hidden = true), 2800);
}

/* flight number -> airline context (common IATA prefixes, no API needed) */
const AIRLINES = {
  AA: "American", BA: "British Airways", DL: "Delta", UA: "United", AF: "Air France",
  KL: "KLM", LH: "Lufthansa", FR: "Ryanair", U2: "easyJet", W6: "Wizz Air",
  EK: "Emirates", QR: "Qatar Airways", EY: "Etihad", TK: "Turkish Airlines",
  AC: "Air Canada", WS: "WestJet", QF: "Qantas", NZ: "Air New Zealand",
  SQ: "Singapore Airlines", CX: "Cathay Pacific", JL: "JAL", NH: "ANA",
  KE: "Korean Air", AZ: "ITA Airways", IB: "Iberia", VY: "Vueling", TP: "TAP",
  LX: "SWISS", OS: "Austrian", SN: "Brussels Airlines", SK: "SAS", AY: "Finnair",
  EI: "Aer Lingus", VS: "Virgin Atlantic", WN: "Southwest", B6: "JetBlue",
  AS: "Alaska", F9: "Frontier", NK: "Spirit", AM: "Aeromexico", Y4: "Volaris",
  LA: "LATAM", AV: "Avianca", CM: "Copa", ET: "Ethiopian", MS: "EgyptAir",
  SV: "Saudia", AI: "Air India", "6E": "IndiGo", TG: "Thai Airways",
  VN: "Vietnam Airlines", GA: "Garuda", MH: "Malaysia Airlines", CI: "China Airlines",
  BR: "EVA Air", CA: "Air China", MU: "China Eastern", CZ: "China Southern",
  JQ: "Jetstar", VA: "Virgin Australia", PC: "Pegasus", A3: "Aegean",
  HV: "Transavia", DY: "Norwegian", LO: "LOT", JU: "Air Serbia", BT: "airBaltic",
};

export function flightInfo(fn) {
  const m = /^([A-Z][A-Z0-9]|[0-9][A-Z])\s*0*(\d{1,4})[A-Z]?$/.exec((fn || "").toUpperCase().trim());
  if (!m) return null;
  return {
    code: m[1] + m[2],
    airline: AIRLINES[m[1]] || null,
    trackUrl: "https://www.flightradar24.com/data/flights/" + (m[1] + m[2]).toLowerCase(),
  };
}

/* travel dates -> which weekdays (0=Sun) the stay covers */
const DAY_NAMES = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
export function stayDays(start, end) {
  if (!start || !end) return null;
  const s = new Date(start + "T12:00:00"), e = new Date(end + "T12:00:00");
  if (isNaN(s) || isNaN(e) || e < s) return null;
  const days = new Set();
  for (const d = new Date(s); d <= e && days.size < 7; d.setDate(d.getDate() + 1)) days.add(d.getDay());
  return days;
}

/* open_days bitmask (index 0 = Sunday) vs the stay -> closed info */
export function closedDuring(openDays, days) {
  if (!openDays || openDays.length !== 7 || !days) return null;
  const closed = [...days].filter((d) => openDays[d] === "0");
  if (!closed.length) return null;
  return { all: closed.length === days.size, names: closed.sort().map((d) => DAY_NAMES[d]) };
}

export function fmtDate(iso) {
  const d = new Date(iso + "T12:00:00");
  return isNaN(d) ? iso : d.toLocaleDateString(undefined, { weekday: "short", day: "numeric", month: "short" });
}

/* ── travel status ───────────────────────────────────── */

export function visitedSet() { return new Set((S.user?.visited || []).map((v) => v.code)); }
export function wishSet() { return new Set((S.user?.wishlist || []).map((w) => w.code).filter(Boolean)); }

/* city-level status keys: "name|ISO2", lowercased */
export const cityKey = (name, iso2) => `${(name || "").toLowerCase()}|${iso2 || ""}`;
function visitedCityKeys() {
  return new Set((S.user?.visited_cities || []).map((c) => cityKey(c.name, c.iso2)));
}
function wishCityKeys() {
  const keys = new Set();
  for (const w of S.user?.wishlist || []) {
    const iso2 = w.code ? S.byCode[w.code]?.iso2 : "";
    keys.add(cityKey(w.place.split(",")[0].trim(), iso2));
  }
  return keys;
}
export function cityStatus(city) {
  const key = cityKey(city.name, city.iso2);
  if (visitedCityKeys().has(key)) return "you";
  if (wishCityKeys().has(key)) return "wish";
  return "none";
}

export function countryStatus(code) {
  if (S.compare) {
    const mine = visitedSet().has(code);
    const theirs = S.compare.codes.has(code);
    if (mine && theirs) return "both";
    if (mine) return "you";
    if (theirs) return "friend";
    return "none";
  }
  if (visitedSet().has(code)) return "you";
  if (wishSet().has(code)) return "wish";
  return "none";
}

export function visitedContinents() {
  return new Set((S.user?.visited || []).map((v) => S.byCode[v.code]?.continent)
    .filter((c) => c && c !== "Seven seas (open ocean)"));
}

/* rough centroid of a country's largest ring (handles the antimeridian) */
export function centroid(feature) {
  const polys = feature.geometry.type === "Polygon"
    ? [feature.geometry.coordinates] : feature.geometry.coordinates;
  let ring = polys[0][0];
  for (const p of polys) if (p[0].length > ring.length) ring = p[0];
  let lngs = ring.map((pt) => pt[0]);
  const lats = ring.map((pt) => pt[1]);
  const span = Math.max(...lngs) - Math.min(...lngs);
  if (span > 180) lngs = lngs.map((l) => (l < 0 ? l + 360 : l));
  const lat = lats.reduce((a, b) => a + b, 0) / lats.length;
  let lng = lngs.reduce((a, b) => a + b, 0) / lngs.length;
  if (lng > 180) lng -= 360;
  return { lat, lng };
}

/* share an invite link: native share sheet on phones, clipboard elsewhere */
export async function shareInvite() {
  const code = S.user?.share_code;
  if (!code) return;
  const url = `${location.origin}/?add=${code}`;
  const text = `Add me on ORBIT and compare travel maps — my code is ${code}`;
  if (navigator.share) {
    try { await navigator.share({ title: "ORBIT", text, url }); return; }
    catch (e) { if (e.name === "AbortError") return; }
  }
  copyText(url, "Invite link copied — send it to a friend");
}

export async function copyText(text, message) {
  try {
    await navigator.clipboard.writeText(text);
    toast(message);
  } catch {
    toast(text);  // no clipboard access: at least show it
  }
}
