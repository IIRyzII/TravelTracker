/* ORBIT — Logbook: continents → countries → cities & towns */

import { api } from "../api.js";
import { flyTo, flyToCity } from "../globe.js";
import { switchView } from "../nav.js";
import { $, S, esc, flag, setUser, toast, visitedContinents } from "../state.js";

export function renderLogbook() {
  const visited = S.user?.visited || [];
  const cities = S.user?.visited_cities || [];
  $("logEmpty").hidden = visited.length > 0 || cities.length > 0;

  const conts = visitedContinents();
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
