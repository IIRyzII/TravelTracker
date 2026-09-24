/* ORBIT — Friends: share codes, invite links and map comparison */

import { api } from "../api.js";
import { refreshGlobe } from "../globe.js";
import { switchView } from "../nav.js";
import { $, S, copyText, esc, setUser, shareInvite, toast, visitedSet } from "../state.js";
import { updatePlanWithNote } from "./planner.js";

export function renderFriends() {
  const list = $("friendList");
  const friends = S.user?.friends || [];
  $("friendEmpty").hidden = friends.length > 0;
  list.innerHTML = friends.map((f) => `
    <li class="friend-item" data-id="${f.id}">
      <span class="friend-main">
        <span class="avatar friend-avatar">${esc(f.username[0].toUpperCase())}</span>
        <span class="wish-place">${esc(f.username)}</span>
        <span class="friend-stats">
          <span class="friend-stat"><b>${f.visited_count}</b><span>countries</span></span>
          <span class="friend-stat"><b>${f.overlap}</b><span>in common</span></span>
        </span>
      </span>
      <span class="row-actions">
        <button class="btn btn-ghost btn-sm" data-act="plan">Plan together</button>
        <button class="btn btn-primary btn-sm" data-act="compare">Compare on globe</button>
        <button class="btn btn-danger btn-sm" data-act="remove" aria-label="Remove friend">✕</button>
      </span>
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
        } else if (confirm(`Remove ${f.username} from your friends?`)) {
          setUser(await api(`/api/friends/${id}`, { method: "DELETE" }));
          toast(`${f.username} removed`);
        }
      } catch (e) { toast(e.message); }
    });
  });
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

export function exitCompare() {
  S.compare = null;
  $("compareBanner").hidden = true;
  $("globeLegend").hidden = false;
  refreshGlobe();
}

export async function addFriendByCode(code) {
  const payload = await api("/api/friends", { method: "POST", body: { share_code: code } });
  setUser(payload);
  return payload.added_friend;
}

export function initFriends() {
  $("friendForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    const code = $("friendInput").value.trim().toUpperCase();
    if (!code) return;
    try {
      const name = await addFriendByCode(code);
      $("friendInput").value = "";
      toast(`${name} added — hit Compare to overlay maps`);
    } catch (err) { toast(err.message); }
  });
  $("copyCode").addEventListener("click", () =>
    copyText(S.user?.share_code || "", "Share code copied — send it to a friend"));
  $("shareInvite").addEventListener("click", shareInvite);
  $("exitCompare").addEventListener("click", exitCompare);
}
