// panels/account.js — cuenta, estado de mercado y posiciones (snapshots del WS).

const fmtMoney = (v) =>
  Number.isFinite(Number(v))
    ? Number(v).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })
    : "—";

export function renderSnapshot(snapshot) {
  const account = snapshot.account;
  document.getElementById("acct-balance").textContent =
    account ? `${fmtMoney(account.balance)} ${account.currency ?? ""}` : "—";
  document.getElementById("acct-equity").textContent =
    account ? fmtMoney(account.equity) : "—";

  const market = snapshot.market ?? {};
  const badge = document.getElementById("market-badge");
  badge.classList.toggle("open", !!market.open);
  badge.title = market.detail ?? "";
  document.getElementById("market-text").textContent =
    market.open ? "Mercado abierto" : "Mercado cerrado";

  renderPositions(snapshot.positions ?? []);
}

function renderPositions(positions) {
  const list = document.getElementById("positions-list");
  const empty = document.getElementById("positions-empty");
  empty.hidden = positions.length > 0;
  list.innerHTML = "";

  for (const pos of positions) {
    // Normaliza MT5 ({type, profit, time_open}) y paper ({direction, time}).
    const dir = pos.type ?? (pos.direction === 1 ? "BUY" : pos.direction === -1 ? "SELL" : "—");
    const profit = Number(pos.profit ?? 0);

    const item = document.createElement("div");
    item.className = "item";

    const main = document.createElement("div");
    main.className = "main";
    const title = document.createElement("div");
    title.className = "title";
    title.textContent = `${dir} ${pos.volume ?? ""} @ ${fmtMoney(pos.price_open)}`;
    const sub = document.createElement("div");
    sub.className = "sub";
    const slTp = [pos.sl > 0 ? `SL ${fmtMoney(pos.sl)}` : null,
                  pos.tp > 0 ? `TP ${fmtMoney(pos.tp)}` : null]
      .filter(Boolean).join(" · ");
    sub.textContent = [`#${pos.ticket ?? "—"}`, pos.magic ? `magic ${pos.magic}` : null, slTp]
      .filter(Boolean).join(" · ");
    main.append(title, sub);

    const num = document.createElement("div");
    num.className = "num" + (profit < 0 ? " neg" : "");
    num.textContent = `${profit >= 0 ? "+" : "−"}${fmtMoney(Math.abs(profit))}`;

    item.append(main, num);
    list.appendChild(item);
  }
}
