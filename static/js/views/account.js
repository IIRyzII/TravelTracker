/* ORBIT — the Account sheet: name, password, share code, export, delete */

import { api } from "../api.js";
import { $, S, esc, setUser, shareInvite, toast } from "../state.js";

export const accountHooks = { signedOut: () => {} };

export function openAccount() {
  if (!S.user) return;
  renderAccount();
  $("accountOverlay").hidden = false;
  $("accountClose").focus();
}

export function closeAccount() {
  $("accountOverlay").hidden = true;
  $("deleteForm").reset();
  $("passwordForm").reset();
}

export function renderAccount() {
  const u = S.user;
  if (!u) return;
  $("accountAvatar").textContent = u.username[0].toUpperCase();
  $("accountTitle").textContent = u.username;
  $("accountEmail").innerHTML = esc(u.email || "") +
    (u.google_linked ? ` <span class="sheet-tag">Google</span>` : "");
  $("planBadge").textContent = u.plan === "pro" ? "Pro" : "Free";
  $("planBadge").classList.toggle("pro", u.plan === "pro");
  $("accountCode").textContent = u.share_code;
  if (document.activeElement !== $("accountName")) $("accountName").value = u.username;
  // Google-only accounts set a first password without the old one
  $("currentPassword").hidden = !u.has_password;
  $("passwordLabel").textContent = u.has_password ? "Change password" : "Add a password";
  $("deletePassword").hidden = !u.has_password;
}

export function initAccount() {
  $("profileChip").addEventListener("click", openAccount);
  $("accountClose").addEventListener("click", closeAccount);
  $("accountOverlay").addEventListener("click", (e) => {
    if (e.target === $("accountOverlay")) closeAccount();
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !$("accountOverlay").hidden) closeAccount();
  });
  $("accountShare").addEventListener("click", shareInvite);

  $("accountRotate").addEventListener("click", async () => {
    if (!confirm("Get a new share code? Your old code stops working, but existing friends stay.")) return;
    try {
      setUser(await api("/api/share_code/rotate", { method: "POST" }));
      toast("New share code ready");
    } catch (e) { toast(e.message); }
  });

  $("nameForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    const username = $("accountName").value.trim();
    if (!username || username === S.user.username) return;
    try {
      setUser(await api("/api/account", { method: "PATCH", body: { username } }));
      $("accountName").blur();
      toast("Name updated");
    } catch (err) { toast(err.message); }
  });

  $("passwordForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    try {
      setUser(await api("/api/account", {
        method: "PATCH",
        body: { current_password: $("currentPassword").value, new_password: $("newPassword").value },
      }));
      $("passwordForm").reset();
      toast("Password saved — other devices have been signed out");
    } catch (err) { toast(err.message); }
  });

  $("signOut").addEventListener("click", async () => {
    try { await api("/api/auth/logout", { method: "POST" }); } catch { /* signed out anyway */ }
    closeAccount();
    accountHooks.signedOut();
    toast("Signed out");
  });

  $("deleteForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    try {
      await api("/api/account", {
        method: "DELETE",
        body: { password: $("deletePassword").value, confirm: $("deleteConfirm").value.trim().toUpperCase() },
      });
      closeAccount();
      accountHooks.signedOut();
      toast("Your account and data have been deleted");
    } catch (err) { toast(err.message); }
  });
}
