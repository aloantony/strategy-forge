// app.js — bootstrap del frontend web: tema, tabs, chart, stream y paneles.

import { apiGet, subscribeStream } from "./api.js";
import { ChartView } from "./chart.js";
import { renderSnapshot } from "./panels/account.js";
import { refreshStrategies } from "./panels/strategies.js";
import { initBacktestPanel, refreshStrategyOptions } from "./panels/backtest.js";
import { initBuilder, openBuilderNew } from "./panels/builder.js";

const POLL_MS = 5000;
const INITIAL_BARS = 1200;

const state = {
  theme: localStorage.getItem("ta-theme") ?? "dark",
  symbol: "",
  timeframe: "M1",
  timeframeMinutes: { M1: 1 },
  chart: null,
  unsubscribe: null,
  pollTimer: 0,
};

// ---------- Tema ----------

function applyTheme(name) {
  state.theme = name;
  document.documentElement.dataset.theme = name;
  localStorage.setItem("ta-theme", name);
  state.chart?.applyTheme(name);
}

// ---------- Velas ----------

function dateStr(d) { return d.toISOString().slice(0, 10); }

function candleParams(barsBack) {
  const minutes = state.timeframeMinutes[state.timeframe] ?? 1;
  const start = new Date(Date.now() - barsBack * minutes * 60_000);
  return {
    symbol: state.symbol,
    timeframe: state.timeframe,
    start: dateStr(start),
    source: "mt5",
    limit: barsBack,
  };
}

async function loadCandles() {
  const statusEl = document.getElementById("chart-status");
  statusEl.textContent = "Cargando velas…";
  try {
    const data = await apiGet("/api/candles", candleParams(INITIAL_BARS));
    state.chart.setCandles(data.candles);
    statusEl.textContent = data.candles.length
      ? "" : "Sin velas para este símbolo/timeframe (¿broker sin datos?).";
  } catch (err) {
    statusEl.textContent = err.message;
  }
}

async function pollCandles() {
  try {
    const data = await apiGet("/api/candles", candleParams(30));
    state.chart.mergeCandles(data.candles);
  } catch { /* siguiente intento en el próximo tick */ }
}

function restartPolling() {
  clearInterval(state.pollTimer);
  state.pollTimer = setInterval(pollCandles, POLL_MS);
}

// ---------- Stream ----------

function restartStream() {
  state.unsubscribe?.();
  state.unsubscribe = subscribeStream({
    symbol: state.symbol,
    magic: 0, // 0 = todas las estrategias
    onSnapshot: (snapshot) => {
      renderSnapshot(snapshot);
      state.chart.setPositionLevels(snapshot.positions);
    },
  });
}

// ---------- Símbolo / timeframe ----------

async function setMarket(symbol, timeframe) {
  state.symbol = symbol;
  state.timeframe = timeframe;
  await loadCandles();
  restartPolling();
  restartStream();
}

// ---------- Tabs ----------

function initTabs() {
  const tabs = document.querySelectorAll("#tabs .tab");
  tabs.forEach((tab) => {
    tab.addEventListener("click", () => {
      tabs.forEach((t) => t.classList.remove("active"));
      document.querySelectorAll(".panel").forEach((p) => p.classList.remove("active"));
      tab.classList.add("active");
      document.getElementById(`panel-${tab.dataset.panel}`).classList.add("active");
    });
  });
}

// ---------- Bootstrap ----------

async function main() {
  applyTheme(state.theme);
  initTabs();

  state.chart = new ChartView(document.getElementById("chart"));
  state.chart.applyTheme(state.theme);

  document.getElementById("theme-toggle").addEventListener("click", () => {
    applyTheme(state.theme === "dark" ? "light" : "dark");
  });

  let meta = { symbol_default: "", timeframes: ["M1"], data_sources: ["mt5"] };
  try {
    meta = await apiGet("/api/meta");
    document.getElementById("acct-broker").textContent =
      (await apiGet("/api/health")).broker.replace("BrokerAdapter", "");
  } catch (err) {
    document.getElementById("chart-status").textContent = err.message;
  }

  // Selectores de mercado
  const tfSelect = document.getElementById("timeframe-select");
  for (const tf of meta.timeframes) {
    const opt = document.createElement("option");
    opt.value = tf;
    opt.textContent = tf;
    tfSelect.appendChild(opt);
  }
  state.timeframeMinutes = meta.timeframe_minutes ?? { M1: 1 };

  const symbolInput = document.getElementById("symbol-input");
  symbolInput.value = meta.symbol_default;
  tfSelect.value = state.timeframe;

  symbolInput.addEventListener("change", () => setMarket(symbolInput.value.trim(), tfSelect.value));
  tfSelect.addEventListener("change", () => setMarket(symbolInput.value.trim(), tfSelect.value));

  refreshStrategies();
  initBacktestPanel(meta, () => state.theme);

  initBuilder();
  document.getElementById("strategy-new").addEventListener("click", openBuilderNew);
  document.addEventListener("strategies-changed", () => {
    refreshStrategies();
    refreshStrategyOptions();
  });

  await setMarket(meta.symbol_default, state.timeframe);
}

main();
