/* ORBIT — globe-first travel tracker: boot and app-wide wiring */

import { api, apiHooks } from "./api.js";
import { authHooks, hasResetToken, initAuth, showAuth } from "./auth.js";
import { closePop, flyToLevel, initGlobe, refreshGlobe } from "./globe.js";
import { switchView } from "./nav.js";
import { initPwa } from "./pwa.js";
import { initSearch } from "./search.js";
import {
  $, ISO2_FIX, S, hooks, isTouch, setUser, toast, visitedContinents,
} from "./state.js";
import { accountHooks, initAccount, renderAccount } from "./views/account.js";
import { addFriendByCode, exitCompare, initFriends, renderFriends } from "./views/friends.js";
import { renderLogbook } from "./views/logbook.js";
import { initPlanner, renderPlannerChips, updatePlanWithNote } from "./views/planner.js";
import { closeTripDetail, initTrips, renderTrips } from "./views/trips.js";
import { initWishlist, renderWishlist } from "./views/wishlist.js";

/* ── stats & profile chip ────────────────────────────── */

function renderStats() {
  const total = S.countries.length;
  const visited = S.user?.visited || [];
  const conts = visitedContinents();
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

function renderAll() {
  renderStats();
  renderLogbook();
  renderWishlist();
  renderFriends();
  renderPlannerChips();
  renderTrips();
  if (!$("accountOverlay").hidden) renderAccount();
  refreshGlobe();
}
hooks.render = renderAll;

/* ── signing in and out ──────────────────────────────── */

function signedOut() {
  S.user = null;
  S.plan = null;
  S.planWith = null;
  updatePlanWithNote();
  closeTripDetail();
  $("itinerary").hidden = true;
  if (S.compare) exitCompare();
  switchView("globe");
  renderAll();
}

apiHooks.unauthorized = () => {
  // first visit, or the session expired / was signed out elsewhere
  const wasSignedIn = !!S.user;
  if (wasSignedIn) signedOut();
  if ($("authOverlay").hidden) showAuth(wasSignedIn ? "login" : undefined);
};

accountHooks.signedOut = () => {
  signedOut();
  showAuth("login");
};

authHooks.signedIn = (payload, isNew) => {
  setUser(payload);
  toast(isNew
    ? `Welcome aboard, ${payload.username} — tap a country to begin`
    : `Welcome back, ${payload.username}`);
  acceptPendingInvite();
};

/* ── invite links: /?add=CODE ────────────────────────── */

function capturePendingInvite() {
  const code = (new URLSearchParams(location.search).get("add") || "").trim().toUpperCase();
  if (!/^[A-Z0-9]{6}$/.test(code)) return;
  try { sessionStorage.setItem("orbit_add", code); } catch { /* private mode */ }
  history.replaceState(null, "", "/");
}

async function acceptPendingInvite() {
  let code = null;
  try {
    code = sessionStorage.getItem("orbit_add");
    sessionStorage.removeItem("orbit_add");
  } catch { /* private mode */ }
  if (!code || !S.user || code === S.user.share_code) return;
  try {
    const name = await addFriendByCode(code);
    toast(`You and ${name} are now friends — compare maps in Friends`);
  } catch (e) { toast(e.message); }
}

/* ── boot ────────────────────────────────────────────── */

async function boot() {
  const [geo, config] = await Promise.all([
    fetch("/static/data/countries.geojson").then((r) => r.json()),
    api("/api/config").catch(() => ({})),
  ]);
  S.config = config || {};
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
  initAuth();
  if (isTouch()) $("legendHint").textContent = "Tap a continent, pinch to zoom in";

  api("/api/destinations").then((d) => { S.destinations = d; renderPlannerChips(); }).catch(() => {});
  capturePendingInvite();

  if (hasResetToken()) { showAuth("reset"); return; }
  if (S.config.signed_in === false) { showAuth(); return; }
  try {
    setUser(await api("/api/state"));
    acceptPendingInvite();
  } catch (e) {
    // a 401 already opened the sign-in card via apiHooks.unauthorized
    if ($("authOverlay").hidden) toast(e.message);
  }
}

/* events */
document.querySelectorAll(".tab").forEach((t) =>
  t.addEventListener("click", () => switchView(t.dataset.view)));
document.querySelectorAll("#lodPill button").forEach((b) =>
  b.addEventListener("click", () => flyToLevel(b.dataset.mode)));
$("popClose").addEventListener("click", closePop);
document.addEventListener("keydown", (e) => { if (e.key === "Escape") closePop(); });

initWishlist();
initFriends();
initPlanner();
initTrips();
initAccount();
initPwa();

boot();
