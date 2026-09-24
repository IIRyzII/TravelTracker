/* ORBIT — Trip planner: build a shortlist, pick what you like, save it */

import { api } from "../api.js";
import {
  $, CAT_DOT, CAT_ORDER, S, closedDuring, esc, setUser, stayDays, toast,
} from "../state.js";
import { openTrip } from "./trips.js";

export function renderPlannerChips() {
  const wishes = S.user?.wishlist || [];
  $("wishChips").innerHTML = wishes.length
    ? `<span class="chip-row-label">From your wishlist</span>` +
      wishes.map((w) => `<button class="chip chip-wish" data-place="${esc(w.place)}">☆ ${esc(w.place)}</button>`).join("")
    : "";
  $("destChips").innerHTML = S.destinations.length
    ? `<span class="chip-row-label">Popular shortlists</span>` +
      S.destinations.map((d) => `<button class="chip" data-place="${esc(d.destination)}">${esc(d.destination)}</button>`).join("")
    : "";
  document.querySelectorAll("#wishChips .chip, #destChips .chip").forEach((chip) =>
    chip.addEventListener("click", () => planTrip(chip.dataset.place)));
}

export function updatePlanWithNote() {
  const note = $("planWithNote");
  note.hidden = !S.planWith;
  if (S.planWith) {
    $("planWithText").innerHTML =
      `Planning with <b>${esc(S.planWith.username)}</b> — they'll be added to the trip when you save it.`;
  }
}

export async function planTrip(place, coords) {
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
    if (S.user && plan.live_left != null) S.user.live_left = plan.live_left;
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

export function itemCard(i, opts) {
  const boxAttrs = opts.done
    ? `class="done-box" ${i.done ? "checked" : ""} aria-label="Mark ${esc(i.title)} done"`
    : `${i.selected ? "checked" : ""} aria-label="Include ${esc(i.title)}"`;
  const closed = closedDuring(i.open_days, opts.days);
  const closedChip = closed
    ? `<span class="closed-chip${closed.all ? " closed-all" : ""}">${
        closed.all ? "Closed during your stay" : "Closed " + closed.names.join(" · ")}</span>`
    : "";
  const actions = [
    opts.votes ? `<button class="vote-btn${i.my_vote ? " voted" : ""}" data-act="vote"
        title="Vote for this">♥ ${i.votes || 0}</button>` : "",
    i.maps_url ? `<a class="maps-link" href="${esc(i.maps_url)}" target="_blank" rel="noopener">Maps ↗</a>` : "",
    opts.canRemove ? `<button class="btn btn-danger btn-sm" data-act="del" aria-label="Remove">✕</button>` : "",
  ].join("");
  return `<div class="itin-item ${opts.done && i.done ? "done" : ""} ${!opts.done && !i.selected ? "deselected" : ""}"
        data-id="${opts.id}">
    <input type="checkbox" ${boxAttrs}>
    <div class="itin-body">
      <b>${esc(i.title)}</b>
      ${ratingHtml(i)}
      ${i.desc ? `<span class="itin-desc">${esc(i.desc)}</span>` : ""}
      ${closedChip}
    </div>
    ${actions ? `<span class="itin-actions">${actions}</span>` : ""}
  </div>`;
}

export function sectionsHtml(items, opts) {
  return CAT_ORDER.map((cat) => {
    const catItems = items.filter((i) => i.category === cat);
    if (!catItems.length) return "";
    return `<section class="itin-section">
      <div class="itin-cat"><i class="dot" style="background:${CAT_DOT[cat]}"></i>${cat}</div>
      <div class="itin-items">${catItems.map((i) => itemCard(i, { ...opts, id: i._id })).join("")}</div>
    </section>`;
  }).join("");
}

function planNote(plan) {
  if (plan.live_limited) {
    return "You've used today's live Google Maps lookups, so this is our saved list. " +
      "They reset at midnight UTC.";
  }
  if (plan.live && plan.live_left != null) {
    return `${plan.live_left} live Google Maps lookup${plan.live_left === 1 ? "" : "s"} left today.`;
  }
  return "";
}

export function renderItinerary() {
  const plan = S.plan;
  plan.items.forEach((i, idx) => (i._id = idx));
  $("itinerary").hidden = false;
  $("itinTitle").textContent = plan.destination;
  $("itinTagline").textContent = plan.tagline;
  const badge = $("itinBadge");
  badge.textContent = plan.live ? "Live · Google Maps" : plan.curated ? "Curated" : "Starter list";
  badge.classList.toggle("curated", !!(plan.live || plan.curated));
  const note = planNote(plan);
  $("itinNote").hidden = !note;
  $("itinNote").textContent = note;

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

export function initPlanner() {
  $("planForm").addEventListener("submit", (e) => {
    e.preventDefault();
    const place = $("planInput").value.trim();
    $("planInput").blur();
    if (place) planTrip(place);
  });

  $("planRadius").addEventListener("change", () => {
    if (S.lastPlan) planTrip(S.lastPlan.place, S.lastPlan.coords);
  });

  /* re-annotate (no refetch — hours are already on the items) */
  for (const id of ["planStart", "planEnd"]) {
    $(id).addEventListener("change", () => { if (S.plan) renderItinerary(); });
  }

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
}
