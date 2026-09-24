/* ORBIT — the globe's "fly to a country or city" search box */

import { api } from "./api.js";
import { flyTo, flyToCity } from "./globe.js";
import { $, S, cityStatus, countryStatus, esc, flag } from "./state.js";

export function initSearch() {
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
    input.blur(); // drop the phone keyboard so the globe is visible
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
