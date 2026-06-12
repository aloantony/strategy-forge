// panels/builder.js — wizard del Strategy Builder (crear/editar estrategias).
//
// Diseño UX propio: pasos guiados, condiciones como frases con etiquetas humanas
// (nunca nombres de columna crudos) y resumen en lenguaje natural. Cada condición
// puede vivir en su propio timeframe ("En H4: RSI(14) es menor que 30"): si todas
// usan el timeframe de la estrategia se genera una estrategia clásica (v1); si no,
// una multi-timeframe (modo reglas). Los bloques (riesgo por tramos) admiten
// dirección larga o corta. El modelo interno es el config del generador.

import { apiGet, apiPost, apiPut, apiDelete } from "../api.js";

let meta = null;
let uidSeq = 1;

const S = {
  isNew: true,
  editingKey: null,
  step: 0,
  mode: "rules", // "rules" | "blocks"
  display_name: "",
  description: "",
  timeframe: "M5", // primario
  instances: [], // {uid, id, params, tf: null|label} (null = timeframe primario)
  buyTree: null,
  sellTree: null,
  extras: { pyramiding: false, dynamic_sizing: false },
  customFields: [], // {key, type, value}
  blocks: [],
  validation: null,
};

const group = (type = "AND", children = []) => ({ type, children });
const cond = (left = "close", op = ">", right = 0) => ({ type: "condition", left, op, right });

// ---------- Refs con timeframe ----------

const primaryTf = () => S.timeframe;
const isQualified = (ref) =>
  typeof ref === "string" && ref.includes(".") && meta.timeframes.includes(ref.split(".")[0]);
const refTf = (ref) => (isQualified(ref) ? ref.split(".")[0] : primaryTf());
const refCol = (ref) => (isQualified(ref) ? ref.split(".").slice(1).join(".") : ref);
const makeRef = (col, tf) => (tf === primaryTf() ? col : `${tf}.${col}`);
const instTf = (inst) => inst.tf ?? primaryTf();

// ---------- Catálogo / columnas ----------

const indicatorDef = (id) => meta.indicators.find((i) => i.id === id);

function realizeColumns(inst) {
  const def = indicatorDef(inst.id);
  return def.columns.map((c) => ({
    column: c.template.replace(/\{(\w+)\}/g, (_, k) => inst.params[k]),
    label: c.label.replace(/\{(\w+)\}/g, (_, k) => inst.params[k]),
  }));
}

// Operandos disponibles para un timeframe concreto.
function registryFor(tf, extraColumns = []) {
  const out = meta.base_columns.map((c) => ({
    ref: makeRef(c.column, tf), column: c.column, label: c.label, group: c.group,
  }));
  for (const col of extraColumns) {
    out.push({ ref: makeRef(col.column, tf), column: col.column, label: col.label, group: col.group });
  }
  for (const inst of S.instances) {
    if (instTf(inst) !== tf) continue;
    const def = indicatorDef(inst.id);
    for (const col of realizeColumns(inst)) {
      out.push({ ref: makeRef(col.column, tf), column: col.column, label: col.label, group: def.label, uid: inst.uid });
    }
  }
  return out;
}

function columnLabel(ref) {
  const tf = refTf(ref);
  const col = refCol(ref);
  let label = meta.base_columns.find((c) => c.column === col)?.label;
  if (!label) {
    for (const inst of S.instances) {
      const hit = realizeColumns(inst).find((c) => c.column === col);
      if (hit) { label = hit.label; break; }
    }
  }
  if (!label) label = mtfColumnLabel(col) ?? col;
  return tf === primaryTf() ? label : `${tf} · ${label}`;
}

function mtfColumnLabel(col) {
  for (const c of meta.mtf.column_labels ?? []) {
    const re = new RegExp("^" + c.template.replace(/\{(\w+)\}/g, "(\\d+)") + "$");
    const m = col.match(re);
    if (m) return c.label.replace(/\{(\w+)\}/g, m[1]);
  }
  return null;
}

const opLabel = (op) => meta.operators.find((o) => o.op === op)?.label ?? op;

function addInstance(id, params = null, tf = null) {
  const def = indicatorDef(id);
  const values = {};
  for (const p of def.params) values[p.key] = params?.[p.key] ?? p.default;
  const existing = S.instances.find(
    (i) => i.id === id && (i.tf ?? null) === (tf ?? null) && JSON.stringify(i.params) === JSON.stringify(values)
  );
  if (existing) return existing;
  const inst = { uid: uidSeq++, id, params: values, tf };
  S.instances.push(inst);
  return inst;
}

function renameColumnsEverywhere(mapping) {
  const fix = (ref) => {
    if (typeof ref !== "string") return ref;
    const col = refCol(ref);
    if (mapping[col] === undefined) return ref;
    return makeRef(mapping[col], refTf(ref));
  };
  const walk = (node) => {
    if (!node) return;
    if (node.type === "condition") {
      node.left = fix(node.left);
      node.right = fix(node.right);
      return;
    }
    (node.children || []).forEach(walk);
  };
  walk(S.buyTree);
  walk(S.sellTree);
  for (const b of S.blocks) {
    if (b.entryCustom) walk(b.entryCustom);
    if (b.dirCustom) walk(b.dirCustom);
  }
  for (const f of S.customFields) {
    if (f.type === "column" && mapping[f.value] !== undefined) f.value = mapping[f.value];
  }
}

function setInstanceParam(inst, key, value) {
  const before = realizeColumns(inst).map((c) => c.column);
  inst.params[key] = value;
  const after = realizeColumns(inst).map((c) => c.column);
  const mapping = {};
  before.forEach((old, i) => { mapping[old] = after[i]; });
  renameColumnsEverywhere(mapping);
}

function removeInstance(inst) {
  S.instances = S.instances.filter((i) => i.uid !== inst.uid);
}

function referencedColumns() {
  const used = new Set();
  const add = (ref) => { if (typeof ref === "string") used.add(`${refTf(ref)}.${refCol(ref)}`); };
  const walk = (node) => {
    if (!node) return;
    if (node.type === "condition") { add(node.left); add(node.right); return; }
    (node.children || []).forEach(walk);
  };
  walk(S.buyTree);
  walk(S.sellTree);
  for (const b of S.blocks) { walk(b.entryCustom); walk(b.dirCustom); }
  for (const f of S.customFields) if (f.type === "column") add(f.value);
  return used;
}

function instanceInUse(inst) {
  const used = referencedColumns();
  const tf = instTf(inst);
  return realizeColumns(inst).some((c) => used.has(`${tf}.${c.column}`));
}

function isMultiTF() {
  if (S.instances.some((i) => i.tf && i.tf !== primaryTf())) return true;
  let found = false;
  const walk = (node) => {
    if (!node || found) return;
    if (node.type === "condition") {
      if (isQualified(node.left) && refTf(node.left) !== primaryTf()) found = true;
      if (typeof node.right === "string" && isQualified(node.right) && refTf(node.right) !== primaryTf()) found = true;
      return;
    }
    (node.children || []).forEach(walk);
  };
  walk(S.buyTree);
  walk(S.sellTree);
  return found;
}

// ---------- Resumen en lenguaje natural ----------

function describeCondition(c) {
  const right = typeof c.right === "number" ? String(c.right) : columnLabel(c.right);
  return `${columnLabel(c.left)} ${opLabel(c.op)} ${right}`;
}

function describeTree(node, depth = 0) {
  if (!node) return "—";
  if (node.type === "condition") return describeCondition(node);
  const joiner = node.type === "AND" ? " y " : " o ";
  const parts = (node.children || []).map((ch) => describeTree(ch, depth + 1));
  if (!parts.length) return "—";
  const text = parts.join(joiner);
  return depth > 0 ? `(${text})` : text;
}

function describeBlock(b) {
  const short = b.direction === "short";
  const confirms = b.confirms.length ? ` confirmado en ${b.confirms.join(" y ")}` : "";
  const tiers = parseRiskTiers(b.riskTiersText).map((r) => `${(r * 100).toFixed(2).replace(/\.?0+$/, "")}%`);
  const entry = b.entryCustom
    ? describeCondition(b.entryCustom)
    : `cruce ${short ? "bajista" : "alcista"} del Vortex(${b.vortex_period}) en ${b.trigger}`;
  return `Bloque «${b.id}» (${short ? "corto" : "largo"}): ${short ? "vende" : "compra"} con ${entry}${confirms}; ` +
    `riesgo por entrada: ${tiers.join(" → ") || "—"}; SL a ${b.sl_atr_mult}×ATR(${b.atr_period}), TP ${b.tp_rr}:1` +
    (b.parent ? `; solo si «${b.parent}» acompaña` : "");
}

// ---------- Validación local ----------

function localErrors() {
  const errs = [];
  if (!S.display_name.trim()) errs.push("Ponle un nombre a la estrategia (paso 1).");
  if (S.mode === "rules") {
    for (const [label, tree] of [["compra", S.buyTree], ["venta", S.sellTree]]) {
      const walk = (node, depth) => {
        if (node.type !== "condition") {
          if (depth > 4) errs.push(`La regla de ${label} supera los 4 niveles de grupos.`);
          if ((node.children || []).length < 2) {
            errs.push(`En la regla de ${label} hay un grupo con menos de 2 condiciones.`);
          }
          (node.children || []).forEach((ch) => { if (ch.type !== "condition") walk(ch, depth + 1); });
        }
      };
      walk(tree, 0);
    }
  } else {
    if (!S.blocks.length) errs.push("Añade al menos un bloque (paso 2).");
    for (const b of S.blocks) {
      if (!/^[A-Za-z][A-Za-z0-9_]*$/.test(b.id)) errs.push(`Id de bloque inválido: «${b.id}» (letras/números/_).`);
      if (!parseRiskTiers(b.riskTiersText).length) errs.push(`El bloque «${b.id}» necesita al menos un % de riesgo.`);
    }
  }
  return errs;
}

// ---------- Construcción del config ----------

function parseRiskTiers(text) {
  return String(text || "")
    .split(",")
    .map((s) => parseFloat(s.trim().replace(",", ".")))
    .filter((n) => Number.isFinite(n) && n >= 0)
    .map((pct) => pct / 100);
}

function buildConfig() {
  if (S.mode === "blocks") {
    return {
      mode: "multi_timeframe",
      display_name: S.display_name.trim(),
      description: S.description.trim(),
      primary_timeframe: S.timeframe,
      indicators: S.instances.map((inst) => ({
        id: inst.id, params: { ...inst.params }, timeframe: instTf(inst),
      })),
      blocks: S.blocks.map((b) => {
        const block = {
          id: b.id,
          direction: b.direction,
          trigger_timeframe: b.trigger,
          confirm_timeframes: [...b.confirms],
          atr_period: Number(b.atr_period) || 14,
          vortex_period: Number(b.vortex_period) || 14,
          risk_tiers: parseRiskTiers(b.riskTiersText),
          sl_atr_mult: Number(b.sl_atr_mult) || 1.5,
          tp_rr: Number(b.tp_rr) || 2.0,
          pyramid_atr_mult: Number(b.pyramid_atr_mult) || 0.5,
        };
        if (b.max_entries) block.max_entries = Number(b.max_entries);
        if (b.parent) block.parent_block = b.parent;
        if (b.entryCustom) block.entry_condition = b.entryCustom;
        else if (b.entryRaw) block.entry_condition = b.entryRaw;
        if (b.dirCustom) block.direction_condition = b.dirCustom;
        else if (b.dirRaw) block.direction_condition = b.dirRaw;
        return block;
      }),
    };
  }

  if (isMultiTF()) {
    // Modo reglas multi-timeframe (los extras avanzados son solo de v1).
    return {
      mode: "multi_timeframe",
      display_name: S.display_name.trim(),
      description: S.description.trim(),
      primary_timeframe: S.timeframe,
      indicators: S.instances.map((inst) => ({
        id: inst.id, params: { ...inst.params }, timeframe: instTf(inst),
      })),
      buy_condition: S.buyTree,
      sell_condition: S.sellTree,
    };
  }

  // v1 clásico (un timeframe)
  const payload = [];
  if (S.extras.pyramiding || S.extras.dynamic_sizing) {
    const atr = S.instances.find((i) => i.id === "ATR") ?? addInstance("ATR");
    payload.push({ key: "pyramiding", type: "literal", value: true });
    payload.push({ key: "atr_value", type: "column", value: realizeColumns(atr)[0].column });
  }
  if (S.extras.dynamic_sizing) {
    const vr = S.instances.find((i) => i.id === "VOLUME_RATIO") ?? addInstance("VOLUME_RATIO");
    payload.push({ key: "dynamic_sizing", type: "literal", value: true });
    payload.push({ key: "volume_ratio", type: "column", value: realizeColumns(vr)[0].column });
  }
  const reserved = new Set(payload.map((f) => f.key));
  for (const f of S.customFields) {
    if (!f.key || reserved.has(f.key)) continue;
    payload.push({ key: f.key, type: f.type, value: f.type === "literal" ? parseLiteral(f.value) : f.value });
  }

  return {
    display_name: S.display_name.trim(),
    description: S.description.trim(),
    timeframe: S.timeframe,
    indicators: S.instances.map((inst) => ({
      id: inst.id,
      params: { ...inst.params },
      columns: realizeColumns(inst).map((c) => c.column),
      pre_computed: !!indicatorDef(inst.id).pre_computed,
    })),
    buy_condition: S.buyTree,
    sell_condition: S.sellTree,
    payload_extra_fields: payload,
  };
}

function parseLiteral(raw) {
  const t = String(raw ?? "").trim();
  if (t === "true") return true;
  if (t === "false") return false;
  const n = Number(t);
  return Number.isFinite(n) && t !== "" ? n : t;
}

// ---------- Carga de una config existente ----------

function loadFromConfig(cfg) {
  S.display_name = cfg.display_name ?? "";
  S.description = cfg.description ?? "";
  const isMtf = cfg.schema_version === 2 || ["multi_timeframe", "mtf"].includes(String(cfg.mode || ""));

  if (isMtf && (cfg.blocks || []).length) {
    S.mode = "blocks";
    S.timeframe = cfg.primary_timeframe || cfg.timeframe || "M1";
    S.instances = [];
    S.blocks = (cfg.blocks || []).map((b) => ({
      id: b.id,
      direction: b.direction === "short" ? "short" : "long",
      trigger: b.trigger_timeframe || S.timeframe,
      confirms: [...(b.confirm_timeframes || [])],
      atr_period: b.atr_period ?? 14,
      vortex_period: b.vortex_period ?? 14,
      riskTiersText: (b.tiers || []).map((t) => +(t.risk_pct * 100).toFixed(4)).join(", ") ||
        (b.risk_tiers || []).map((r) => +(r * 100).toFixed(4)).join(", "),
      sl_atr_mult: b.sl_atr_mult ?? 1.5,
      tp_rr: b.tp_rr ?? 2.0,
      pyramid_atr_mult: b.pyramid_atr_mult ?? 0.5,
      max_entries: b.max_entries ?? "",
      parent: b.parent_block ?? "",
      entryCustom: null,
      dirCustom: null,
      entryRaw: b.entry_condition ?? null,
      dirRaw: b.direction_condition ?? null,
    }));
    return;
  }

  S.mode = "rules";
  S.timeframe = isMtf ? (cfg.primary_timeframe || "M1") : (cfg.timeframe || "M5");
  S.instances = (cfg.indicators || []).map((ind) => ({
    uid: uidSeq++,
    id: ind.id,
    params: { ...(ind.params || {}) },
    tf: ind.timeframe && ind.timeframe !== S.timeframe ? ind.timeframe : null,
  }));
  S.buyTree = normalizeTree(cfg.buy_condition);
  S.sellTree = normalizeTree(cfg.sell_condition);

  S.extras = { pyramiding: false, dynamic_sizing: false };
  S.customFields = [];
  const known = new Set(["pyramiding", "atr_value", "dynamic_sizing", "volume_ratio"]);
  for (const f of cfg.payload_extra_fields || []) {
    if (f.key === "pyramiding" && f.value === true) S.extras.pyramiding = true;
    else if (f.key === "dynamic_sizing" && f.value === true) S.extras.dynamic_sizing = true;
    else if (!known.has(f.key)) {
      S.customFields.push({ key: f.key, type: f.type, value: String(f.value) });
    }
  }
}

function normalizeTree(node) {
  if (!node) return group("AND", [cond(), cond("close", "<", 0)]);
  if (node.type === "condition") node = group("AND", [node, cond()]);
  return unqualifyPrimary(node);
}

// El backend guarda refs cualificadas también para el primario ("M1.close");
// internamente "sin prefijo" significa primario, así que se normaliza al cargar.
function unqualifyPrimary(node) {
  if (!node) return node;
  if (node.type === "condition") {
    if (isQualified(node.left) && refTf(node.left) === primaryTf()) node.left = refCol(node.left);
    if (typeof node.right === "string" && isQualified(node.right) && refTf(node.right) === primaryTf()) {
      node.right = refCol(node.right);
    }
    return node;
  }
  (node.children || []).forEach(unqualifyPrimary);
  return node;
}

// ---------- Render ----------

const $ = (sel) => document.querySelector(sel);
const el = (tag, cls, text) => {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text !== undefined) n.textContent = text;
  return n;
};

function stepsFor() {
  return S.mode === "blocks"
    ? ["Identidad", "Bloques", "Revisión"]
    : ["Identidad", "Regla de compra", "Regla de venta", "Revisión"];
}

function render() {
  const steps = stepsFor();
  $("#sb-title").textContent = S.isNew ? "Nueva estrategia" : `Editar · ${S.display_name || ""}`;

  const nav = $("#sb-steps");
  nav.innerHTML = "";
  steps.forEach((label, i) => {
    const b = el("button", "sb-step-dot" + (i === S.step ? " active" : "") + (i < S.step ? " done" : ""));
    b.type = "button";
    b.append(el("span", "n", String(i + 1)), el("span", "t", label));
    b.addEventListener("click", () => { if (i < S.step) { S.step = i; render(); } });
    nav.appendChild(b);
  });

  $("#sb-back").style.visibility = S.step === 0 ? "hidden" : "visible";
  $("#sb-next").textContent = S.step === steps.length - 1 ? "Guardar estrategia" : "Siguiente";
  $("#sb-delete").hidden = S.isNew;
  setError("");

  const host = $("#sb-step");
  host.innerHTML = "";
  const viewName = steps[S.step];
  if (viewName === "Identidad") host.appendChild(viewIdentity());
  else if (viewName === "Regla de compra") host.appendChild(viewRule("buy"));
  else if (viewName === "Regla de venta") host.appendChild(viewRule("sell"));
  else if (viewName === "Bloques") host.appendChild(viewBlocks());
  else host.appendChild(viewReview());
  $("#sb-body").scrollTop = 0;
}

const setError = (msg) => { $("#sb-error").textContent = msg || ""; };

// ----- Paso 1: identidad -----

function viewIdentity() {
  const root = el("div", "sb-view");
  root.appendChild(el("h2", "sb-q", "¿Cómo se llama tu estrategia?"));

  const nameField = el("label", "field");
  nameField.append(el("span", "", "Nombre"));
  const nameInput = el("input");
  nameInput.type = "text";
  nameInput.value = S.display_name;
  nameInput.placeholder = "Mi estrategia de tendencia";
  nameField.appendChild(nameInput);
  const slug = el("p", "hint");
  const updateSlug = () => {
    slug.textContent = nameInput.value.trim() ? `Identificador: ${slugify(nameInput.value)}` : "";
  };
  nameInput.addEventListener("input", () => { S.display_name = nameInput.value; updateSlug(); });
  updateSlug();

  const descField = el("label", "field");
  descField.append(el("span", "", "Descripción (opcional)"));
  const desc = el("textarea");
  desc.rows = 2;
  desc.value = S.description;
  desc.addEventListener("change", () => { S.description = desc.value; });
  descField.appendChild(desc);

  root.append(nameField, slug, descField);

  root.appendChild(el("h2", "sb-q", "¿Timeframe principal?"));
  root.appendChild(el("p", "hint", "Las condiciones pueden mirar otros timeframes; este es el de referencia."));
  root.appendChild(chips(meta.timeframes, () => S.timeframe, (tf) => { S.timeframe = tf; render(); }));

  root.appendChild(el("h2", "sb-q", "¿Qué tipo de estrategia es?"));
  const cards = el("div", "sb-cards");
  const mk = (mode, title, text) => {
    const c = el("button", "sb-card" + (S.mode === mode ? " active" : ""));
    c.type = "button";
    c.append(el("strong", "", title), el("span", "", text));
    c.addEventListener("click", () => {
      if (S.mode !== mode) {
        S.mode = mode;
        if (mode === "blocks" && !S.blocks.length) S.blocks.push(newBlock());
        render();
      }
    });
    return c;
  };
  cards.append(
    mk("rules", "Reglas", "Condiciones de compra y venta con indicadores, en uno o varios timeframes. SL/TP fijos."),
    mk("blocks", "Bloques", "Entradas por tramos de riesgo con SL/TP en ATRs y piramidación, en largo o en corto."),
  );
  root.appendChild(cards);
  return root;
}

function slugify(text) {
  let s = (text || "").toLowerCase().replace(/[^a-z0-9_]/g, "_").replace(/_+/g, "_").replace(/^_|_$/g, "");
  if (!s || /^\d/.test(s)) s = "strategy_" + s;
  return s;
}

function chips(values, getActive, onPick, { multi = false } = {}) {
  const wrap = el("div", "chips");
  for (const v of values) {
    const active = multi ? getActive().includes(v) : getActive() === v;
    const c = el("button", "chip" + (active ? " active" : ""), v);
    c.type = "button";
    c.addEventListener("click", () => onPick(v));
    wrap.appendChild(c);
  }
  return wrap;
}

// ----- Reglas (modo rules) -----

function viewRule(kind) {
  const isBuy = kind === "buy";
  const tree = isBuy ? S.buyTree : S.sellTree;
  const root = el("div", "sb-view");
  root.appendChild(el("h2", "sb-q", isBuy ? "¿Cuándo debe comprar?" : "¿Cuándo debe vender o cerrar?"));
  root.appendChild(el("p", "hint",
    "Construye la regla como frases. Cada condición puede mirar otro timeframe con el selector «En…». " +
    "Si eliges un indicador nuevo, se añade solo."));

  root.appendChild(renderGroup(tree, 0, null));

  if (S.instances.length) {
    root.appendChild(el("h3", "panel-subtitle", "Indicadores en uso"));
    const strip = el("div", "sb-instances");
    for (const inst of S.instances) strip.appendChild(renderInstanceChip(inst));
    root.appendChild(strip);
  }

  const sum = el("div", "sb-summary");
  sum.append(el("span", "", isBuy ? "Compra cuando" : "Vende cuando"), el("p", "", describeTree(tree)));
  if (isMultiTF()) sum.appendChild(el("p", "hint-inline", "Estrategia multi-timeframe (modo reglas)."));
  root.appendChild(sum);
  return root;
}

function renderInstanceChip(inst) {
  const def = indicatorDef(inst.id);
  const chip = el("div", "sb-instance");
  const tfTag = instTf(inst) !== primaryTf() ? `${instTf(inst)} · ` : "";
  chip.appendChild(el("span", "name", tfTag + def.label.replace(/\s*\(.*\)$/, "")));
  for (const p of def.params) {
    const input = el("input", "param");
    input.type = "number";
    input.min = p.min; input.max = p.max; input.step = p.step;
    input.value = inst.params[p.key];
    input.title = p.label;
    input.addEventListener("change", () => {
      const v = p.type === "int" ? parseInt(input.value, 10) : parseFloat(input.value);
      if (Number.isFinite(v)) { setInstanceParam(inst, p.key, v); render(); }
    });
    chip.appendChild(input);
  }
  if (!instanceInUse(inst)) {
    const rm = el("button", "ghost", "✕");
    rm.type = "button";
    rm.title = "Quitar (no se usa en ninguna condición)";
    rm.addEventListener("click", () => { removeInstance(inst); render(); });
    chip.appendChild(rm);
  }
  return chip;
}

function renderGroup(node, depth, parent) {
  const box = el("div", "sb-group");
  const head = el("div", "sb-group-head");

  const toggle = el("button", "sb-anyall", node.type === "AND" ? "TODAS" : "CUALQUIERA");
  toggle.type = "button";
  toggle.title = "Alternar entre exigir todas las condiciones o cualquiera de ellas";
  toggle.addEventListener("click", () => { node.type = node.type === "AND" ? "OR" : "AND"; render(); });
  head.append(toggle, el("span", "hint-inline", "de las siguientes:"));
  head.appendChild(el("span", "spacer"));

  const addCond = el("button", "ghost small", "+ condición");
  addCond.type = "button";
  addCond.addEventListener("click", () => { node.children.push(cond()); render(); });
  head.appendChild(addCond);

  if (depth < 3) {
    const addGroup = el("button", "ghost small", "+ grupo");
    addGroup.type = "button";
    addGroup.addEventListener("click", () => { node.children.push(group("OR", [cond(), cond()])); render(); });
    head.appendChild(addGroup);
  }
  if (parent) {
    const rm = el("button", "ghost small", "✕");
    rm.type = "button";
    rm.addEventListener("click", () => {
      parent.children = parent.children.filter((c) => c !== node);
      render();
    });
    head.appendChild(rm);
  }
  box.appendChild(head);

  const body = el("div", "sb-group-body");
  for (const child of node.children) {
    body.appendChild(child.type === "condition" ? renderCondition(child, node) : renderGroup(child, depth + 1, node));
  }
  if (!node.children.length) body.appendChild(el("p", "hint", "Grupo vacío — añade condiciones."));
  box.appendChild(body);
  return box;
}

function tfSelect(value, onChange) {
  const sel = el("select", "sb-tf");
  sel.title = "Timeframe de esta condición";
  for (const tf of meta.timeframes) {
    const opt = el("option", "", tf === primaryTf() ? `En ${tf}` : `En ${tf}`);
    opt.value = tf;
    sel.appendChild(opt);
  }
  sel.value = value;
  sel.addEventListener("change", () => { onChange(sel.value); });
  return sel;
}

function operandSelect(value, rowTf, onChange, extraColumns = []) {
  const sel = el("select", "sb-operand");
  const groups = new Map();
  for (const c of registryFor(rowTf, extraColumns)) {
    if (!groups.has(c.group)) groups.set(c.group, []);
    groups.get(c.group).push(c);
  }
  for (const [g, cols] of groups) {
    const og = el("optgroup");
    og.label = g;
    for (const c of cols) {
      const opt = el("option", "", c.label);
      opt.value = c.ref;
      og.appendChild(opt);
    }
    sel.appendChild(og);
  }
  const addGroup = el("optgroup");
  addGroup.label = "➕ Añadir indicador…";
  for (const ind of meta.indicators) {
    if (rowTf !== primaryTf() && ind.pre_computed) continue; // pre-computados: solo TF base
    const opt = el("option", "", ind.label);
    opt.value = `__add__:${ind.id}`;
    addGroup.appendChild(opt);
  }
  sel.appendChild(addGroup);
  sel.value = value;
  if (sel.value !== value) sel.value = makeRef("close", rowTf);
  sel.addEventListener("change", () => {
    let v = sel.value;
    if (v.startsWith("__add__:")) {
      const inst = addInstance(v.slice(8), null, rowTf === primaryTf() ? null : rowTf);
      v = makeRef(realizeColumns(inst)[0].column, rowTf);
    }
    onChange(v);
    render();
  });
  return sel;
}

function migrateConditionTf(node, newTf) {
  const move = (ref) => {
    if (typeof ref !== "string") return ref;
    const col = refCol(ref);
    // Si la columna pertenece a un indicador, asegura una instancia en el nuevo TF.
    for (const inst of S.instances) {
      const hit = realizeColumns(inst).find((c) => c.column === col);
      if (hit) {
        const def = indicatorDef(inst.id);
        if (newTf !== primaryTf() && def.pre_computed) return makeRef("close", newTf);
        addInstance(inst.id, inst.params, newTf === primaryTf() ? null : newTf);
        break;
      }
    }
    return makeRef(col, newTf);
  };
  node.left = move(node.left);
  if (typeof node.right === "string") node.right = move(node.right);
}

function renderCondition(node, parent, extraColumns = []) {
  const row = el("div", "sb-row");
  const rowTf = refTf(node.left);

  row.appendChild(tfSelect(rowTf, (tf) => { migrateConditionTf(node, tf); render(); }));
  row.appendChild(operandSelect(node.left, rowTf, (v) => { node.left = v; }, extraColumns));

  const op = el("select", "sb-op");
  for (const o of meta.operators) {
    const opt = el("option", "", o.label);
    opt.value = o.op;
    op.appendChild(opt);
  }
  op.value = node.op;
  op.addEventListener("change", () => { node.op = op.value; render(); });
  row.appendChild(op);

  const isNumber = typeof node.right === "number";
  if (isNumber) {
    const num = el("input", "sb-num");
    num.type = "number";
    num.step = "any";
    num.value = node.right;
    num.addEventListener("change", () => {
      const v = parseFloat(num.value);
      node.right = Number.isFinite(v) ? v : 0;
    });
    row.appendChild(num);
  } else {
    row.appendChild(operandSelect(node.right, refTf(node.right), (v) => { node.right = v; }, extraColumns));
  }

  const swap = el("button", "ghost small", isNumber ? "↔ indicador" : "↔ valor");
  swap.type = "button";
  swap.title = "Comparar contra un valor fijo o contra otro indicador";
  swap.addEventListener("click", () => {
    node.right = isNumber ? makeRef("close", rowTf) : 0;
    render();
  });
  row.appendChild(swap);

  const rm = el("button", "ghost small", "✕");
  rm.type = "button";
  rm.addEventListener("click", () => {
    parent.children = parent.children.filter((c) => c !== node);
    render();
  });
  row.appendChild(rm);
  return row;
}

// ----- Bloques -----

function newBlock() {
  const d = meta.mtf.block_defaults;
  return {
    id: `bloque_${S.blocks.length + 1}`,
    direction: "long",
    trigger: S.timeframe,
    confirms: [],
    atr_period: d.atr_period,
    vortex_period: d.vortex_period,
    riskTiersText: d.risk_tiers.map((r) => +(r * 100).toFixed(4)).join(", "),
    sl_atr_mult: d.sl_atr_mult,
    tp_rr: d.tp_rr,
    pyramid_atr_mult: d.pyramid_atr_mult,
    max_entries: "",
    parent: "",
    entryCustom: null,
    dirCustom: null,
    entryRaw: null,
    dirRaw: null,
  };
}

function blockExtraColumns(b) {
  const out = [];
  const labels = meta.mtf.column_labels ?? [];
  for (const tpl of labels) {
    const period = tpl.template.startsWith("atr") ? b.atr_period : b.vortex_period;
    out.push({
      column: tpl.template.replace(/\{period\}/g, period),
      label: tpl.label.replace(/\{period\}/g, period),
      group: "Indicadores del bloque",
    });
  }
  return out;
}

function viewBlocks() {
  const root = el("div", "sb-view");
  root.appendChild(el("h2", "sb-q", "Bloques de entrada"));
  root.appendChild(el("p", "hint",
    "Cada bloque entra al mercado en su dirección cuando se cumple su condición de entrada " +
    "(por defecto, cruce del Vortex), confirmando en los timeframes extra, y reparte el riesgo en tramos."));

  S.blocks.forEach((b, i) => root.appendChild(renderBlock(b, i)));

  const add = el("button", "ghost", "+ Añadir bloque");
  add.type = "button";
  add.style.marginTop = "12px";
  add.addEventListener("click", () => { S.blocks.push(newBlock()); render(); });
  root.appendChild(add);

  const sum = el("div", "sb-summary");
  sum.append(el("span", "", "Resumen"));
  for (const b of S.blocks) sum.appendChild(el("p", "", describeBlock(b)));
  root.appendChild(sum);
  return root;
}

function renderBlock(b, index) {
  const card = el("div", "sb-block");
  const head = el("div", "sb-block-head");
  const idInput = el("input", "sb-block-id");
  idInput.type = "text";
  idInput.value = b.id;
  idInput.title = "Identificador del bloque (letras, números, _)";
  idInput.addEventListener("change", () => { b.id = idInput.value.trim(); render(); });
  head.appendChild(idInput);

  const dir = el("button", "sb-dir" + (b.direction === "short" ? " short" : ""),
    b.direction === "short" ? "CORTO ↓" : "LARGO ↑");
  dir.type = "button";
  dir.title = "Dirección del bloque";
  dir.addEventListener("click", () => {
    b.direction = b.direction === "short" ? "long" : "short";
    render();
  });
  head.appendChild(dir);

  head.appendChild(el("span", "spacer"));
  if (S.blocks.length > 1) {
    const rm = el("button", "ghost small", "✕ quitar");
    rm.type = "button";
    rm.addEventListener("click", () => { S.blocks.splice(index, 1); render(); });
    head.appendChild(rm);
  }
  card.appendChild(head);

  const fld = (label, node) => {
    const f = el("label", "field");
    f.append(el("span", "", label), node);
    return f;
  };
  const num = (get, set, step = "any", min = null) => {
    const i = el("input");
    i.type = "number"; i.step = step; if (min !== null) i.min = min;
    i.value = get();
    i.addEventListener("change", () => { set(i.value); });
    return i;
  };

  card.appendChild(fld("Timeframe disparador", chips(meta.timeframes, () => b.trigger, (tf) => { b.trigger = tf; render(); })));
  card.appendChild(fld("Confirmar también en (opcional)", chips(
    meta.timeframes.filter((tf) => tf !== b.trigger),
    () => b.confirms,
    (tf) => {
      b.confirms = b.confirms.includes(tf) ? b.confirms.filter((x) => x !== tf) : [...b.confirms, tf];
      render();
    },
    { multi: true },
  )));

  const grid = el("div", "sb-grid3");
  grid.append(
    fld("% riesgo por entrada (coma = tramos)", (() => {
      const i = el("input");
      i.type = "text";
      i.value = b.riskTiersText;
      i.placeholder = "1, 0.5";
      i.addEventListener("change", () => { b.riskTiersText = i.value; render(); });
      return i;
    })()),
    fld("SL en ATRs", num(() => b.sl_atr_mult, (v) => { b.sl_atr_mult = v; }, "0.1", "0.1")),
    fld("TP (ratio beneficio:riesgo)", num(() => b.tp_rr, (v) => { b.tp_rr = v; }, "0.1", "0.1")),
    fld("Período ATR", num(() => b.atr_period, (v) => { b.atr_period = v; render(); }, "1", "1")),
    fld("Período Vortex", num(() => b.vortex_period, (v) => { b.vortex_period = v; render(); }, "1", "2")),
    fld("Distancia de piramidación (ATRs)", num(() => b.pyramid_atr_mult, (v) => { b.pyramid_atr_mult = v; }, "0.1", "0")),
  );
  card.appendChild(grid);

  const others = S.blocks.filter((x) => x !== b).map((x) => x.id);
  if (others.length) {
    const sel = el("select");
    const none = el("option", "", "— ninguno —");
    none.value = "";
    sel.appendChild(none);
    for (const id of others) {
      const o = el("option", "", `solo si «${id}» acompaña`);
      o.value = id;
      sel.appendChild(o);
    }
    sel.value = b.parent;
    sel.addEventListener("change", () => { b.parent = sel.value; render(); });
    card.appendChild(fld("Filtro de dirección (opcional)", sel));
  }

  // Condiciones personalizadas (avanzado)
  if ((b.entryRaw && b.entryRaw.type !== "condition") || (b.dirRaw && b.dirRaw.type !== "condition")) {
    card.appendChild(el("p", "hint",
      "Este bloque tiene condiciones personalizadas complejas guardadas; se conservan tal cual al guardar."));
  } else {
    const det = el("details", "sb-custom");
    if (b.entryCustom || b.dirCustom || b.entryRaw || b.dirRaw) det.open = true;
    det.appendChild(el("summary", "", "Personalizar condiciones (avanzado)"));
    const inner = el("div");

    const mkCustom = (label, getNode, setNode, defaultText) => {
      const wrap = el("div", "sb-custom-cond");
      wrap.appendChild(el("span", "lbl", label));
      const node = getNode();
      if (node) {
        const fake = { children: [node] };
        const row = renderCondition(node, {
          get children() { return fake.children; },
          set children(v) { setNode(null); },
        }, blockExtraColumns(b));
        wrap.appendChild(row);
      } else {
        wrap.appendChild(el("span", "hint-inline", defaultText));
        const btn = el("button", "ghost small", "personalizar");
        btn.type = "button";
        btn.addEventListener("click", () => {
          setNode({ type: "condition", left: makeRef("close", b.trigger), op: ">", right: 0 });
          render();
        });
        wrap.appendChild(btn);
      }
      return wrap;
    };

    const short = b.direction === "short";
    inner.appendChild(mkCustom(
      "Entrada",
      () => b.entryCustom ?? (b.entryRaw && b.entryRaw.type === "condition" ? (b.entryCustom = b.entryRaw, b.entryRaw = null, b.entryCustom) : null),
      (v) => { b.entryCustom = v; },
      `cruce ${short ? "bajista" : "alcista"} del Vortex(${b.vortex_period}) en ${b.trigger}`,
    ));
    inner.appendChild(mkCustom(
      "Dirección",
      () => b.dirCustom ?? (b.dirRaw && b.dirRaw.type === "condition" ? (b.dirCustom = b.dirRaw, b.dirRaw = null, b.dirCustom) : null),
      (v) => { b.dirCustom = v; },
      `Vortex ${short ? "bajista" : "alcista"} en ${b.trigger}`,
    ));
    det.appendChild(inner);
    card.appendChild(det);
  }
  return card;
}

// ----- Revisión -----

function viewReview() {
  const root = el("div", "sb-view");
  root.appendChild(el("h2", "sb-q", "Revisa tu estrategia"));

  const sum = el("div", "sb-summary big");
  sum.appendChild(el("span", "", S.display_name || "Sin nombre"));
  if (S.mode === "rules") {
    const mtf = isMultiTF();
    sum.appendChild(el("p", "", mtf
      ? `Multi-timeframe · principal ${S.timeframe}.`
      : `Opera en ${S.timeframe}.`));
    sum.appendChild(el("p", "", `Compra cuando ${describeTree(S.buyTree)}.`));
    sum.appendChild(el("p", "", `Vende cuando ${describeTree(S.sellTree)}.`));
  } else {
    sum.appendChild(el("p", "", `Bloques · timeframe principal ${S.timeframe}.`));
    for (const b of S.blocks) sum.appendChild(el("p", "", describeBlock(b) + "."));
  }
  root.appendChild(sum);

  if (S.mode === "rules" && !isMultiTF()) {
    root.appendChild(el("h3", "panel-subtitle", "Opciones avanzadas"));
    root.append(
      toggleRow("Piramidación", "Permite añadir entradas escalonadas usando el ATR como distancia.",
        () => S.extras.pyramiding, (v) => { S.extras.pyramiding = v; }),
      toggleRow("Tamaño dinámico", "Ajusta el lote según volatilidad (ATR) y volumen relativo.",
        () => S.extras.dynamic_sizing, (v) => { S.extras.dynamic_sizing = v; if (v) S.extras.pyramiding = true; }),
    );

    const det = el("details", "sb-custom");
    det.appendChild(el("summary", "", "Campos personalizados del payload (avanzado)"));
    const list = el("div");
    S.customFields.forEach((f, i) => {
      const row = el("div", "sb-row");
      const key = el("input"); key.type = "text"; key.placeholder = "clave"; key.value = f.key;
      key.addEventListener("change", () => { f.key = key.value.trim(); });
      const type = el("select");
      for (const [v, l] of [["literal", "valor fijo"], ["column", "columna"]]) {
        const o = el("option", "", l); o.value = v; type.appendChild(o);
      }
      type.value = f.type;
      type.addEventListener("change", () => { f.type = type.value; render(); });
      let value;
      if (f.type === "column") {
        value = operandSelect(f.value || "close", primaryTf(), (v) => { f.value = v; });
      } else {
        value = el("input"); value.type = "text"; value.placeholder = "true / 1.5 / texto"; value.value = f.value;
        value.addEventListener("change", () => { f.value = value.value; });
      }
      const rm = el("button", "ghost small", "✕");
      rm.type = "button";
      rm.addEventListener("click", () => { S.customFields.splice(i, 1); render(); });
      row.append(key, type, value, rm);
      list.appendChild(row);
    });
    const add = el("button", "ghost small", "+ campo");
    add.type = "button";
    add.addEventListener("click", () => { S.customFields.push({ key: "", type: "literal", value: "" }); render(); });
    det.append(list, add);
    root.appendChild(det);
  } else if (S.mode === "rules") {
    root.appendChild(el("p", "hint",
      "Las opciones avanzadas (piramidación, tamaño dinámico) solo aplican a estrategias de un " +
      "timeframe; en multi-timeframe usa el tipo Bloques para riesgo avanzado."));
  }

  const vWrap = el("div", "sb-validation");
  if (S.validation === null) {
    vWrap.appendChild(el("p", "hint", "Validando con el servidor…"));
    runRemoteValidation(vWrap);
  } else {
    paintValidation(vWrap);
  }
  root.appendChild(vWrap);
  return root;
}

function toggleRow(title, text, get, set) {
  const row = el("div", "sb-toggle");
  const main = el("div", "main");
  main.append(el("strong", "", title), el("span", "", text));
  const btn = el("button", get() ? "on" : "", get() ? "Sí" : "No");
  btn.type = "button";
  btn.addEventListener("click", () => { set(!get()); render(); });
  row.append(main, btn);
  return row;
}

async function runRemoteValidation(wrap) {
  try {
    S.validation = await apiPost("/api/builder/validate", buildConfig());
  } catch (err) {
    S.validation = { valid: false, errors: [err.message] };
  }
  paintValidation(wrap);
}

function paintValidation(wrap) {
  wrap.innerHTML = "";
  if (S.validation?.valid) {
    wrap.appendChild(el("p", "sb-ok", "✓ Configuración válida — lista para guardar."));
  } else {
    for (const e of S.validation?.errors ?? []) wrap.appendChild(el("p", "sb-bad", `✗ ${e}`));
  }
}

// ---------- Navegación / guardado ----------

async function next() {
  const steps = stepsFor();
  setError("");

  if (S.step === 0 && !S.display_name.trim()) {
    setError("Ponle un nombre a la estrategia.");
    return;
  }
  if (S.step < steps.length - 1) {
    if (steps[S.step + 1] === "Revisión") {
      const errs = localErrors();
      if (errs.length) { setError(errs[0]); return; }
      S.validation = null;
    }
    S.step += 1;
    render();
    return;
  }

  const errs = localErrors();
  if (errs.length) { setError(errs[0]); return; }
  const btn = $("#sb-next");
  btn.disabled = true;
  try {
    const cfg = buildConfig();
    if (S.isNew) {
      await apiPost("/api/builder/strategies", cfg);
    } else {
      await apiPut(`/api/builder/strategies/${encodeURIComponent(S.editingKey)}`, cfg);
    }
    closeBuilder();
    document.dispatchEvent(new CustomEvent("strategies-changed"));
  } catch (err) {
    setError(err.message);
  } finally {
    btn.disabled = false;
  }
}

function back() {
  if (S.step > 0) { S.step -= 1; render(); }
}

async function removeStrategy() {
  if (!S.editingKey) return;
  if (!confirm(`¿Eliminar definitivamente «${S.display_name}»?`)) return;
  try {
    await apiDelete(`/api/builder/strategies/${encodeURIComponent(S.editingKey)}`);
    closeBuilder();
    document.dispatchEvent(new CustomEvent("strategies-changed"));
  } catch (err) {
    setError(err.message);
  }
}

function resetState() {
  uidSeq = 1;
  S.isNew = true;
  S.editingKey = null;
  S.step = 0;
  S.mode = "rules";
  S.display_name = "";
  S.description = "";
  S.timeframe = "M5";
  S.instances = [];
  S.buyTree = group("AND", [cond("close", ">", 0), cond("close", ">", 0)]);
  S.sellTree = group("AND", [cond("close", "<", 0), cond("close", "<", 0)]);
  S.extras = { pyramiding: false, dynamic_sizing: false };
  S.customFields = [];
  S.blocks = [];
  S.validation = null;
}

async function ensureMeta() {
  if (!meta) meta = await apiGet("/api/builder/meta");
}

export async function openBuilderNew() {
  await ensureMeta();
  resetState();
  const rsi = addInstance("RSI");
  const rsiCol = realizeColumns(rsi)[0].column;
  S.buyTree = group("AND", [cond(rsiCol, "<", 30), cond("close", ">", "open")]);
  S.sellTree = group("AND", [cond(rsiCol, ">", 70), cond("close", "<", "open")]);
  document.getElementById("builder").hidden = false;
  render();
}

export async function openBuilderEdit(key) {
  await ensureMeta();
  resetState();
  const cfg = await apiGet(`/api/builder/strategies/${encodeURIComponent(key)}`);
  S.isNew = false;
  S.editingKey = key;
  loadFromConfig(cfg);
  document.getElementById("builder").hidden = false;
  render();
}

export function closeBuilder() {
  document.getElementById("builder").hidden = true;
}

export function initBuilder() {
  $("#sb-close").addEventListener("click", closeBuilder);
  $("#sb-back").addEventListener("click", back);
  $("#sb-next").addEventListener("click", next);
  $("#sb-delete").addEventListener("click", removeStrategy);
  document.addEventListener("keydown", (ev) => {
    if (ev.key === "Escape" && !document.getElementById("builder").hidden) closeBuilder();
  });
}
