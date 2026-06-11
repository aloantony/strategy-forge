// panels/strategies.js — listado de estrategias + activar/desactivar + acceso al Builder.

import { apiGet, apiPost } from "../api.js";
import { openBuilderEdit } from "./builder.js";

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

    const actions = document.createElement("div");
    actions.className = "actions";

    if (strat.has_config) {
      const edit = document.createElement("button");
      edit.type = "button";
      edit.textContent = "Editar";
      edit.addEventListener("click", () => openBuilderEdit(strat.key));
      actions.appendChild(edit);
    }

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
    actions.appendChild(toggle);

    item.append(main, actions);
    list.appendChild(item);
  }
  return strategies;
}
