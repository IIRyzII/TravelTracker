/* ORBIT — switching between the Globe and the list views */

import { closePop, setGlobeActive } from "./globe.js";

export function switchView(name) {
  document.querySelectorAll(".view").forEach((v) => v.classList.toggle("active", v.id === "view-" + name));
  document.querySelectorAll(".tab").forEach((t) => {
    const on = t.dataset.view === name;
    t.classList.toggle("active", on);
    if (on) t.setAttribute("aria-current", "page");
    else t.removeAttribute("aria-current");
  });
  closePop();
  setGlobeActive(name === "globe");
}
