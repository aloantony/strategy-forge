// panels/backtest.js — formulario de backtest, métricas, equity y trades.

import { apiGet, apiPost } from "../api.js";
import { createEquityChart } from "../chart.js";

const fmtMoney = (v, digits = 2) =>
  Number.isFinite(Number(v))
    ? Number(v).toLocaleString(undefined, { minimumFractionDigits: digits, maximumFractionDigits: digits })
    : "—";

const fmtDate = (epoch) => {
  if (!epoch) return "—";
  const d = new Date(epoch * 1000);
  return `${d.toLocaleDateString()} ${d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}`;
};

let equityChart = null;

export async function refreshStrategyOptions() {
  const stratSel = document.getElementById("bt-strategy");
  const previous = stratSel.value;
  stratSel.innerHTML = "";
  try {
    for (const strat of await apiGet("/api/strategies")) {
      const opt = document.createElement("option");
      opt.value = strat.key;
      opt.textContent = strat.label ?? strat.key;
      stratSel.appendChild(opt);
    }
  } catch { /* lista vacía: el submit avisará */ }
  if (previous) stratSel.value = previous;
  if (!stratSel.value && stratSel.options.length) stratSel.selectedIndex = 0;
}

export async function initBacktestPanel(meta, getTheme) {
  const form = document.getElementById("bt-form");
  const status = document.getElementById("bt-status");
  const results = document.getElementById("bt-results");
  const runBtn = document.getElementById("bt-run");

  // Poblar selectores
  const sourceSel = document.getElementById("bt-source");
  for (const src of meta.data_sources ?? ["mt5"]) {
    if (src === "dukascopy" && !meta.dukascopy_available) continue;
    const opt = document.createElement("option");
    opt.value = src;
    opt.textContent = src;
    sourceSel.appendChild(opt);
  }
  document.getElementById("bt-symbol").value = meta.symbol_default ?? "";

  const stratSel = document.getElementById("bt-strategy");
  await refreshStrategyOptions();

  // Fechas por defecto: último mes
  const today = new Date();
  const monthAgo = new Date(today.getTime() - 30 * 86400_000);
  document.getElementById("bt-end").value = today.toISOString().slice(0, 10);
  document.getElementById("bt-start").value = monthAgo.toISOString().slice(0, 10);

  form.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    runBtn.disabled = true;
    results.hidden = true;
    status.textContent = "Ejecutando backtest…";
    try {
      const result = await apiPost("/api/backtest/run", {
        strategy_key: stratSel.value,
        symbol: document.getElementById("bt-symbol").value.trim(),
        start_date: document.getElementById("bt-start").value,
        end_date: document.getElementById("bt-end").value,
        initial_balance: Number(document.getElementById("bt-balance").value || 10000),
        data_source: sourceSel.value,
      });
      if (result.status !== "success") {
        status.textContent = `Error: ${result.error || "backtest fallido"}`;
        return;
      }
      status.textContent =
        `${result.closed_trades} operaciones · ${result.symbol} ${result.timeframe}`;
      renderResult(result, getTheme());
      results.hidden = false;
    } catch (err) {
      status.textContent = err.message;
    } finally {
      runBtn.disabled = false;
    }
  });
}

function renderResult(result, theme) {
  const digits = Number.isInteger(result.digits) && result.digits > 0 ? result.digits : 2;

  const cards = [
    ["Retorno", `${result.total_return_pct >= 0 ? "+" : ""}${result.total_return_pct.toFixed(2)}%`],
    ["Profit", fmtMoney(result.total_profit)],
    ["Win rate", `${Number(result.win_rate ?? 0).toFixed(1)}%`],
    ["Max DD", `${Number(result.max_drawdown ?? 0).toFixed(2)}%`],
    ["Profit factor", Number(result.profit_factor ?? 0).toFixed(2)],
    ["Expectancy", fmtMoney(result.expectancy)],
  ];
  const cardsEl = document.getElementById("bt-cards");
  cardsEl.innerHTML = "";
  for (const [label, value] of cards) {
    const card = document.createElement("div");
    card.className = "card";
    const span = document.createElement("span");
    span.textContent = label;
    const strong = document.createElement("strong");
    strong.textContent = value;
    card.append(span, strong);
    cardsEl.appendChild(card);
  }

  // Equity
  const points = (result.equity_curve ?? [])
    .filter((p) => p && p.time)
    .map((p) => ({ time: p.time, value: Number(p.equity ?? p.value ?? 0) }));
  equityChart?.remove();
  equityChart = points.length >= 2
    ? createEquityChart(document.getElementById("bt-equity"), theme, points)
    : null;

  // Trades
  const tbody = document.querySelector("#bt-trades tbody");
  tbody.innerHTML = "";
  (result.trades ?? []).forEach((trade, i) => {
    const row = document.createElement("tr");
    const pnl = Number(trade.profit ?? 0);
    const cells = [
      String(i + 1),
      trade.direction === 1 ? "BUY" : "SELL",
      `${fmtMoney(trade.entry_price, digits)} · ${fmtDate(trade.entry_time)}`,
      `${fmtMoney(trade.exit_price, digits)} · ${fmtDate(trade.exit_time)}`,
      `${pnl >= 0 ? "+" : "−"}${fmtMoney(Math.abs(pnl))}`,
      String(trade.reason ?? ""),
    ];
    cells.forEach((text, idx) => {
      const td = document.createElement("td");
      td.textContent = text;
      if (idx === 4 && pnl < 0) td.className = "neg";
      row.appendChild(td);
    });
    tbody.appendChild(row);
  });
}
