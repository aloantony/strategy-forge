// panels/strategies.js — listado de estrategias + activar/desactivar.

import { apiGet, apiPost } from "../api.js";

export async function refreshStrategies() {
  const list = document.getElementById("strategies-list");
  const empty = document.getElementById("strategies-empty");
  let strategies = [];
  try {
    strategies = await apiGet("/api/strategies");
  } catch (err) {
    empty.hidden = false;
    empty.textContent = err.message;
    return [];
  }
  empty.hidden = strategies.length > 0;
  list.innerHTML = "";

  for (const strat of strategies) {
    const item = document.createElement("div");
    item.className = "item";

    const main = document.createElement("div");
    main.className = "main";
    const title = document.createElement("div");
    title.className = "title";
    title.textContent = strat.label ?? strat.key;
    const sub = document.createElement("div");
    sub.className = "sub";
    sub.textContent = [strat.timeframe || null,
                       strat.magic_number ? `magic ${strat.magic_number}` : null,
                       strat.has_config ? "builder" : "manual"]
      .filter(Boolean).join(" · ");
    main.append(title, sub);

    const toggle = document.createElement("button");
    toggle.type = "button";
    toggle.className = strat.enabled ? "on" : "";
    toggle.textContent = strat.enabled ? "Activa" : "Inactiva";
    toggle.addEventListener("click", async () => {
      toggle.disabled = true;
      try {
        await apiPost(`/api/strategies/${encodeURIComponent(strat.key)}/${strat.enabled ? "disable" : "enable"}`);
        await refreshStrategies();
      } catch (err) {
        toggle.disabled = false;
        alert(err.message);
      }
    });

    item.append(main, toggle);
    list.appendChild(item);
  }
  return strategies;
}
