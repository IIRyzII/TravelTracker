/* ORBIT — globe-first travel tracker */
"use strict";

const S = {
  user: null,          // profile payload from the server
  countries: [],       // [{code, name, continent, iso2, feature}]
  byCode: {},
  byIso2: {},
  compare: null,       // {id, username, codes:Set}
  hover: null,
  hoverContinent: null,
  mode: "continent",   // continent | country | city | town (zoom level)
  cities: null,        // lazily-loaded GeoNames places
  searchMarker: null,
  destinations: [],
  plan: null,          // itinerary currently open in the planner
  lastPlan: null,      // {place, coords} — so the radius selector can re-run it
  planWith: null,      // friend to auto-invite when the next trip is saved
  trip: null,          // saved trip currently open in My trips
};

/* zoom altitude -> detail level */
function modeForAlt(alt) {
  if (alt >= 1.7) return "continent";
  if (alt >= 0.55) return "country";
  if (alt >= 0.22) return "city";
  return "town";
}
const LOD_FLY = { continent: 2.2, country: 1.1, city: 0.4, town: 0.15 };
const CONTINENT_VIEWS = {
  "Africa": { lat: 2, lng: 20 },
  "Europe": { lat: 52, lng: 14 },
  "Asia": { lat: 34, lng: 92 },
  "North America": { lat: 44, lng: -100 },
  "South America": { lat: -16, lng: -60 },
  "Oceania": { lat: -26, lng: 140 },
  "Antarctica": { lat: -78, lng: 20 },
};

const C = {
  page: "#0d0d0d",
  ocean: "#122741",     // deep navy sea — lifts the globe off the black page
  none: "#2b303b",      // unvisited land: graphite, clearly lighter than the sea
  noneHover: "#3a4150",
  you: "#3987e5",
  wish: "#c98500",
  friend: "#199e70",
  both: "#9085e9",
};
const CAT_ORDER = ["Must-see", "Activity", "Food & drink", "Night out"];
const CAT_DOT = { "Must-see": C.you, "Activity": C.friend, "Food & drink": C.wish, "Night out": C.both };
// Natural Earth leaves ISO_A2 as -99 for a few countries
const ISO2_FIX = { FRA: "FR", NOR: "NO", CYN: "CY", SOL: "SO" };

const $ = (id) => document.getElementById(id);
let world; // globe.gl instance

/* ── helpers ─────────────────────────────────────────── */

function flag(iso2) {
  if (!iso2 || iso2.length !== 2 || /[^A-Z]/.test(iso2)) return "🌍";
  return String.fromCodePoint(...[...iso2].map((c) => 0x1f1e6 + c.charCodeAt(0) - 65));
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

function flightInfo(fn) {
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
function stayDays(start, end) {
  if (!start || !end) return null;
  const s = new Date(start + "T12:00:00"), e = new Date(end + "T12:00:00");
  if (isNaN(s) || isNaN(e) || e < s) return null;
  const days = new Set();
  for (const d = new Date(s); d <= e && days.size < 7; d.setDate(d.getDate() + 1)) days.add(d.getDay());
  return days;
}

/* open_days bitmask (index 0 = Sunday) vs the stay -> closed info */
function closedDuring(openDays, days) {
  if (!openDays || openDays.length !== 7 || !days) return null;
  const closed = [...days].filter((d) => openDays[d] === "0");
  if (!closed.length) return null;
  return { all: closed.length === days.size, names: closed.sort().map((d) => DAY_NAMES[d]) };
}

function fmtDate(iso) {
  const d = new Date(iso + "T12:00:00");
  return isNaN(d) ? iso : d.toLocaleDateString(undefined, { weekday: "short", day: "numeric", month: "short" });
}

let toastTimer;
function toast(msg) {
  const el = $("toast");
  el.textContent = msg;
  el.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (el.hidden = true), 2600);
}

async function api(path, { method = "GET", body } = {}) {
  const opts = { method, headers: { "Content-Type": "application/json" } };
  let url = path;
  if (body) opts.body = JSON.stringify({ ...body, user_id: S.user ? S.user.id : undefined });
  if (!body && S.user) url += (url.includes("?") ? "&" : "?") + "user_id=" + S.user.id;
  const res = await fetch(url, opts);
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || "Something went wrong");
  return data;
}

function setUser(payload) {
  S.user = payload;
  localStorage.setItem("orbit_user", payload.id);
  renderAll();
}

function visitedSet() { return new Set((S.user?.visited || []).map((v) => v.code)); }
function wishSet() { return new Set((S.user?.wishlist || []).map((w) => w.code).filter(Boolean)); }

/* city-level status keys: "name|ISO2", lowercased */
const cityKey = (name, iso2) => `${(name || "").toLowerCase()}|${iso2 || ""}`;
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
function cityStatus(city) {
  const key = cityKey(city.name, city.iso2);
  if (visitedCityKeys().has(key)) return "you";
  if (wishCityKeys().has(key)) return "wish";
  return "none";
}

/* rough centroid of a country's largest ring (handles the antimeridian) */
function centroid(feature) {
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

/* ── globe ───────────────────────────────────────────── */

function countryStatus(code) {
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

const STATUS_LABEL = {
  you: "Visited", wish: "On your wishlist", friend: "", both: "", none: "Not visited yet",
};

function capColor(d) {
  const st = countryStatus(d.properties.ADM0_A3);
  return C[st === "none" ? "none" : st] || C.none;
}

function continentTally(cont) {
  const mine = visitedSet();
  let total = 0, visited = 0;
  for (const c of S.countries) {
    if (c.continent !== cont) continue;
    total++;
    if (mine.has(c.code)) visited++;
  }
  return { total, visited };
}

function refreshGlobe() {
  const contMode = S.mode === "continent";
  world
    .polygonCapColor((d) => {
      const st = countryStatus(d.properties.ADM0_A3);
      if (st !== "none") return C[st];
      return contMode && d.properties.CONTINENT === S.hoverContinent ? C.noneHover : C.none;
    })
    .polygonAltitude((d) => {
      const close = S.mode === "city" || S.mode === "town"; // flat up close: no cliff edges
      if (contMode) return d.properties.CONTINENT === S.hoverContinent ? 0.022 : 0.008;
      if (d === S.hover) return close ? 0.006 : 0.04;
      return countryStatus(d.properties.ADM0_A3) === "none"
        ? (close ? 0.002 : 0.006) : (close ? 0.004 : 0.015);
    })
    // hex only — the renderer ignores stroke alpha
    .polygonStrokeColor((d) => {
      if (contMode) {
        // match the cap colour so internal borders vanish at continent level
        return d.properties.CONTINENT === S.hoverContinent ? C.noneHover : C.none;
      }
      return d === S.hover ? "#ffffff" : "#4d525e";
    });
}

function initGlobe(features) {
  world = Globe()($("globe"))
    .backgroundColor("rgba(0,0,0,0)") // let the CSS glow behind the globe show
    .showAtmosphere(true)
    .atmosphereColor(C.you)
    .atmosphereAltitude(0.18)
    .polygonsData(features)
    .polygonSideColor(() => "rgba(0,0,0,0.45)")
    .polygonsTransitionDuration(200)
    .polygonLabel((d) => {
      if (S.mode === "continent") {
        const cont = d.properties.CONTINENT;
        const t = continentTally(cont);
        return `<div class="globe-tooltip">${cont}<br><small>${t.visited} of ${t.total} countries visited · click to explore</small></div>`;
      }
      const code = d.properties.ADM0_A3;
      const st = countryStatus(code);
      let sub = STATUS_LABEL[st];
      if (S.compare) {
        sub = { you: "Only you", friend: "Only " + S.compare.username, both: "You both", none: "Neither of you" }[st];
      }
      return `<div class="globe-tooltip">${flag(S.byCode[code]?.iso2)} ${d.properties.ADMIN}<br><small>${sub}</small></div>`;
    })
    .onPolygonHover((d) => {
      S.hover = d;
      S.hoverContinent = d ? d.properties.CONTINENT : null;
      $("globe").style.cursor = d ? "pointer" : "grab";
      refreshGlobe();
    })
    .onPolygonClick((d, ev) => {
      if (S.mode === "continent") {
        const view = CONTINENT_VIEWS[d.properties.CONTINENT] || centroid(d);
        goTo({ ...view, altitude: 1.1 });
        return;
      }
      openPop(d.properties.ADM0_A3, ev.clientX, ev.clientY);
    })
    .onGlobeClick(closePop)
    .labelsData([])
    .labelLat((d) => d.lat)
    .labelLng((d) => d.lng)
    .labelText((d) => d.name)
    .labelSize((d) => d.size)
    .labelDotRadius((d) => d.dot)
    .labelColor((d) => d.color)
    .labelAltitude((d) => d.alt || 0.002)  // must clear the polygon caps
    .labelResolution(2)
    .onLabelClick((d, ev) => {
      if (d.type === "continent") goTo({ lat: d.lat, lng: d.lng, altitude: 1.1 });
      else openCityPop(d, ev.clientX, ev.clientY);
    })
    .onLabelHover((d) => { $("globe").style.cursor = d ? "pointer" : "grab"; });

  world.globeMaterial().color.set(C.ocean);
  world.controls().autoRotate = true;
  world.controls().autoRotateSpeed = 0.45;
  world.controls().addEventListener("start", () => (world.controls().autoRotate = false));
  let lodTimer;
  world.controls().addEventListener("change", () => {
    clearTimeout(lodTimer);
    lodTimer = setTimeout(updateLOD, 120);
  });
  world.pointOfView({ lat: 24, lng: 10, altitude: 2.2 });
  refreshGlobe();
  updateLOD();

  window.addEventListener("resize", () =>
    world.width(window.innerWidth).height(window.innerHeight));
}

/* fly the camera and re-sync the detail level once the animation lands
   (programmatic moves don't fire the controls' change event) */
function goTo(view, ms = 900) {
  world.controls().autoRotate = false;
  world.pointOfView(view, ms);
  setTimeout(updateLOD, ms + 60);
}

function flyTo(code) {
  const c = S.byCode[code];
  if (!c) return;
  const { lat, lng } = centroid(c.feature);
  goTo({ lat, lng, altitude: 1.5 });
  setTimeout(() => openPop(code, window.innerWidth - 320, 160), 950);
}

/* ── level of detail: continents → countries → cities → towns ── */

let citiesLoading = false;
async function loadCities() {
  if (S.cities || citiesLoading) return;
  citiesLoading = true;
  try {
    const raw = await (await fetch("/static/data/cities.json")).json();
    // pre-sorted by population, descending
    S.cities = raw.map(([name, iso2, lat, lng, pop]) => ({ name, iso2, lat, lng, pop }));
    updateLOD();
  } catch {
    toast("Couldn't load the city layer");
  } finally {
    citiesLoading = false;
  }
}

function continentLabels() {
  return Object.entries(CONTINENT_VIEWS).map(([cont, v]) => ({
    type: "continent", name: cont, lat: v.lat, lng: v.lng,
    size: 1.7, dot: 0, alt: 0.012,         // above the polygon caps
    color: "#c9c7bb",                      // hex only — label colors ignore alpha
  }));
}

function placeMarkers() {
  if (!S.cities) { loadCities(); return []; }
  const pov = world.pointOfView();
  const town = S.mode === "town";
  const alt = Math.max(pov.altitude, 0.05);
  const radius = Math.min(alt * 55, 30);   // match what's actually on screen
  const cap = town ? 90 : 36;
  // spacing scales with zoom: the closer you get, the tighter labels can pack
  const sep = alt * (town ? 3.3 : 4.75);
  const cosLat = Math.max(Math.cos(pov.lat * Math.PI / 180), 0.05);
  const dist = (a1, o1, a2, o2) => {
    let dLng = Math.abs(o1 - o2);
    if (dLng > 180) dLng = 360 - dLng;
    return Math.hypot(a1 - a2, dLng * cosLat);
  };
  // no population floor — rank by population discounted by distance from the
  // view centre, so key cities surface but edge-of-screen giants can't starve
  // the local towns you're actually looking at
  const cand = [];
  for (const c of S.cities) {
    const d = dist(c.lat, c.lng, pov.lat, pov.lng);
    if (d > radius) continue;
    cand.push([Math.log10(c.pop + 1) - 2.2 * (d / radius), c]);
  }
  cand.sort((a, b) => b[0] - a[0]);
  const out = [];
  for (const [, c] of cand) {
    if (out.some((o) => dist(c.lat, c.lng, o.lat, o.lng) < sep)) continue;
    out.push(c);
    if (out.length >= cap) break;
  }
  // your visited cities always show, even tiny ones
  const seen = new Set(out.map((c) => cityKey(c.name, c.iso2)));
  for (const c of S.user?.visited_cities || []) {
    if (c.lat == null || seen.has(cityKey(c.name, c.iso2))) continue;
    if (dist(c.lat, c.lng, pov.lat, pov.lng) <= radius) {
      out.push({ ...c, pop: 0 });
      seen.add(cityKey(c.name, c.iso2));
    }
  }
  // label size lives in globe units — scale it with zoom so text stays readable
  return out.map((c) => {
    const st = cityStatus(c);
    return {
      ...c, type: "place", alt: 0.006,
      size: alt * (c.pop >= 1e6 ? 0.8 : c.pop >= 200000 ? 0.65 : c.pop >= 30000 ? 0.52 : 0.44),
      dot: alt * (st === "none" ? 0.3 : 0.42),
      color: st === "you" ? C.you : st === "wish" ? C.wish : "#e8e6dc",
    };
  });
}

function updateLOD() {
  if (!world) return;
  const mode = modeForAlt(world.pointOfView().altitude);
  if (mode !== S.mode) {
    S.mode = mode;
    S.hoverContinent = null;
    refreshGlobe();
    document.querySelectorAll("#lodPill button").forEach((b) =>
      b.classList.toggle("active", b.dataset.mode === mode));
  }
  let labels = [];
  if (mode === "continent") labels = continentLabels();
  else if (mode === "city" || mode === "town") labels = placeMarkers();
  if (S.searchMarker && mode !== "continent") labels = labels.concat(S.searchMarker);
  world.labelsData(labels);
}

/* ── country popover ─────────────────────────────────── */

function closePop() { $("countryPop").hidden = true; }

function openPop(code, x, y) {
  const c = S.byCode[code];
  if (!c) return;
  const pop = $("countryPop");
  const visited = visitedSet().has(code);
  const wishItem = (S.user?.wishlist || []).find((w) => w.code === code);

  $("popFlag").textContent = flag(c.iso2);
  $("popName").textContent = c.name;
  $("popMeta").textContent = c.continent +
    (visited ? " · visited" : wishItem ? " · on your wishlist" : "");

  const actions = [];
  if (!visited) {
    actions.push(`<button class="btn btn-primary" data-act="visit">✓&nbsp; Been there</button>`);
    actions.push(wishItem
      ? `<button class="btn btn-ghost" data-act="unwish">Remove from wishlist</button>`
      : `<button class="btn btn-wish" data-act="wish">☆&nbsp; Dream trip</button>`);
  } else {
    actions.push(`<button class="btn btn-ghost" data-act="unvisit">Remove from visited</button>`);
  }
  actions.push(`<button class="btn btn-ghost" data-act="zoomin">Explore its cities ⌕</button>`);
  actions.push(`<button class="btn btn-ghost" data-act="plan">Plan a trip here →</button>`);
  $("popActions").innerHTML = actions.join("");

  $("popActions").querySelectorAll("button").forEach((btn) =>
    btn.addEventListener("click", () => popAction(btn.dataset.act, c, wishItem)));

  pop.hidden = false;
  const rect = pop.getBoundingClientRect();
  pop.style.left = Math.min(Math.max(12, x + 14), window.innerWidth - rect.width - 12) + "px";
  pop.style.top = Math.min(Math.max(72, y - 20), window.innerHeight - rect.height - 12) + "px";
}

async function popAction(act, c, wishItem) {
  try {
    if (act === "visit") {
      setUser(await api("/api/visited", { method: "POST", body: { code: c.code } }));
      toast(`${flag(c.iso2)} ${c.name} added to your map`);
    } else if (act === "unvisit") {
      setUser(await api("/api/visited", { method: "DELETE", body: { code: c.code } }));
      toast(`${c.name} removed`);
    } else if (act === "wish") {
      setUser(await api("/api/wishlist", { method: "POST", body: { place: c.name, code: c.code } }));
      toast(`☆ ${c.name} added to your dream list`);
    } else if (act === "unwish" && wishItem) {
      setUser(await api(`/api/wishlist/${wishItem.id}`, { method: "DELETE", body: {} }));
      toast(`${c.name} removed from wishlist`);
    } else if (act === "zoomin") {
      closePop();
      const { lat, lng } = centroid(c.feature);
      goTo({ lat, lng, altitude: countryZoomAlt(c.feature) });
      return;
    } else if (act === "plan") {
      closePop();
      switchView("planner");
      planTrip(c.name);
      return;
    }
    closePop();
  } catch (e) { toast(e.message); }
}

/* an altitude that fits the country but still lands in city-marker range */
function countryZoomAlt(feature) {
  const polys = feature.geometry.type === "Polygon"
    ? [feature.geometry.coordinates] : feature.geometry.coordinates;
  let minLat = 90, maxLat = -90;
  for (const p of polys) for (const [, la] of p[0]) {
    if (la < minLat) minLat = la;
    if (la > maxLat) maxLat = la;
  }
  return Math.min(Math.max((maxLat - minLat) / 40, 0.28), 0.5);
}

/* ── stats & profile chip ────────────────────────────── */

function renderStats() {
  const total = S.countries.length;
  const visited = S.user?.visited || [];
  const conts = new Set(
    visited.map((v) => S.byCode[v.code]?.continent)
      .filter((x) => x && x !== "Seven seas (open ocean)")
  );
  $("statVisited").textContent = visited.length;
  $("statVisitedSub").textContent = `of ${total} countries`;
  $("meterVisited").style.width = (100 * visited.length / total) + "%";
  $("statPercent").textContent = (100 * visited.length / total).toFixed(1).replace(/\.0$/, "") + "%";
  $("statContinents").innerHTML = `${conts.size}<span class="stat-of"> / 7</span>`;
  $("statWishlist").textContent = (S.user?.wishlist || []).length;

  $("profileName").textContent = S.user?.username || "…";
  $("profileCode").textContent = S.user?.share_code || "";
  $("avatarLetter").textContent = (S.user?.username || "?")[0].toUpperCase();
  $("bigShareCode").textContent = S.user?.share_code || "——————";
}

/* ── logbook view ────────────────────────────────────── */

function renderLogbook() {
  const visited = S.user?.visited || [];
  const cities = S.user?.visited_cities || [];
  $("logEmpty").hidden = visited.length > 0 || cities.length > 0;

  const conts = new Set(visited.map((v) => S.byCode[v.code]?.continent)
    .filter((c) => c && c !== "Seven seas (open ocean)"));
  $("logSummary").innerHTML = `
    <span><b>${conts.size}</b> continent${conts.size === 1 ? "" : "s"}</span>
    <span><b>${visited.length}</b> ${visited.length === 1 ? "country" : "countries"}</span>
    <span><b>${cities.length}</b> ${cities.length === 1 ? "city or town" : "cities & towns"}</span>`;

  const byCont = {};
  for (const v of visited) {
    const cont = S.byCode[v.code]?.continent || "Elsewhere";
    (byCont[cont] = byCont[cont] || []).push(v);
  }
  const cityByIso = {};
  for (const c of cities) (cityByIso[c.iso2] = cityByIso[c.iso2] || []).push(c);

  const cityChips = (list) => list.map((c) =>
    `<span class="city-chip" data-city="${esc(c.name)}" data-iso2="${esc(c.iso2)}"
        data-lat="${c.lat}" data-lng="${c.lng}">${esc(c.name)}
      <button class="kick" data-uncity aria-label="Remove ${esc(c.name)}">✕</button></span>`).join("");

  let html = Object.entries(byCont)
    .sort((a, b) => b[1].length - a[1].length)
    .map(([cont, list]) => {
      const total = S.countries.filter((c) => c.continent === cont).length;
      return `<section class="log-cont">
        <div class="log-cont-head">${esc(cont)}
          <span class="log-count">${list.length} of ${total} countries</span></div>
        ${list.sort((a, b) => a.name.localeCompare(b.name)).map((v) => {
          const iso2 = S.byCode[v.code]?.iso2;
          const cs = cityByIso[iso2] || [];
          return `<div class="log-country">
            <div class="log-country-row">
              <span class="log-flag">${flag(iso2)}</span>
              <span class="log-name" data-fly="${v.code}" title="Fly there">${esc(v.name)}</span>
              <span class="row-actions">
                <button class="btn btn-danger btn-sm" data-uncountry="${v.code}" aria-label="Remove ${esc(v.name)}">✕</button>
              </span>
            </div>
            ${cs.length ? `<div class="log-cities">${cityChips(cs)}</div>` : ""}
          </div>`;
        }).join("")}
      </section>`;
    }).join("");

  // cities whose country isn't on the map data (rare) still deserve a home
  const shownIso = new Set(visited.map((v) => S.byCode[v.code]?.iso2));
  const orphans = cities.filter((c) => !shownIso.has(c.iso2));
  if (orphans.length) {
    html += `<section class="log-cont">
      <div class="log-cont-head">Other places</div>
      <div class="log-country"><div class="log-cities">${cityChips(orphans)}</div></div>
    </section>`;
  }
  $("logSections").innerHTML = html;

  document.querySelectorAll("#logSections [data-fly]").forEach((el) =>
    el.addEventListener("click", () => { switchView("globe"); flyTo(el.dataset.fly); }));
  document.querySelectorAll("#logSections [data-uncountry]").forEach((btn) =>
    btn.addEventListener("click", async () => {
      try {
        setUser(await api("/api/visited", { method: "DELETE", body: { code: btn.dataset.uncountry } }));
        toast("Removed from your log");
      } catch (e) { toast(e.message); }
    }));
  document.querySelectorAll("#logSections .city-chip").forEach((chip) => {
    chip.addEventListener("click", (e) => {
      if (e.target.closest("[data-uncity]")) return;
      switchView("globe");
      flyToCity({
        name: chip.dataset.city, iso2: chip.dataset.iso2,
        lat: +chip.dataset.lat, lng: +chip.dataset.lng,
      });
    });
    chip.querySelector("[data-uncity]").addEventListener("click", async () => {
      try {
        setUser(await api("/api/visited_city", {
          method: "DELETE", body: { name: chip.dataset.city, iso2: chip.dataset.iso2 },
        }));
        toast("Removed from your log");
      } catch (e) { toast(e.message); }
    });
  });
}

/* ── wishlist view ───────────────────────────────────── */

function renderWishlist() {
  const list = $("wishList");
  const items = S.user?.wishlist || [];
  $("wishEmpty").hidden = items.length > 0;
  list.innerHTML = items.map((w) => {
    const iso2 = w.code ? S.byCode[w.code]?.iso2 : null;
    return `<li class="wish-item" data-id="${w.id}">
      <span class="wish-flag">${flag(iso2)}</span>
      <span><span class="wish-place">${esc(w.place)}</span>
        ${w.country && w.country !== w.place ? `<span class="wish-country"> · ${esc(w.country)}</span>` : ""}
      </span>
      <span class="row-actions">
        <button class="btn btn-ghost btn-sm" data-act="plan">Plan trip</button>
        ${w.code ? `<button class="btn btn-sm btn-primary" data-act="visited">✓ Been now</button>` : ""}
        <button class="btn btn-danger btn-sm" data-act="del" aria-label="Remove">✕</button>
      </span>
    </li>`;
  }).join("");

  list.querySelectorAll("button").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const li = btn.closest(".wish-item");
      const item = items.find((w) => w.id === +li.dataset.id);
      try {
        if (btn.dataset.act === "plan") { switchView("planner"); planTrip(item.place); }
        else if (btn.dataset.act === "del") {
          setUser(await api(`/api/wishlist/${item.id}`, { method: "DELETE", body: {} }));
          toast("Removed from your dream list");
        } else if (btn.dataset.act === "visited") {
          await api("/api/visited", { method: "POST", body: { code: item.code } });
          setUser(await api(`/api/wishlist/${item.id}`, { method: "DELETE", body: {} }));
          toast(`✓ ${item.place} — dream achieved!`);
        }
      } catch (e) { toast(e.message); }
    });
  });
}

function esc(s) {
  return String(s).replace(/[&<>"']/g, (ch) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch]));
}

/* ── friends view ────────────────────────────────────── */

function renderFriends() {
  const list = $("friendList");
  const friends = S.user?.friends || [];
  $("friendEmpty").hidden = friends.length > 0;
  list.innerHTML = friends.map((f) => `
    <li class="friend-item" data-id="${f.id}">
      <span class="avatar friend-avatar">${esc(f.username[0].toUpperCase())}</span>
      <span class="wish-place">${esc(f.username)}</span>
      <span class="friend-stats">
        <span class="friend-stat"><b>${f.visited_count}</b><span>countries</span></span>
        <span class="friend-stat"><b>${f.overlap}</b><span>in common</span></span>
      </span>
      <button class="btn btn-ghost btn-sm" data-act="plan">Plan together</button>
      <button class="btn btn-primary btn-sm" data-act="compare">Compare on globe</button>
      <button class="btn btn-danger btn-sm" data-act="remove" aria-label="Remove friend">✕</button>
    </li>`).join("");

  list.querySelectorAll("button").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const id = +btn.closest(".friend-item").dataset.id;
      const f = friends.find((x) => x.id === id);
      try {
        if (btn.dataset.act === "compare") startCompare(f);
        else if (btn.dataset.act === "plan") {
          S.planWith = { id: f.id, username: f.username };
          updatePlanWithNote();
          switchView("planner");
          $("planInput").focus();
          toast(`Planning with ${f.username} — pick a destination`);
        } else {
          setUser(await api(`/api/friends/${id}`, { method: "DELETE", body: {} }));
          toast(`${f.username} removed`);
        }
      } catch (e) { toast(e.message); }
    });
  });
}

function updatePlanWithNote() {
  const note = $("planWithNote");
  note.hidden = !S.planWith;
  if (S.planWith) {
    $("planWithText").innerHTML =
      `Planning with <b>${esc(S.planWith.username)}</b> — they'll be added to the trip when you save it.`;
  }
}

async function startCompare(f) {
  try {
    const data = await api(`/api/compare/${f.id}`);
    S.compare = { id: data.id, username: data.username, codes: new Set(data.visited.map((v) => v.code)) };
    const mine = visitedSet();
    let both = 0;
    for (const code of S.compare.codes) if (mine.has(code)) both++;
    $("compareName").textContent = data.username;
    $("cmpYou").textContent = mine.size - both;
    $("cmpBoth").textContent = both;
    $("cmpThem").textContent = S.compare.codes.size - both;
    $("compareBanner").hidden = false;
    $("globeLegend").hidden = true;
    switchView("globe");
    refreshGlobe();
    toast(`Overlaying ${data.username}'s map on yours`);
  } catch (e) { toast(e.message); }
}

function exitCompare() {
  S.compare = null;
  $("compareBanner").hidden = true;
  $("globeLegend").hidden = false;
  refreshGlobe();
}

/* ── planner view ────────────────────────────────────── */

function renderPlannerChips() {
  const wishes = S.user?.wishlist || [];
  $("wishChips").innerHTML = wishes.length
    ? `<span class="chip-row-label">From your wishlist</span>` +
      wishes.map((w) => `<button class="chip chip-wish" data-place="${esc(w.place)}">☆ ${esc(w.place)}</button>`).join("")
    : "";
  $("destChips").innerHTML =
    `<span class="chip-row-label">Popular shortlists</span>` +
    S.destinations.map((d) => `<button class="chip" data-place="${esc(d.destination)}">${esc(d.destination)}</button>`).join("");
  document.querySelectorAll("#wishChips .chip, #destChips .chip").forEach((chip) =>
    chip.addEventListener("click", () => planTrip(chip.dataset.place)));
}

async function planTrip(place, coords) {
  $("planInput").value = place;
  S.lastPlan = { place, coords };
  const params = new URLSearchParams({ place, radius_km: $("planRadius").value });
  if (coords) {
    params.set("lat", coords.lat);
    params.set("lng", coords.lng);
  }
  try {
    const plan = await api("/api/itinerary?" + params.toString());
    plan.items.forEach((i) => (i.selected = true));
    S.plan = plan;
    renderItinerary();
    $("itinerary").scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (e) { toast(e.message); }
}

function ratingHtml(i) {
  if (!i.rating) return "";
  const count = i.rating_count
    ? ` · ${Number(i.rating_count).toLocaleString()} reviews` : "";
  return `<div class="itin-rating"><span class="star">★</span> ${Number(i.rating).toFixed(1)}${count}</div>`;
}

function itemCard(i, opts) {
  const boxAttrs = opts.done
    ? `class="done-box" ${i.done ? "checked" : ""} aria-label="Mark ${esc(i.title)} done"`
    : `${i.selected ? "checked" : ""} aria-label="Include ${esc(i.title)}"`;
  const closed = closedDuring(i.open_days, opts.days);
  const closedChip = closed
    ? `<span class="closed-chip${closed.all ? " closed-all" : ""}">${
        closed.all ? "Closed during your stay" : "Closed " + closed.names.join(" · ")}</span>`
    : "";
  return `<div class="itin-item ${opts.done && i.done ? "done" : ""} ${!opts.done && !i.selected ? "deselected" : ""}"
        data-id="${opts.id}">
    <input type="checkbox" ${boxAttrs}>
    <div class="itin-body">
      <b>${esc(i.title)}</b>
      ${ratingHtml(i)}
      ${i.desc ? `<span class="itin-desc">${esc(i.desc)}</span>` : ""}
      ${closedChip}
    </div>
    ${opts.votes ? `<button class="vote-btn${i.my_vote ? " voted" : ""}" data-act="vote"
        title="Vote for this">♥ ${i.votes || 0}</button>` : ""}
    ${i.maps_url ? `<a class="maps-link" href="${esc(i.maps_url)}" target="_blank" rel="noopener">Maps ↗</a>` : ""}
    ${opts.canRemove ? `<button class="btn btn-danger btn-sm" data-act="del" aria-label="Remove">✕</button>` : ""}
  </div>`;
}

function sectionsHtml(items, opts) {
  return CAT_ORDER.map((cat) => {
    const catItems = items.filter((i) => i.category === cat);
    if (!catItems.length) return "";
    return `<section class="itin-section">
      <div class="itin-cat"><i class="dot" style="background:${CAT_DOT[cat]}"></i>${cat}</div>
      <div class="itin-items">${catItems.map((i) => itemCard(i, { ...opts, id: i._id })).join("")}</div>
    </section>`;
  }).join("");
}

function renderItinerary() {
  const plan = S.plan;
  plan.items.forEach((i, idx) => (i._id = idx));
  $("itinerary").hidden = false;
  $("itinTitle").textContent = plan.destination;
  $("itinTagline").textContent = plan.tagline;
  const badge = $("itinBadge");
  badge.textContent = plan.live ? "Live · Google Maps" : plan.curated ? "Curated" : "Starter list";
  badge.classList.toggle("curated", !!(plan.live || plan.curated));

  // travel dates: hide places shut for the whole stay, flag partly-closed ones
  const days = stayDays($("planStart").value, $("planEnd").value);
  let visible = plan.items;
  let hiddenCount = 0;
  if (days) {
    visible = plan.items.filter((i) => {
      const closed = closedDuring(i.open_days, days);
      if (closed && closed.all) { i.selected = false; hiddenCount++; return false; }
      return true;
    });
  }
  $("dateNote").textContent = hiddenCount
    ? `${hiddenCount} place${hiddenCount === 1 ? "" : "s"} hidden — closed for your whole stay` : "";
  $("itinSections").innerHTML = sectionsHtml(visible, { done: false, days });
  $("itinSections").querySelectorAll(".itin-item input").forEach((box) =>
    box.addEventListener("change", () => {
      const card = box.closest(".itin-item");
      S.plan.items[+card.dataset.id].selected = box.checked;
      card.classList.toggle("deselected", !box.checked);
      updateSaveBar();
    }));
  updateSaveBar();
}

function updateSaveBar() {
  const n = S.plan ? S.plan.items.filter((i) => i.selected).length : 0;
  $("saveCount").textContent = `${n} pick${n === 1 ? "" : "s"} selected`;
  $("saveTrip").disabled = n === 0;
}

/* ── my trips view ───────────────────────────────────── */

function renderTrips() {
  const trips = S.user?.trips || [];
  $("tripEmpty").hidden = trips.length > 0;
  $("tripList").innerHTML = trips.map((t) => {
    const pct = t.item_count ? Math.round(100 * t.done_count / t.item_count) : 0;
    const when = t.start_date && t.end_date
      ? `${fmtDate(t.start_date)} → ${fmtDate(t.end_date)}`
      : `saved ${esc((t.created_at || "").split(" ")[0])}`;
    const flight = flightInfo(t.flight_number);
    const crew = t.is_owner
      ? (t.members.length ? ` · with ${t.members.map(esc).join(", ")}` : "")
      : ` · by ${esc(t.owner)}`;
    return `
    <li class="trip-item" data-id="${t.id}">
      <span class="trip-icon">✈</span>
      <span class="trip-meta">
        <span class="trip-dest">${esc(t.destination)}</span>
        <span class="trip-sub">${t.done_count} of ${t.item_count} done · ${when}${
          flight ? ` · ${esc(flight.airline || "")} ${esc(flight.code)}` : ""}${crew}</span>
        <span class="meter trip-list-meter"><span class="meter-fill meter-fill-wish" style="width:${pct}%"></span></span>
      </span>
      <span class="row-actions">
        <button class="btn btn-ghost btn-sm" data-act="open">Open</button>
        <button class="btn btn-danger btn-sm" data-act="del" aria-label="Delete trip">✕</button>
      </span>
    </li>`;
  }).join("");

  $("tripList").querySelectorAll(".trip-item").forEach((li) => {
    const id = +li.dataset.id;
    li.addEventListener("click", (e) => {
      if (e.target.closest('[data-act="del"]')) return;
      openTrip(id);
    });
    li.querySelector('[data-act="del"]').addEventListener("click", async () => {
      const t = trips.find((x) => x.id === id);
      try {
        if (t && !t.is_owner) {
          setUser(await api(`/api/trips/${id}/members/${S.user.id}`, { method: "DELETE", body: {} }));
          toast("You left the trip");
        } else {
          setUser(await api(`/api/trips/${id}`, { method: "DELETE", body: {} }));
          toast("Trip deleted");
        }
      } catch (e) { toast(e.message); }
    });
  });
}

async function openTrip(id) {
  try {
    S.trip = await api(`/api/trips/${id}`);
    switchView("trips");
    renderTripDetail();
  } catch (e) { toast(e.message); }
}

function closeTripDetail() {
  S.trip = null;
  $("tripDetail").hidden = true;
  $("tripListWrap").hidden = false;
}

async function refreshUserQuiet() {
  try { S.user = await api("/api/state"); renderAll(); } catch { /* keep stale */ }
}

function renderTripDetail() {
  const trip = S.trip;
  if (!trip) return;
  $("tripListWrap").hidden = true;
  $("tripDetail").hidden = false;
  $("tripTitle").textContent = trip.destination;
  $("tripTagline").textContent = trip.tagline || "";
  const items = trip.items.map((i) => ({ ...i, desc: i.detail, _id: i.id }));
  const done = items.filter((i) => i.done).length;
  $("tripProgress").textContent = `${done} of ${items.length} done`;
  $("tripMeter").style.width = items.length ? (100 * done / items.length) + "%" : "0";

  // travel details
  $("tripFlight").value = trip.flight_number || "";
  $("tripStart").value = trip.start_date || "";
  $("tripEnd").value = trip.end_date || "";
  const flight = flightInfo(trip.flight_number);
  const bits = [];
  if (flight) {
    bits.push(`<span class="flight-strong">✈ ${esc(flight.airline || "Flight")} ${esc(flight.code)}</span>
      <a href="${esc(flight.trackUrl)}" target="_blank" rel="noopener">Track flight ↗</a>`);
  } else if (trip.flight_number) {
    bits.push(`<span class="flight-strong">✈ ${esc(trip.flight_number)}</span>`);
  }
  if (trip.start_date && trip.end_date) {
    bits.push(`${fmtDate(trip.start_date)} → ${fmtDate(trip.end_date)}`);
  }
  $("travelSummary").innerHTML = bits.length
    ? bits.join(" &nbsp;·&nbsp; ")
    : "Add your flight and dates — anything closed while you're there gets flagged.";

  $("travelForm").style.display = trip.is_owner ? "" : "none";
  renderCrew(trip);

  // the crew's favourites float to the top of each category
  items.sort((a, b) => (b.votes || 0) - (a.votes || 0));
  const days = stayDays(trip.start_date, trip.end_date);
  const hasCrew = trip.members.length > 0;
  $("tripSections").innerHTML = sectionsHtml(items, {
    done: true, days, votes: hasCrew, canRemove: trip.is_owner,
  });

  $("tripSections").querySelectorAll(".itin-item").forEach((card) => {
    const itemId = +card.dataset.id;
    card.querySelector("input").addEventListener("change", async () => {
      try {
        S.trip = await api(`/api/trips/${trip.id}/items/${itemId}/toggle`, { method: "POST", body: {} });
        renderTripDetail();
        refreshUserQuiet();
      } catch (e) { toast(e.message); }
    });
    const vote = card.querySelector('[data-act="vote"]');
    if (vote) vote.addEventListener("click", async () => {
      try {
        S.trip = await api(`/api/trips/${trip.id}/items/${itemId}/vote`, { method: "POST", body: {} });
        renderTripDetail();
      } catch (e) { toast(e.message); }
    });
    const del = card.querySelector('[data-act="del"]');
    if (del) del.addEventListener("click", async () => {
      try {
        S.trip = await api(`/api/trips/${trip.id}/items/${itemId}`, { method: "DELETE", body: {} });
        renderTripDetail();
        refreshUserQuiet();
        toast("Removed from this trip");
      } catch (e) { toast(e.message); }
    });
  });
}

function renderCrew(trip) {
  const crew = $("tripCrew");
  const chips = [];
  const avatar = (name, cls) =>
    `<i class="avatar ${cls}">${esc(name[0].toUpperCase())}</i>`;
  chips.push(`<span class="crew-chip">${avatar(trip.owner.username, "")}
    ${esc(trip.owner.username)}${trip.owner.id === S.user.id ? " (you)" : ""}</span>`);
  for (const m of trip.members) {
    const kick = trip.is_owner
      ? `<button class="kick" data-kick="${m.id}" title="Remove ${esc(m.username)}">✕</button>` : "";
    chips.push(`<span class="crew-chip">${avatar(m.username, "member")}
      ${esc(m.username)}${m.id === S.user.id ? " (you)" : ""}${kick}</span>`);
  }
  if (trip.is_owner) {
    const candidates = (S.user?.friends || []).filter(
      (f) => !trip.members.some((m) => m.id === f.id));
    if (candidates.length) {
      chips.push(`<span class="crew-invite">
        <select id="inviteSelect">${candidates.map(
          (f) => `<option value="${f.id}">${esc(f.username)}</option>`).join("")}</select>
        <button class="btn btn-ghost btn-sm" id="inviteBtn">+ Invite</button>
      </span>`);
    }
  } else {
    chips.push(`<button class="btn btn-ghost btn-sm" id="leaveTrip">Leave trip</button>`);
  }
  crew.innerHTML = chips.join("");

  const inviteBtn = $("inviteBtn");
  if (inviteBtn) inviteBtn.addEventListener("click", async () => {
    try {
      S.trip = await api(`/api/trips/${trip.id}/members`, {
        method: "POST", body: { friend_id: +$("inviteSelect").value },
      });
      renderTripDetail();
      refreshUserQuiet();
      toast("Invited — the trip now shows up in their My trips");
    } catch (e) { toast(e.message); }
  });
  crew.querySelectorAll("[data-kick]").forEach((btn) =>
    btn.addEventListener("click", async () => {
      try {
        S.trip = await api(`/api/trips/${trip.id}/members/${btn.dataset.kick}`, { method: "DELETE", body: {} });
        renderTripDetail();
        toast("Removed from the trip");
      } catch (e) { toast(e.message); }
    }));
  const leave = $("leaveTrip");
  if (leave) leave.addEventListener("click", async () => {
    try {
      setUser(await api(`/api/trips/${trip.id}/members/${S.user.id}`, { method: "DELETE", body: {} }));
      closeTripDetail();
      toast("You left the trip");
    } catch (e) { toast(e.message); }
  });
}

/* ── country + city search ───────────────────────────── */

function flyToCity(city) {
  world.controls().autoRotate = false;
  S.searchMarker = { ...city, type: "search", size: 0.34, dot: 0.13, alt: 0.008, color: "#ffffff" };
  world.pointOfView({ lat: city.lat, lng: city.lng, altitude: 0.4 }, 900);
  setTimeout(() => { updateLOD(); openCityPop(city); }, 950);
}

function openCityPop(city, x, y) {
  const pop = $("countryPop");
  const countryEntry = S.byIso2[city.iso2];
  const countryName = city.country || (countryEntry ? countryEntry.name : "");
  const placeLabel = city.name + (countryName ? ", " + countryName : "");
  const status = cityStatus(city);
  const wishItem = (S.user?.wishlist || []).find(
    (w) => w.place.split(",")[0].trim().toLowerCase() === city.name.toLowerCase());

  $("popFlag").textContent = flag(city.iso2);
  $("popName").textContent = city.name;
  $("popMeta").textContent =
    ([city.admin, countryName].filter(Boolean).join(", ") ||
      (city.pop ? city.pop.toLocaleString() + " people" : "")) +
    (status === "you" ? " · visited" : status === "wish" ? " · on your wishlist" : "");

  const actions = [];
  if (status === "you") {
    actions.push(`<button class="btn btn-ghost" data-act="uncity">Remove from visited</button>`);
  } else {
    actions.push(`<button class="btn btn-primary" data-act="citydone">✓&nbsp; Been there</button>`);
    actions.push(wishItem
      ? `<button class="btn btn-ghost" data-act="unwish">Remove from wishlist</button>`
      : `<button class="btn btn-wish" data-act="wish">☆&nbsp; Dream trip</button>`);
  }
  actions.push(`<button class="btn btn-ghost" data-act="plan">Plan a trip here →</button>`);
  $("popActions").innerHTML = actions.join("");

  $("popActions").querySelectorAll("button").forEach((btn) =>
    btn.addEventListener("click", async () => {
      try {
        if (btn.dataset.act === "citydone") {
          setUser(await api("/api/visited_city", {
            method: "POST",
            body: { name: city.name, iso2: city.iso2, lat: city.lat, lng: city.lng },
          }));
          toast(countryEntry
            ? `✓ ${city.name} logged — ${countryEntry.name} marked visited`
            : `✓ ${city.name} logged`);
        } else if (btn.dataset.act === "uncity") {
          setUser(await api("/api/visited_city", {
            method: "DELETE", body: { name: city.name, iso2: city.iso2 },
          }));
          toast(`${city.name} removed from your log`);
        } else if (btn.dataset.act === "wish") {
          setUser(await api("/api/wishlist", {
            method: "POST",
            body: { place: placeLabel, code: countryEntry ? countryEntry.code : undefined },
          }));
          toast(`☆ ${placeLabel} added to your dream list`);
        } else if (btn.dataset.act === "unwish" && wishItem) {
          setUser(await api(`/api/wishlist/${wishItem.id}`, { method: "DELETE", body: {} }));
          toast(`${city.name} removed from wishlist`);
        } else {
          closePop();
          switchView("planner");
          planTrip(placeLabel, { lat: city.lat, lng: city.lng });
          return;
        }
        S.searchMarker = null; // reveal the city's own status colour
        updateLOD();
        closePop();
      } catch (e) { toast(e.message); }
    }));

  pop.hidden = false;
  const px = x != null ? x + 14 : window.innerWidth - 320;
  const py = y != null ? y - 20 : 160;
  const rect = pop.getBoundingClientRect();
  pop.style.left = Math.min(Math.max(12, px), window.innerWidth - rect.width - 12) + "px";
  pop.style.top = Math.min(Math.max(72, py), window.innerHeight - rect.height - 12) + "px";
}

function initSearch() {
  const input = $("countrySearch");
  const box = $("searchResults");
  let cityTimer;
  let current = { countries: [], cities: [] };

  function renderBox() {
    const { countries, cities } = current;
    if (!countries.length && !cities.length) { box.hidden = true; return; }
    box.hidden = false;
    let html = "";
    if (countries.length) {
      html += `<li class="sr-group">Countries</li>` + countries.map((c) => {
        const st = countryStatus(c.code);
        const label = st === "you" ? "visited" : st === "wish" ? "wishlist" : "";
        return `<li data-kind="country" data-code="${c.code}">${flag(c.iso2)} ${esc(c.name)}<span class="sr-status">${label}</span></li>`;
      }).join("");
    }
    if (cities.length) {
      html += `<li class="sr-group">Cities</li>` + cities.map((c, i) => {
        const where = [c.admin, c.country].filter(Boolean).join(", ");
        const st = cityStatus(c);
        const label = st === "you" ? " · visited" : st === "wish" ? " · wishlist" : "";
        return `<li data-kind="city" data-i="${i}">${flag(c.iso2)} ${esc(c.name)}<span class="sr-status">${esc(where)}${label}</span></li>`;
      }).join("");
    }
    box.innerHTML = html;
    box.querySelectorAll("li[data-kind]").forEach((li) =>
      li.addEventListener("click", () => pick(li)));
  }

  function pick(li) {
    input.value = "";
    box.hidden = true;
    if (li.dataset.kind === "country") flyTo(li.dataset.code);
    else flyToCity(current.cities[+li.dataset.i]);
  }

  input.addEventListener("input", () => {
    const q = input.value.trim().toLowerCase();
    clearTimeout(cityTimer);
    if (!q) { current = { countries: [], cities: [] }; renderBox(); return; }
    current.countries = S.countries.filter((c) => c.name.toLowerCase().includes(q)).slice(0, 5);
    current.cities = [];
    renderBox();
    cityTimer = setTimeout(async () => {
      try {
        const cities = await api("/api/cities?q=" + encodeURIComponent(q));
        if (input.value.trim().toLowerCase() === q) {
          current.cities = cities;
          renderBox();
        }
      } catch { /* offline — country search still works */ }
    }, 250);
  });
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      e.preventDefault();
      const first = box.querySelector("li[data-kind]");
      if (first) pick(first);
    }
    if (e.key === "Escape") { input.value = ""; box.hidden = true; }
  });
}

/* ── views / tabs ────────────────────────────────────── */

function switchView(name) {
  document.querySelectorAll(".view").forEach((v) => v.classList.toggle("active", v.id === "view-" + name));
  document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("active", t.dataset.view === name));
  closePop();
}

function renderAll() {
  renderStats();
  renderLogbook();
  renderWishlist();
  renderFriends();
  renderPlannerChips();
  renderTrips();
  if (world) refreshGlobe();
}

/* ── boot ────────────────────────────────────────────── */

async function boot() {
  const geo = await (await fetch("/static/data/countries.geojson")).json();
  for (const f of geo.features) {
    const p = f.properties;
    const code = p.ADM0_A3;
    let iso2 = p.ISO_A2;
    if (!/^[A-Z]{2}$/.test(iso2)) iso2 = ISO2_FIX[code] || null;
    const entry = { code, name: p.ADMIN, continent: p.CONTINENT, iso2, feature: f };
    S.countries.push(entry);
    S.byCode[code] = entry;
    if (iso2) S.byIso2[iso2] = entry;
  }
  S.countries.sort((a, b) => a.name.localeCompare(b.name));
  initGlobe(geo.features);
  initSearch();

  api("/api/destinations").then((d) => { S.destinations = d; renderPlannerChips(); });

  const saved = localStorage.getItem("orbit_user");
  if (saved) {
    try {
      S.user = await api("/api/state?user_id=" + saved);
      renderAll();
      return;
    } catch { localStorage.removeItem("orbit_user"); }
  }
  $("onboard").hidden = false;
}

/* events */
document.querySelectorAll(".tab").forEach((t) =>
  t.addEventListener("click", () => switchView(t.dataset.view)));

$("onboardForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const name = $("onboardName").value.trim();
  if (!name) return;
  try {
    const user = await api("/api/profile", { method: "POST", body: { username: name } });
    $("onboard").hidden = true;
    setUser(user);
    toast(`Welcome aboard, ${user.username} — click a country to begin`);
  } catch (err) { toast(err.message); }
});

$("wishForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const place = $("wishInput").value.trim();
  if (!place) return;
  try {
    setUser(await api("/api/wishlist", { method: "POST", body: { place } }));
    $("wishInput").value = "";
    toast(`☆ ${place} added to your dream list`);
  } catch (err) { toast(err.message); }
});

$("friendForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const code = $("friendInput").value.trim().toUpperCase();
  if (!code) return;
  try {
    setUser(await api("/api/friends", { method: "POST", body: { share_code: code } }));
    $("friendInput").value = "";
    toast("Friend added — hit Compare to overlay maps");
  } catch (err) { toast(err.message); }
});

$("planForm").addEventListener("submit", (e) => {
  e.preventDefault();
  const place = $("planInput").value.trim();
  if (place) planTrip(place);
});

$("planRadius").addEventListener("change", () => {
  if (S.lastPlan) planTrip(S.lastPlan.place, S.lastPlan.coords);
});

/* re-annotate (no refetch — hours are already on the items) */
for (const id of ["planStart", "planEnd"]) {
  $(id).addEventListener("change", () => { if (S.plan) renderItinerary(); });
}

$("travelForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  if (!S.trip) return;
  try {
    S.trip = await api(`/api/trips/${S.trip.id}/details`, {
      method: "POST",
      body: {
        flight_number: $("tripFlight").value.trim(),
        start_date: $("tripStart").value || null,
        end_date: $("tripEnd").value || null,
      },
    });
    renderTripDetail();
    refreshUserQuiet();
    toast("Travel details saved");
  } catch (err) { toast(err.message); }
});

$("saveTrip").addEventListener("click", async () => {
  if (!S.plan) return;
  const items = S.plan.items.filter((i) => i.selected);
  try {
    const payload = await api("/api/trips", {
      method: "POST",
      body: {
        destination: S.plan.destination,
        country: S.plan.country,
        tagline: S.plan.tagline,
        start_date: $("planStart").value || null,
        end_date: $("planEnd").value || null,
        invite_ids: S.planWith ? [S.planWith.id] : [],
        items,
      },
    });
    const tripId = payload.saved_trip_id;
    toast(S.planWith
      ? `Trip saved — ${S.planWith.username} is on board`
      : `Trip to ${S.plan.destination} saved`);
    S.planWith = null;
    updatePlanWithNote();
    setUser(payload);
    openTrip(tripId);
  } catch (e) { toast(e.message); }
});

$("planWithCancel").addEventListener("click", () => {
  S.planWith = null;
  updatePlanWithNote();
});

$("tripBack").addEventListener("click", closeTripDetail);

document.querySelectorAll("#lodPill button").forEach((b) =>
  b.addEventListener("click", () => {
    world.controls().autoRotate = false;
    world.pointOfView({ altitude: LOD_FLY[b.dataset.mode] }, 700);
    setTimeout(updateLOD, 750);
  }));

$("copyCode").addEventListener("click", () => {
  navigator.clipboard.writeText(S.user?.share_code || "");
  toast("Share code copied — send it to a friend");
});
$("profileChip").addEventListener("click", () => {
  navigator.clipboard.writeText(S.user?.share_code || "");
  toast("Share code copied — send it to a friend");
});
$("switchProfile").addEventListener("click", () => {
  localStorage.removeItem("orbit_user");
  S.user = null;
  S.planWith = null;
  updatePlanWithNote();
  closeTripDetail();
  exitCompare();
  switchView("globe");
  $("onboard").hidden = false;
  $("onboardName").value = "";
  $("onboardName").focus();
});
$("exitCompare").addEventListener("click", exitCompare);
$("popClose").addEventListener("click", closePop);
document.addEventListener("keydown", (e) => { if (e.key === "Escape") closePop(); });

boot();
