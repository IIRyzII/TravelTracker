/* ORBIT service worker — served at /sw.js so it covers the whole site.

   - App shell (page, CSS, JS modules): network first, cached copy when offline.
   - Vendor code, map data, icons: cache first (their URLs are versioned).
   - /api/*: always the network — your data is never served stale.

   Bump VERSION when the precache list changes. tests/test_pwa.py checks
   that every JS module is listed here. */

const VERSION = "orbit-v1";
const SHELL = [
  "/",
  "/static/css/app.css",
  "/static/manifest.webmanifest",
  "/static/js/main.js",
  "/static/js/api.js",
  "/static/js/auth.js",
  "/static/js/globe.js",
  "/static/js/nav.js",
  "/static/js/pwa.js",
  "/static/js/search.js",
  "/static/js/state.js",
  "/static/js/views/account.js",
  "/static/js/views/friends.js",
  "/static/js/views/logbook.js",
  "/static/js/views/planner.js",
  "/static/js/views/trips.js",
  "/static/js/views/wishlist.js",
  "/static/vendor/globe.gl.min.js",
  "/static/data/countries.geojson",
  "/static/icons/icon-192.png",
];
const CACHE_FIRST = ["/static/vendor/", "/static/data/", "/static/icons/"];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(VERSION).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== VERSION).map((k) => caches.delete(k))))
      .then(() => self.clients.claim()));
});

async function cacheFirst(request) {
  const cached = await caches.match(request);
  if (cached) return cached;
  const response = await fetch(request);
  if (response.ok) (await caches.open(VERSION)).put(request, response.clone());
  return response;
}

async function networkFirst(request, fallbackUrl) {
  try {
    const response = await fetch(request);
    if (response.ok) (await caches.open(VERSION)).put(request, response.clone());
    return response;
  } catch (err) {
    const cached = await caches.match(request) || (fallbackUrl && await caches.match(fallbackUrl));
    if (cached) return cached;
    throw err;
  }
}

self.addEventListener("fetch", (event) => {
  const { request } = event;
  const url = new URL(request.url);
  if (request.method !== "GET" || url.origin !== self.location.origin) return;
  if (url.pathname.startsWith("/api/")) return;
  if (CACHE_FIRST.some((p) => url.pathname.startsWith(p))) {
    event.respondWith(cacheFirst(request));
  } else if (request.mode === "navigate") {
    event.respondWith(networkFirst(request, "/"));
  } else {
    event.respondWith(networkFirst(request));
  }
});
