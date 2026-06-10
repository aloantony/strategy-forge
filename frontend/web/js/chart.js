// chart.js — gráfico de velas monocromo (Lightweight Charts) + niveles de posiciones.

const THEMES = {
  dark: {
    layout: { background: { color: "#0a0a0a" }, textColor: "#8a8a8a" },
    grid: {
      vertLines: { color: "rgba(255,255,255,0.05)" },
      horzLines: { color: "rgba(255,255,255,0.05)" },
    },
    border: "rgba(255,255,255,0.12)",
    up: "#0a0a0a", down: "#f5f5f5", outline: "#f5f5f5",
  },
  light: {
    layout: { background: { color: "#fafafa" }, textColor: "#767676" },
    grid: {
      vertLines: { color: "rgba(0,0,0,0.05)" },
      horzLines: { color: "rgba(0,0,0,0.05)" },
    },
    border: "rgba(0,0,0,0.12)",
    up: "#fafafa", down: "#111111", outline: "#111111",
  },
};

// Compatibilidad v4/v5 de la librería.
function addCandles(chart) {
  if (typeof chart.addCandlestickSeries === "function") {
    return chart.addCandlestickSeries();
  }
  return chart.addSeries(LightweightCharts.CandlestickSeries);
}

export class ChartView {
  constructor(container) {
    this.container = container;
    this.chart = LightweightCharts.createChart(container, {
      autoSize: true,
      timeScale: { timeVisible: true, secondsVisible: false },
      rightPriceScale: { borderVisible: true },
      crosshair: { mode: 0 },
    });
    this.series = addCandles(this.chart);
    this.priceLines = [];
    this.lastTime = 0;
  }

  applyTheme(name) {
    const t = THEMES[name] ?? THEMES.dark;
    this.chart.applyOptions({
      layout: t.layout,
      grid: t.grid,
      timeScale: { borderColor: t.border },
      rightPriceScale: { borderColor: t.border },
    });
    // Velas monocromas: alcista hueca (borde), bajista rellena.
    this.series.applyOptions({
      upColor: t.up,
      downColor: t.down,
      borderUpColor: t.outline,
      borderDownColor: t.outline,
      wickUpColor: t.outline,
      wickDownColor: t.outline,
    });
    this._lineColor = t.outline;
  }

  setCandles(candles) {
    this.series.setData(candles);
    this.lastTime = candles.length ? candles[candles.length - 1].time : 0;
    this.chart.timeScale().fitContent();
  }

  // Merge incremental: solo velas con time >= última conocida.
  mergeCandles(candles) {
    for (const candle of candles) {
      if (candle.time >= this.lastTime) {
        this.series.update(candle);
        this.lastTime = candle.time;
      }
    }
  }

  // Niveles de posiciones abiertas: entrada (sólida), SL y TP (discontinuas).
  setPositionLevels(positions) {
    for (const line of this.priceLines) this.series.removePriceLine(line);
    this.priceLines = [];
    const style = LightweightCharts.LineStyle ?? { Dashed: 2, Solid: 0 };
    for (const pos of positions ?? []) {
      const dir = pos.type ?? (pos.direction === 1 ? "BUY" : pos.direction === -1 ? "SELL" : "");
      this._addLine(pos.price_open, `${dir} ${pos.volume ?? ""}`.trim(), style.Solid ?? 0);
      if (pos.sl > 0) this._addLine(pos.sl, "SL", style.Dashed ?? 2);
      if (pos.tp > 0) this._addLine(pos.tp, "TP", style.Dashed ?? 2);
    }
  }

  _addLine(price, title, lineStyle) {
    if (!(price > 0)) return;
    this.priceLines.push(this.series.createPriceLine({
      price,
      title,
      color: this._lineColor ?? "#f5f5f5",
      lineWidth: 1,
      lineStyle,
      axisLabelVisible: true,
    }));
  }
}

// Mini-gráfico de línea (curva de equity del backtest), mismo lenguaje visual.
export function createEquityChart(container, themeName, points) {
  container.innerHTML = "";
  const t = THEMES[themeName] ?? THEMES.dark;
  const chart = LightweightCharts.createChart(container, {
    autoSize: true,
    layout: t.layout,
    grid: { vertLines: { visible: false }, horzLines: { visible: false } },
    timeScale: { timeVisible: true, borderColor: t.border },
    rightPriceScale: { borderColor: t.border },
  });
  const series = typeof chart.addLineSeries === "function"
    ? chart.addLineSeries({ color: t.outline, lineWidth: 1 })
    : chart.addSeries(LightweightCharts.LineSeries, { color: t.outline, lineWidth: 1 });
  series.setData(points);
  chart.timeScale().fitContent();
  return chart;
}
