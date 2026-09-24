/* ORBIT — My trips: saved shortlists, check-offs, crew and votes */

import { api } from "../api.js";
import { switchView } from "../nav.js";
import { $, S, esc, flightInfo, fmtDate, setUser, stayDays, toast } from "../state.js";
import { sectionsHtml } from "./planner.js";

export function renderTrips() {
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
        <button class="btn btn-danger btn-sm" data-act="del" aria-label="${t.is_owner ? "Delete" : "Leave"} trip">✕</button>
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
          if (!confirm(`Leave the trip to ${t.destination}?`)) return;
          setUser(await api(`/api/trips/${id}/members/${S.user.id}`, { method: "DELETE" }));
          toast("You left the trip");
        } else {
          if (!confirm(`Delete the trip to ${t.destination}${t.members.length ? " for everyone on it" : ""}?`)) return;
          setUser(await api(`/api/trips/${id}`, { method: "DELETE" }));
          toast("Trip deleted");
        }
      } catch (e) { toast(e.message); }
    });
  });
}

export async function openTrip(id) {
  try {
    S.trip = await api(`/api/trips/${id}`);
    switchView("trips");
    renderTripDetail();
    $("view-trips").scrollTop = 0;
  } catch (e) { toast(e.message); }
}

export function closeTripDetail() {
  S.trip = null;
  $("tripDetail").hidden = true;
  $("tripListWrap").hidden = false;
}

async function refreshUserQuiet() {
  try { setUser(await api("/api/state")); } catch { /* keep stale */ }
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

  $("travelForm").hidden = !trip.is_owner;
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
        S.trip = await api(`/api/trips/${trip.id}/items/${itemId}/toggle`, { method: "POST" });
        renderTripDetail();
        refreshUserQuiet();
      } catch (e) { toast(e.message); }
    });
    const vote = card.querySelector('[data-act="vote"]');
    if (vote) vote.addEventListener("click", async () => {
      try {
        S.trip = await api(`/api/trips/${trip.id}/items/${itemId}/vote`, { method: "POST" });
        renderTripDetail();
      } catch (e) { toast(e.message); }
    });
    const del = card.querySelector('[data-act="del"]');
    if (del) del.addEventListener("click", async () => {
      try {
        S.trip = await api(`/api/trips/${trip.id}/items/${itemId}`, { method: "DELETE" });
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
        <select id="inviteSelect" aria-label="Friend to invite">${candidates.map(
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
        S.trip = await api(`/api/trips/${trip.id}/members/${btn.dataset.kick}`, { method: "DELETE" });
        renderTripDetail();
        toast("Removed from the trip");
      } catch (e) { toast(e.message); }
    }));
  const leave = $("leaveTrip");
  if (leave) leave.addEventListener("click", async () => {
    try {
      setUser(await api(`/api/trips/${trip.id}/members/${S.user.id}`, { method: "DELETE" }));
      closeTripDetail();
      toast("You left the trip");
    } catch (e) { toast(e.message); }
  });
}

export function initTrips() {
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
  $("tripBack").addEventListener("click", closeTripDetail);
}
