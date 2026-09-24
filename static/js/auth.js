/* ORBIT — sign in, create account, forgot / reset password, Google */

import { api } from "./api.js";
import { $, S } from "./state.js";

export const authHooks = { signedIn: (_payload, _isNew) => {} };

let mode = "signup";
let resetToken = null;
let busy = false;

const COPY = {
  signup: { submit: "Create account", pitch: "Track every country you've set foot in, show it off on a globe, compare with friends and plan the next one." },
  login: { submit: "Sign in", pitch: "Welcome back — sign in to pick up your map where you left it." },
  forgot: { submit: "Send reset link", pitch: "Enter your account's email and we'll send you a link to set a new password." },
  reset: { submit: "Set new password", pitch: "Choose a new password for your ORBIT account." },
};

function remembered() {
  try { return localStorage.getItem("orbit_seen") === "1"; } catch { return false; }
}

function setMode(next) {
  mode = next;
  const tabbed = mode === "signup" || mode === "login";
  $("authTabs").hidden = !tabbed;
  $("authTabs").querySelectorAll("button").forEach((b) =>
    b.classList.toggle("active", b.dataset.auth === mode));
  $("authName").hidden = mode !== "signup";
  $("authEmail").hidden = mode === "reset";
  $("authPassword").hidden = mode === "forgot";
  $("authPassword").autocomplete = mode === "login" ? "current-password" : "new-password";
  $("authPassword").placeholder = mode === "login" ? "Password" : "Password (8+ characters)";
  $("authSubmit").textContent = COPY[mode].submit;
  $("authPitch").textContent = COPY[mode].pitch;
  $("forgotLink").hidden = mode !== "login";
  $("backToLogin").hidden = !(mode === "forgot" || mode === "reset");
  $("authLegal").hidden = mode !== "signup";
  $("googleWrap").hidden = !(tabbed && S.config.google_client_id && window.google?.accounts);
  showMessage("");
}

function showMessage(text, ok = false) {
  const el = $("authError");
  el.textContent = text;
  el.hidden = !text;
  el.classList.toggle("ok", ok);
}

export function showAuth(startMode) {
  setMode(startMode || (remembered() ? "login" : "signup"));
  $("authOverlay").hidden = false;
  const first = mode === "signup" ? $("authName") : mode === "reset" ? $("authPassword") : $("authEmail");
  if (window.matchMedia("(hover: hover)").matches) first.focus(); // don't pop the phone keyboard
}

export function hideAuth() {
  $("authOverlay").hidden = true;
  $("authForm").reset();
  showMessage("");
}

function signedIn(payload, isNew) {
  try { localStorage.setItem("orbit_seen", "1"); } catch { /* private mode */ }
  hideAuth();
  authHooks.signedIn(payload, isNew);
}

async function submit(e) {
  e.preventDefault();
  if (busy) return;
  const email = $("authEmail").value.trim();
  const password = $("authPassword").value;
  const username = $("authName").value.trim();
  busy = true;
  $("authSubmit").disabled = true;
  try {
    if (mode === "signup") {
      signedIn(await api("/api/auth/signup", { method: "POST", body: { email, password, username } }), true);
    } else if (mode === "login") {
      signedIn(await api("/api/auth/login", { method: "POST", body: { email, password } }), false);
    } else if (mode === "forgot") {
      const res = await api("/api/auth/forgot", { method: "POST", body: { email } });
      showMessage(res.message, true);
    } else if (mode === "reset") {
      const payload = await api("/api/auth/reset", { method: "POST", body: { token: resetToken, password } });
      history.replaceState(null, "", "/");
      resetToken = null;
      signedIn(payload, false);
    }
  } catch (err) {
    showMessage(err.message);
  } finally {
    busy = false;
    $("authSubmit").disabled = false;
  }
}

function loadGoogle(clientId) {
  const script = document.createElement("script");
  script.src = "https://accounts.google.com/gsi/client";
  script.async = true;
  script.onload = () => {
    window.google.accounts.id.initialize({
      client_id: clientId,
      callback: async ({ credential }) => {
        try {
          const res = await fetch("/api/auth/google", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ credential }),
          });
          const data = await res.json();
          if (!res.ok) throw new Error(data.error || "Google sign-in failed");
          signedIn(data, res.status === 201);
        } catch (err) { showMessage(err.message); }
      },
    });
    window.google.accounts.id.renderButton($("googleBtn"), {
      theme: "filled_black", size: "large", shape: "pill", text: "continue_with",
      width: Math.min(320, $("authForm").clientWidth || 300),
    });
    if (!$("authOverlay").hidden) setMode(mode);
  };
  document.head.appendChild(script);
}

/* a /reset?token=... link from the password email */
export function resetTokenFromUrl() {
  if (location.pathname !== "/reset") return null;
  return new URLSearchParams(location.search).get("token");
}

export function initAuth() {
  $("authForm").addEventListener("submit", submit);
  $("authTabs").querySelectorAll("button").forEach((b) =>
    b.addEventListener("click", () => setMode(b.dataset.auth)));
  $("forgotLink").addEventListener("click", () => setMode("forgot"));
  $("backToLogin").addEventListener("click", () => {
    if (mode === "reset") history.replaceState(null, "", "/");
    setMode("login");
  });
  if (S.config.google_client_id) loadGoogle(S.config.google_client_id);
  resetToken = resetTokenFromUrl();
}

export function startReset() {
  showAuth("reset");
}

export const hasResetToken = () => !!resetToken;
