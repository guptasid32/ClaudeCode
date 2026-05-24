"use strict";

const STORAGE_KEY = "couple-fund-manager:v1";

const defaultState = () => ({
  currency: "₹",
  people: {
    a: { name: "Partner A", income: 0, contribution: 0 },
    b: { name: "Partner B", income: 0, contribution: 0 },
  },
  expenses: [],
  savings: [],
  statements: [],
});

function mergeWithDefaults(parsed) {
  if (!parsed || typeof parsed !== "object") return defaultState();
  const d = defaultState();
  return {
    ...d, ...parsed,
    people: {
      a: { ...d.people.a, ...(parsed.people?.a || {}) },
      b: { ...d.people.b, ...(parsed.people?.b || {}) },
    },
    expenses: Array.isArray(parsed.expenses) ? parsed.expenses : [],
    savings: Array.isArray(parsed.savings) ? parsed.savings : [],
    statements: Array.isArray(parsed.statements) ? parsed.statements : [],
  };
}

// Storage backend: server API if available, else localStorage.
let state = defaultState();
let backend = "local"; // "server" | "local"
let serverVersion = 0;
let saveTimer = null;
let saveInFlight = null;
let pendingSave = false;
const STATUS_EL = () => document.getElementById("storage-status");

function setStatus(text, kind) {
  const el = STATUS_EL();
  if (!el) return;
  el.textContent = text;
  el.dataset.kind = kind || "";
}

async function loadFromServer() {
  const r = await fetch("/api/state", { cache: "no-store" });
  if (!r.ok) throw new Error(`GET /api/state -> ${r.status}`);
  const body = await r.json();
  serverVersion = body.version || 0;
  return mergeWithDefaults(body.state);
}

function loadFromLocal() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return defaultState();
    return mergeWithDefaults(JSON.parse(raw));
  } catch {
    return defaultState();
  }
}

async function loadState() {
  if (location.protocol === "http:" || location.protocol === "https:") {
    try {
      const s = await loadFromServer();
      backend = "server";
      setStatus(`Synced with laptop · v${serverVersion}`, "ok");
      return s;
    } catch (e) {
      console.warn("Server load failed; falling back to localStorage.", e);
      backend = "local";
      setStatus("Offline — data on this device only", "warn");
      return loadFromLocal();
    }
  }
  backend = "local";
  setStatus("Local only (open via serve.py for shared storage)", "warn");
  return loadFromLocal();
}

async function saveToServer() {
  if (saveInFlight) { pendingSave = true; return; }
  setStatus("Saving…", "pending");
  const snapshot = JSON.stringify({ state });
  saveInFlight = fetch("/api/state", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: snapshot,
  }).then(async (r) => {
    if (!r.ok) throw new Error(`PUT /api/state -> ${r.status}`);
    const body = await r.json();
    serverVersion = body.version || serverVersion + 1;
    setStatus(`Synced with laptop · v${serverVersion}`, "ok");
  }).catch((e) => {
    console.warn("Save failed:", e);
    setStatus("Save failed — keeping a local copy", "warn");
    try { localStorage.setItem(STORAGE_KEY, JSON.stringify(state)); } catch {}
  }).finally(() => {
    saveInFlight = null;
    if (pendingSave) { pendingSave = false; saveToServer(); }
  });
}

function save() {
  if (backend === "server") {
    clearTimeout(saveTimer);
    saveTimer = setTimeout(saveToServer, 250);
  } else {
    try { localStorage.setItem(STORAGE_KEY, JSON.stringify(state)); } catch {}
  }
}

async function clearStorage() {
  if (backend === "server") {
    try {
      const r = await fetch("/api/state", { method: "DELETE" });
      if (!r.ok) throw new Error(`DELETE /api/state -> ${r.status}`);
      const body = await r.json();
      serverVersion = body.version || serverVersion + 1;
      setStatus(`Synced with laptop · v${serverVersion}`, "ok");
    } catch (e) {
      console.warn("Server reset failed:", e);
      setStatus("Reset failed on laptop", "warn");
    }
  }
  try { localStorage.removeItem(STORAGE_KEY); } catch {}
}

async function refreshFromServer() {
  if (backend !== "server") return false;
  try {
    const r = await fetch("/api/state", { cache: "no-store" });
    if (!r.ok) return false;
    const body = await r.json();
    if ((body.version || 0) === serverVersion) return false;
    state = mergeWithDefaults(body.state);
    serverVersion = body.version || 0;
    setStatus(`Synced with laptop · v${serverVersion}`, "ok");
    syncInputs();
    render();
    return true;
  } catch {
    return false;
  }
}

const fmt = (n) => {
  const num = Number(n) || 0;
  const sign = num < 0 ? "-" : "";
  const abs = Math.abs(num);
  return `${sign}${state.currency}${abs.toLocaleString(undefined, {
    maximumFractionDigits: 2,
  })}`;
};

const accountLabel = (key) => {
  if (key === "personalA") return `Personal — ${state.people.a.name}`;
  if (key === "personalB") return `Personal — ${state.people.b.name}`;
  return "Joint";
};

const uid = () => Math.random().toString(36).slice(2, 10);

// ---------- Tabs ----------
function initTabs() {
  document.querySelectorAll(".tab").forEach((btn) => {
    btn.addEventListener("click", () => {
      const target = btn.dataset.tab;
      document.querySelectorAll(".tab").forEach((b) => b.classList.toggle("active", b === btn));
      document.querySelectorAll(".tab-panel").forEach((p) => {
        p.classList.toggle("active", p.id === `tab-${target}`);
      });
    });
  });
}

// ---------- Setup ----------
function initSetup() {
  const map = [
    ["a-name", "a", "name", "text"],
    ["a-income", "a", "income", "number"],
    ["a-contrib", "a", "contribution", "number"],
    ["b-name", "b", "name", "text"],
    ["b-income", "b", "income", "number"],
    ["b-contrib", "b", "contribution", "number"],
  ];
  for (const [id, person, field, type] of map) {
    const el = document.getElementById(id);
    el.value = state.people[person][field];
    el.addEventListener("input", () => {
      const v = type === "number" ? Number(el.value) || 0 : el.value;
      state.people[person][field] = v;
      save();
      render();
    });
  }
}

// ---------- Currency ----------
function initCurrency() {
  const sel = document.getElementById("currency-select");
  sel.value = state.currency;
  sel.addEventListener("change", () => {
    state.currency = sel.value;
    save();
    render();
  });
}

// ---------- Reset ----------
function initReset() {
  document.getElementById("reset-btn").addEventListener("click", async () => {
    const where = backend === "server" ? "on the laptop" : "in this browser";
    if (!confirm(`Erase all data stored ${where} and start over?`)) return;
    await clearStorage();
    state = defaultState();
    syncInputs();
    render();
  });
  const refresh = document.getElementById("refresh-btn");
  if (refresh) {
    refresh.addEventListener("click", async () => {
      const changed = await refreshFromServer();
      if (!changed) setStatus(`Up to date · v${serverVersion}`, "ok");
    });
  }
}

function syncInputs() {
  document.getElementById("a-name").value = state.people.a.name;
  document.getElementById("a-income").value = state.people.a.income;
  document.getElementById("a-contrib").value = state.people.a.contribution;
  document.getElementById("b-name").value = state.people.b.name;
  document.getElementById("b-income").value = state.people.b.income;
  document.getElementById("b-contrib").value = state.people.b.contribution;
  document.getElementById("currency-select").value = state.currency;
}

// ---------- Expenses ----------
function initExpenseForm() {
  document.getElementById("expense-form").addEventListener("submit", (e) => {
    e.preventDefault();
    const name = document.getElementById("exp-name").value.trim();
    const amount = Number(document.getElementById("exp-amount").value) || 0;
    const account = document.getElementById("exp-account").value;
    const category = document.getElementById("exp-category").value.trim();
    if (!name || amount <= 0) return;
    state.expenses.push({ id: uid(), name, amount, account, category });
    save();
    e.target.reset();
    render();
  });
}

function renderExpenses() {
  const tbody = document.querySelector("#expenses-table tbody");
  tbody.innerHTML = "";
  refreshAccountOptions("exp-account");
  for (const item of state.expenses) {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${escapeHtml(item.name)}</td>
      <td>${escapeHtml(item.category || "—")}</td>
      <td><span class="pill ${item.account}">${escapeHtml(accountLabel(item.account))}</span></td>
      <td class="num">${fmt(item.amount)}</td>
      <td class="num"><button class="icon" title="Delete" data-id="${item.id}">×</button></td>
    `;
    tr.querySelector("button").addEventListener("click", () => {
      state.expenses = state.expenses.filter((x) => x.id !== item.id);
      save();
      render();
    });
    tbody.appendChild(tr);
  }
  const total = state.expenses.reduce((s, x) => s + (Number(x.amount) || 0), 0);
  document.getElementById("exp-total").textContent = fmt(total);
}

// ---------- Savings ----------
function initSavingsForm() {
  document.getElementById("savings-form").addEventListener("submit", (e) => {
    e.preventDefault();
    const name = document.getElementById("sav-name").value.trim();
    const amount = Number(document.getElementById("sav-amount").value) || 0;
    const account = document.getElementById("sav-account").value;
    const type = document.getElementById("sav-type").value;
    if (!name || amount <= 0) return;
    state.savings.push({ id: uid(), name, amount, account, type });
    save();
    e.target.reset();
    render();
  });
}

function renderSavings() {
  const tbody = document.querySelector("#savings-table tbody");
  tbody.innerHTML = "";
  refreshAccountOptions("sav-account");
  for (const item of state.savings) {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${escapeHtml(item.name)}</td>
      <td><span class="pill ${item.type}">${item.type}</span></td>
      <td><span class="pill ${item.account}">${escapeHtml(accountLabel(item.account))}</span></td>
      <td class="num">${fmt(item.amount)}</td>
      <td class="num"><button class="icon" title="Delete" data-id="${item.id}">×</button></td>
    `;
    tr.querySelector("button").addEventListener("click", () => {
      state.savings = state.savings.filter((x) => x.id !== item.id);
      save();
      render();
    });
    tbody.appendChild(tr);
  }
  const total = state.savings.reduce((s, x) => s + (Number(x.amount) || 0), 0);
  document.getElementById("sav-total").textContent = fmt(total);
}

function refreshAccountOptions(selectId) {
  const sel = document.getElementById(selectId);
  if (!sel) return;
  const labels = {
    personalA: `Personal — ${state.people.a.name}`,
    personalB: `Personal — ${state.people.b.name}`,
    joint: "Joint",
  };
  for (const opt of sel.options) {
    if (labels[opt.value]) opt.textContent = labels[opt.value];
  }
}

// ---------- Dashboard ----------
function sumBy(list, predicate) {
  return list.filter(predicate).reduce((s, x) => s + (Number(x.amount) || 0), 0);
}

function renderDashboard() {
  const a = state.people.a;
  const b = state.people.b;

  const aExp = sumBy(state.expenses, (x) => x.account === "personalA");
  const bExp = sumBy(state.expenses, (x) => x.account === "personalB");
  const jExp = sumBy(state.expenses, (x) => x.account === "joint");

  const aSav = sumBy(state.savings, (x) => x.account === "personalA");
  const bSav = sumBy(state.savings, (x) => x.account === "personalB");
  const jSav = sumBy(state.savings, (x) => x.account === "joint");

  const aSurplus = a.income - aExp - aSav - a.contribution;
  const bSurplus = b.income - bExp - bSav - b.contribution;
  const jIn = a.contribution + b.contribution;
  const jSurplus = jIn - jExp - jSav;

  document.getElementById("dash-a-name").textContent = a.name;
  document.getElementById("dash-b-name").textContent = b.name;
  setVal("dash-a-income", a.income);
  setVal("dash-a-exp", aExp);
  setVal("dash-a-sav", aSav);
  setVal("dash-a-contrib", a.contribution);
  setVal("dash-a-surplus", aSurplus, true);

  setVal("dash-b-income", b.income);
  setVal("dash-b-exp", bExp);
  setVal("dash-b-sav", bSav);
  setVal("dash-b-contrib", b.contribution);
  setVal("dash-b-surplus", bSurplus, true);

  setVal("dash-j-in", jIn);
  setVal("dash-j-exp", jExp);
  setVal("dash-j-sav", jSav);
  setVal("dash-j-surplus", jSurplus, true);

  // Household
  const hhIncome = a.income + b.income;
  const hhExp = aExp + bExp + jExp;
  const hhSav = aSav + bSav + jSav;
  const hhNet = hhIncome - hhExp - hhSav;
  setVal("hh-income", hhIncome);
  setVal("hh-exp", hhExp);
  setVal("hh-sav", hhSav);
  setVal("hh-net", hhNet, true);
  document.getElementById("hh-rate").textContent =
    hhIncome > 0 ? `${((hhSav / hhIncome) * 100).toFixed(1)}%` : "0%";

  // Allocation bar
  renderAllocationBar(hhIncome, hhExp, hhSav);

  // Suggested contributions (proportional to income)
  const jointRequired = jExp + jSav;
  let sa = 0, sb = 0;
  if (hhIncome > 0) {
    sa = jointRequired * (a.income / hhIncome);
    sb = jointRequired * (b.income / hhIncome);
  } else {
    sa = jointRequired / 2;
    sb = jointRequired / 2;
  }
  document.getElementById("sugg-a-label").textContent = `${a.name} suggested contribution`;
  document.getElementById("sugg-b-label").textContent = `${b.name} suggested contribution`;
  setVal("sugg-a", sa);
  setVal("sugg-b", sb);
  setVal("sugg-required", jointRequired);
}

function setVal(id, n, colorize = false) {
  const el = document.getElementById(id);
  if (!el) return;
  el.textContent = fmt(n);
  el.classList.remove("positive", "negative");
  if (colorize) {
    if (n > 0) el.classList.add("positive");
    else if (n < 0) el.classList.add("negative");
  }
}

function renderAllocationBar(income, exp, sav) {
  const bar = document.getElementById("alloc-bar");
  bar.innerHTML = "";
  const total = Math.max(income, exp + sav);
  if (total <= 0) return;
  const surplus = Math.max(income - exp - sav, 0);
  const segs = [
    { cls: "seg-exp", val: exp },
    { cls: "seg-sav", val: sav },
    { cls: "seg-surplus", val: surplus },
  ];
  for (const s of segs) {
    if (s.val <= 0) continue;
    const div = document.createElement("div");
    div.className = s.cls;
    div.style.width = `${(s.val / total) * 100}%`;
    div.title = `${fmt(s.val)} (${((s.val / total) * 100).toFixed(1)}%)`;
    bar.appendChild(div);
  }
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

// ---------- Main ----------
function render() {
  renderExpenses();
  renderSavings();
  renderDashboard();
  if (typeof renderStatements === "function") renderStatements();
  if (typeof renderHistory === "function") renderHistory();
}

async function init() {
  state = await loadState();
  initTabs();
  initCurrency();
  initSetup();
  initReset();
  initExpenseForm();
  initSavingsForm();
  if (typeof initStatements === "function") initStatements();
  syncInputs();
  render();
  // Light polling so a second device sees the first device's changes
  if (backend === "server") {
    setInterval(() => { refreshFromServer(); }, 8000);
  }
}

// Expose for statements.js
window.CFM = {
  get state() { return state; },
  save, render, fmt, accountLabel, escapeHtml, uid,
};

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", init);
} else {
  // statements.js is loaded immediately after, so wait one tick
  setTimeout(init, 0);
}
