/* ORBIT — the globe: colours, zoom levels, city labels and the place popover */

import { api } from "./api.js";
import { switchView } from "./nav.js";
import {
  $, C, S, centroid, cityKey, cityStatus, countryStatus, flag, fold, isPhone, isTouch,
  setUser, toast, visitedSet,
} from "./state.js";
import { planTrip } from "./views/planner.js";

let world; // globe.gl instance

/* zoom altitude -> detail level */
function modeForAlt(alt) {
  if (alt >= 1.7) return "continent";
  if (alt >= 0.55) return "country";
  if (alt >= 0.22) return "city";
  return "town";
}
const CONTINENT_VIEWS = {
  "Africa": { lat: 2, lng: 20 },
  "Europe": { lat: 52, lng: 14 },
  "Asia": { lat: 34, lng: 92 },
  "North America": { lat: 44, lng: -100 },
  "South America": { lat: -16, lng: -60 },
  "Oceania": { lat: -26, lng: 140 },
  "Antarctica": { lat: -78, lng: 20 },
};
const STATUS_LABEL = {
  you: "Visited", wish: "On your wishlist", friend: "", both: "", none: "Not visited yet",
};

/* far enough out that the whole globe fits a narrow portrait screen */
function homeAltitude() {
  const aspect = window.innerWidth / window.innerHeight;
  if (aspect >= 1) return 2.2;
  const halfFov = (50 / 2) * Math.PI / 180;           // globe.gl's camera fov
  const fit = 1 / Math.sin(Math.atan(Math.tan(halfFov) * aspect)) - 1;
  return Math.max(2.2, fit * 0.9);
}
const lodAltitude = (mode) => ({ continent: homeAltitude(), country: 1.1, city: 0.4, town: 0.15 }[mode]);

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

export function refreshGlobe() {
  if (!world) return;
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

export function initGlobe(features) {
  world = Globe()($("globe"))
    .backgroundColor("rgba(0,0,0,0)") // let the CSS glow behind the globe show
    .showAtmosphere(true)
    .atmosphereColor(C.you)
    .atmosphereAltitude(0.18)
    .polygonsData(features)
    .polygonSideColor(() => "rgba(0,0,0,0.45)")
    .polygonsTransitionDuration(200)
    .polygonLabel((d) => {
      if (isTouch()) return ""; // tooltips stick on touch screens; the popover does the job
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
      if (isTouch()) return; // a tap isn't a hover — don't leave countries raised
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

  // retina phones report 3x; 2x looks the same and renders far cheaper
  world.renderer().setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  world.globeMaterial().color.set(C.ocean);
  world.controls().autoRotate = true;
  world.controls().autoRotateSpeed = 0.45;
  world.controls().addEventListener("start", () => (world.controls().autoRotate = false));
  let lodTimer;
  world.controls().addEventListener("change", () => {
    clearTimeout(lodTimer);
    lodTimer = setTimeout(updateLOD, 120);
  });
  world.pointOfView({ lat: 24, lng: 10, altitude: homeAltitude() });
  refreshGlobe();
  updateLOD();

  window.addEventListener("resize", () =>
    world.width(window.innerWidth).height(window.innerHeight));
  document.addEventListener("visibilitychange", () =>
    setGlobeActive($("view-globe").classList.contains("active")));
}

/* stop rendering while the globe is hidden — saves a phone's battery */
export function setGlobeActive(active) {
  if (!world) return;
  if (active && !document.hidden) world.resumeAnimation();
  else world.pauseAnimation();
}

/* fly the camera and re-sync the detail level once the animation lands
   (programmatic moves don't fire the controls' change event) */
export function goTo(view, ms = 900) {
  world.controls().autoRotate = false;
  world.pointOfView(view, ms);
  setTimeout(updateLOD, ms + 60);
}

export function flyToLevel(mode) {
  goTo({ altitude: lodAltitude(mode) }, 700);
}

export function flyTo(code) {
  const c = S.byCode[code];
  if (!c) return;
  const { lat, lng } = centroid(c.feature);
  goTo({ lat, lng, altitude: 1.5 });
  setTimeout(() => openPop(code), 950);
}

export function flyToCity(city) {
  world.controls().autoRotate = false;
  S.searchMarker = { ...city, type: "search", size: 0.34, dot: 0.13, alt: 0.008, color: "#ffffff" };
  world.pointOfView({ lat: city.lat, lng: city.lng, altitude: 0.4 }, 900);
  setTimeout(() => { updateLOD(); openCityPop(city); }, 950);
}

/* ── level of detail: continents → countries → cities → towns ── */

// places come in two files: cities (pop ≥ 15k, ~1 MB) first, then towns
const tierLoads = {};
function loadCityTier(tier) {
  if (!tierLoads[tier]) {
    // the version is a fingerprint of the files (they're cached for a week)
    const version = S.config.data_version || "1";
    tierLoads[tier] = fetch(`/static/data/cities-${tier}.json?v=${version}`)
      .then((r) => { if (!r.ok) throw new Error(r.status); return r.json(); })
      .then((raw) => {
        addToGrid(raw);
        updateLOD();
        if (tier === 1) prefetchTowns();
      })
      .catch(() => {
        delete tierLoads[tier];
        toast("Couldn't load the city layer");
      });
  }
  return tierLoads[tier];
}

function prefetchTowns() {
  const conn = navigator.connection;
  if (conn && (conn.saveData || /2g/.test(conn.effectiveType || ""))) return;
  loadCityTier(2);
}

/* villages (under 1,000 people) come from the server a view at a time, once
   its places database is built — too many to ship to the phone */
let villageKey = null;
function loadVillages(lat, lng, radius) {
  const step = radius / 8; // re-ask only after panning a fair way
  const key = `${Math.round(lat / step)},${Math.round(lng / step)},${radius.toFixed(1)}`;
  if (key === villageKey) return;
  villageKey = key;
  api(`/api/places/near?lat=${lat.toFixed(3)}&lng=${lng.toFixed(3)}&radius=${radius.toFixed(2)}`)
    .then((list) => {
      if (key !== villageKey) return; // the view moved on
      S.villages = list;
      updateLOD();
    })
    .catch(() => { villageKey = null; });
}

const CELL = 5; // degrees
const COLS = 360 / CELL;
const cellOf = (lat, lng) =>
  Math.min(Math.floor((lat + 90) / CELL), 180 / CELL - 1) * 1000 +
  (Math.floor((lng + 180) / CELL) % COLS);

function addToGrid(raw) {
  S.cityGrid = S.cityGrid || new Map();
  for (const [name, iso2, lat, lng, pop] of raw) {
    const key = cellOf(lat, lng);
    let cell = S.cityGrid.get(key);
    if (!cell) S.cityGrid.set(key, (cell = []));
    cell.push({ name, iso2, lat, lng, pop });
  }
}

/* grid cells that can hold a place within `radius` (same metric as dist below) */
function* nearbyPlaces(lat, lng, radius, cosLat) {
  const r0 = Math.max(0, Math.floor((lat - radius + 90) / CELL));
  const r1 = Math.min(180 / CELL - 1, Math.floor((lat + radius + 90) / CELL));
  const span = radius / cosLat;
  const cols = new Set();
  if (span >= 180) for (let c = 0; c < COLS; c++) cols.add(c);
  else {
    const c0 = Math.floor((lng - span + 180) / CELL), c1 = Math.floor((lng + span + 180) / CELL);
    for (let c = c0; c <= c1; c++) cols.add(((c % COLS) + COLS) % COLS);
  }
  for (let r = r0; r <= r1; r++) {
    for (const c of cols) {
      const cell = S.cityGrid.get(r * 1000 + c);
      if (cell) yield* cell;
    }
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
  if (!S.cityGrid) { loadCityTier(1); return []; }
  const pov = world.pointOfView();
  const town = S.mode === "town";
  if (town) loadCityTier(2);
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
  const consider = (c) => {
    const d = dist(c.lat, c.lng, pov.lat, pov.lng);
    if (d <= radius) cand.push([Math.log10(c.pop + 1) - 2.2 * (d / radius), c]);
  };
  for (const c of nearbyPlaces(pov.lat, pov.lng, radius, cosLat)) consider(c);
  if (town && S.config.villages) {
    loadVillages(pov.lat, pov.lng, radius);
    for (const c of S.villages || []) consider(c);
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
  // label size lives in globe units — scale it with zoom so text stays readable;
  // fingers need bigger dots to hit
  const dotScale = isTouch() ? 1.6 : 1;
  return out.map((c) => {
    const st = cityStatus(c);
    return {
      ...c, type: "place", alt: 0.006,
      size: alt * (c.pop >= 1e6 ? 0.8 : c.pop >= 200000 ? 0.65 : c.pop >= 30000 ? 0.52 : 0.44),
      dot: alt * (st === "none" ? 0.3 : 0.42) * dotScale,
      color: st === "you" ? C.you : st === "wish" ? C.wish : "#e8e6dc",
    };
  });
}

export function updateLOD() {
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
  if (S.searchMarker && mode !== "continent") {
    // scale with zoom like the other labels, just a little bigger
    const alt = Math.max(world.pointOfView().altitude, 0.05);
    labels = labels.concat({ ...S.searchMarker, size: alt * 0.95, dot: alt * 0.4 });
  }
  world.labelsData(labels);
}

/* ── place popover (a bottom sheet on phones) ───────── */

export function closePop() { $("countryPop").hidden = true; }

function placePop(x, y) {
  const pop = $("countryPop");
  pop.hidden = false;
  const sheet = isPhone();
  pop.classList.toggle("as-sheet", sheet);
  if (sheet) {
    pop.style.left = pop.style.top = "";
    return;
  }
  const px = x != null ? x + 14 : window.innerWidth - 320;
  const py = y != null ? y - 20 : 160;
  const rect = pop.getBoundingClientRect();
  pop.style.left = Math.min(Math.max(12, px), window.innerWidth - rect.width - 12) + "px";
  pop.style.top = Math.min(Math.max(72, py), window.innerHeight - rect.height - 12) + "px";
}

export function openPop(code, x, y) {
  const c = S.byCode[code];
  if (!c) return;
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

  placePop(x, y);
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
      setUser(await api(`/api/wishlist/${wishItem.id}`, { method: "DELETE" }));
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

export function openCityPop(city, x, y) {
  const countryEntry = S.byIso2[city.iso2];
  const countryName = city.country || (countryEntry ? countryEntry.name : "");
  const placeLabel = city.name + (countryName ? ", " + countryName : "");
  const status = cityStatus(city);
  const wishItem = (S.user?.wishlist || []).find(
    (w) => fold(w.place.split(",")[0]) === fold(city.name));

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
          setUser(await api(`/api/wishlist/${wishItem.id}`, { method: "DELETE" }));
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

  placePop(x, y);
}
