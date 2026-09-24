/* ORBIT — installable app: service worker, install button, offline notice */

import { $, toast } from "./state.js";

let installPrompt = null;

export function initPwa() {
  if ("serviceWorker" in navigator && (location.protocol === "https:" || location.hostname === "localhost"
      || location.hostname === "127.0.0.1")) {
    window.addEventListener("load", () => {
      navigator.serviceWorker.register("/sw.js").catch(() => { /* app works without it */ });
    });
  }

  // Chrome/Android: offer "Install app" in the Account sheet
  window.addEventListener("beforeinstallprompt", (e) => {
    e.preventDefault();
    installPrompt = e;
    $("installApp").hidden = false;
  });
  $("installApp").addEventListener("click", async () => {
    if (!installPrompt) return;
    installPrompt.prompt();
    await installPrompt.userChoice;
    installPrompt = null;
    $("installApp").hidden = true;
  });
  window.addEventListener("appinstalled", () => toast("ORBIT installed — find it on your home screen"));

  window.addEventListener("offline", () => toast("You're offline — changes won't save until you're back"));
  window.addEventListener("online", () => toast("Back online"));
}
