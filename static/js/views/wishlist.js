/* ORBIT — Dream list */

import { api } from "../api.js";
import { switchView } from "../nav.js";
import { $, S, esc, flag, setUser, toast } from "../state.js";
import { planTrip } from "./planner.js";

export function renderWishlist() {
  const list = $("wishList");
  const items = S.user?.wishlist || [];
  $("wishEmpty").hidden = items.length > 0;
  list.innerHTML = items.map((w) => {
    const iso2 = w.code ? S.byCode[w.code]?.iso2 : null;
    return `<li class="wish-item" data-id="${w.id}">
      <span class="wish-flag">${flag(iso2)}</span>
      <span class="wish-text"><span class="wish-place">${esc(w.place)}</span>
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
          setUser(await api(`/api/wishlist/${item.id}`, { method: "DELETE" }));
          toast("Removed from your dream list");
        } else if (btn.dataset.act === "visited") {
          await api("/api/visited", { method: "POST", body: { code: item.code } });
          setUser(await api(`/api/wishlist/${item.id}`, { method: "DELETE" }));
          toast(`✓ ${item.place} — dream achieved!`);
        }
      } catch (e) { toast(e.message); }
    });
  });
}

export function initWishlist() {
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
}
