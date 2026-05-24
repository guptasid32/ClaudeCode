"use strict";

// Order matters: categorize() returns the FIRST matching category.
// Put specific merchant buckets first, generic infrastructure terms
// ("upi", "neft", "atm") last — otherwise "NEFT-FEES-LATE PAYMENT"
// matches Transfers before Fees & Charges.
const CATEGORIES = [
  "Food & Dining",
  "Groceries",
  "Transport",
  "Utilities",
  "Rent & Housing",
  "Shopping",
  "Entertainment",
  "Health",
  "Education",
  "Investments",
  "Income",
  "Fees & Charges",
  "Cash",
  "Transfers",
  "Other",
];

// Allow-list helpers live in app.js (window.CFM.safeAccountClass /
// .safeSavingTypeClass) so both files share one source of truth.

const CATEGORY_RULES = {
  "Food & Dining": ["swiggy", "zomato", "restaurant", "cafe", "dining", "mcdonald", "kfc", "pizza", "starbucks", "dunkin", "eatfit", "faasos", "barbeque", "biryani"],
  "Groceries": ["bigbasket", "dmart", "d mart", "grofers", "blinkit", "zepto", "grocery", "groceries", "instamart", "reliance fresh", "spencer", "more retail"],
  "Transport": ["uber", "ola", "rapido", "irctc", "fuel", "petrol", "diesel", "metro", "shell", "bpcl", "iocl", "hpcl", "fastag", "parking", "indianoil"],
  "Utilities": ["electricity", "bescom", "msedcl", "tneb", "kseb", "water bill", "gas bill", "internet", "broadband", "airtel", "jio", "vi prepaid", "vodafone", "bsnl", "recharge", "act fibernet"],
  "Rent & Housing": ["rent", "maintenance", "society"],
  "Shopping": ["amazon", "flipkart", "myntra", "ajio", "meesho", "nykaa", "tata cliq", "ikea", "lifestyle", "shoppers stop", "decathlon"],
  "Entertainment": ["netflix", "prime video", "spotify", "hotstar", "bookmyshow", "pvr", "inox", "youtube premium", "apple music", "sony liv", "zee5"],
  "Health": ["pharmacy", "medical", "hospital", "doctor", "apollo", "1mg", "pharmeasy", "netmeds", "clinic", "diagnostic", "manipal", "fortis"],
  "Education": ["udemy", "coursera", "byjus", "unacademy", "tuition", "school", "college", "fees"],
  "Investments": ["zerodha", "groww", "kuvera", "upstox", "mutual fund", " sip", "sip ", "lic ", "ppf", "nps", "elss", "icicidirect", "hdfc sec"],
  "Income": ["salary", "reimbursement", "refund", "cashback", "interest credit", "dividend"],
  "Transfers": ["neft", "imps", "upi", "transfer", "rtgs"],
  "Cash": ["atm", "cash withdrawal", "cash wdl", "cash dep"],
  "Fees & Charges": ["charges", "fee", "gst", "annual fee", "late fee", "penalty"],
};

function categorize(desc) {
  const d = (desc || "").toLowerCase();
  for (const cat of CATEGORIES) {
    const kws = CATEGORY_RULES[cat] || [];
    for (const kw of kws) {
      if (d.includes(kw)) return cat;
    }
  }
  return "Other";
}

// ---------- CSV parsing ----------
function parseCSV(text) {
  const rows = [];
  let row = [];
  let field = "";
  let inQuotes = false;
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (inQuotes) {
      if (c === '"') {
        if (text[i + 1] === '"') { field += '"'; i++; }
        else inQuotes = false;
      } else {
        field += c;
      }
    } else {
      if (c === '"') inQuotes = true;
      else if (c === ",") { row.push(field); field = ""; }
      else if (c === "\n" || c === "\r") {
        if (c === "\r" && text[i + 1] === "\n") i++;
        row.push(field);
        if (row.some((v) => String(v).trim() !== "")) rows.push(row);
        row = [];
        field = "";
      } else {
        field += c;
      }
    }
  }
  if (field !== "" || row.length) {
    row.push(field);
    if (row.some((v) => String(v).trim() !== "")) rows.push(row);
  }
  return rows;
}

function detectColumns(headers) {
  const norm = headers.map((h) => String(h || "").trim().toLowerCase());
  // Each column can only fill one role. Patterns are listed most-specific
  // first; the first pattern that matches any unclaimed column wins.
  const claimed = new Set();
  const findCol = (patterns) => {
    for (const p of patterns) {
      for (let i = 0; i < norm.length; i++) {
        if (claimed.has(i)) continue;
        if (norm[i].includes(p)) {
          claimed.add(i);
          return i;
        }
      }
    }
    return -1;
  };
  // Order across roles matters. Claim:
  //  1) the date column (most specific patterns first),
  //  2) the type-indicator column (e.g. HDFC credit card "Debit / Credit"
  //     holds "Dr"/"Cr", NOT amounts — must be claimed before any "debit"
  //     substring search grabs it as an amount),
  //  3) amount/debit/credit columns,
  //  4) the description column last so generic patterns can't steal the date.
  const date = findCol(["transaction date", "txn date", "posting date", "tran date", "value date", "date"]);
  const type = findCol(["debit / credit", "debit/credit", "dr/cr", "dr / cr", "cr/dr", "type"]);
  const debit = findCol(["withdrawal amt", "withdrawal amount", "debit amount", "withdrawal", "debit", "dr amount"]);
  const credit = findCol(["deposit amt", "deposit amount", "credit amount", "deposit", "credit", "cr amount"]);
  const amount = findCol(["amount"]);
  const desc = findCol(["transaction remarks", "narration", "particulars", "description", "details", "remarks"]);
  return { date, desc, debit, credit, amount, type };
}

function parseDate(s) {
  if (!s) return null;
  const str = String(s).trim();
  let m;
  m = str.match(/^(\d{4})[-\/](\d{1,2})[-\/](\d{1,2})/);
  if (m) return new Date(+m[1], +m[2] - 1, +m[3]);
  m = str.match(/^(\d{1,2})[-\/](\d{1,2})[-\/](\d{2,4})/);
  if (m) {
    let y = +m[3];
    if (y < 100) y += 2000;
    return new Date(y, +m[2] - 1, +m[1]);
  }
  const months = { jan: 0, feb: 1, mar: 2, apr: 3, may: 4, jun: 5, jul: 6, aug: 7, sep: 8, oct: 9, nov: 10, dec: 11 };
  m = str.match(/^(\d{1,2})[-\/ ]([A-Za-z]{3})[A-Za-z]*[-\/ ](\d{2,4})/);
  if (m) {
    let y = +m[3];
    if (y < 100) y += 2000;
    const mo = months[m[2].toLowerCase()];
    if (mo != null) return new Date(y, mo, +m[1]);
  }
  const d = new Date(str);
  return isNaN(d.getTime()) ? null : d;
}

function parseAmount(s) {
  if (s == null) return 0;
  const str = String(s).replace(/[₹$€£¥,\s]/g, "");
  if (!str) return 0;
  const n = parseFloat(str);
  return isNaN(n) ? 0 : n;
}

function csvToTransactions(text) {
  const rows = parseCSV(text);
  if (rows.length < 2) return { transactions: [], skipped: 0 };
  // find header row - the row with the most matches in known patterns
  let headerIdx = 0;
  let bestScore = -1;
  for (let i = 0; i < Math.min(rows.length, 10); i++) {
    const cols = detectColumns(rows[i]);
    const score = Object.values(cols).filter((v) => v >= 0).length;
    if (score > bestScore) { bestScore = score; headerIdx = i; }
  }
  const cols = detectColumns(rows[headerIdx]);
  const out = [];
  let skipped = 0;
  for (let i = headerIdx + 1; i < rows.length; i++) {
    const r = rows[i];
    const dateRaw = cols.date >= 0 ? r[cols.date] : "";
    const desc = (cols.desc >= 0 ? r[cols.desc] : "") || "";
    let debit = 0, credit = 0;
    if (cols.debit >= 0 || cols.credit >= 0) {
      debit = parseAmount(cols.debit >= 0 ? r[cols.debit] : 0);
      credit = parseAmount(cols.credit >= 0 ? r[cols.credit] : 0);
    } else if (cols.amount >= 0) {
      const amt = parseAmount(r[cols.amount]);
      const typeStr = cols.type >= 0 ? String(r[cols.type] || "").toLowerCase() : "";
      const isDebit = typeStr.startsWith("dr") || typeStr === "debit" || amt < 0;
      if (isDebit) debit = Math.abs(amt);
      else credit = Math.abs(amt);
    } else {
      skipped++; continue;
    }
    const date = parseDate(dateRaw);
    if (!date || (!debit && !credit) || !String(desc).trim()) { skipped++; continue; }
    out.push({
      id: window.CFM.uid(),
      date: toISODate(date),
      description: String(desc).trim(),
      debit,
      credit,
      category: categorize(desc),
    });
  }
  return { transactions: out, skipped };
}

function toISODate(d) {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

function monthOf(isoDate) {
  return String(isoDate).slice(0, 7);
}

// ---------- Statements UI ----------
let draftTxns = [];

let aiAvailable = false;

async function checkAIStatus() {
  if (location.protocol !== "http:" && location.protocol !== "https:") return;
  try {
    const r = await fetch("/api/categorize/status", { cache: "no-store" });
    if (!r.ok) return;
    const body = await r.json();
    aiAvailable = !!body.available;
    const btn = document.getElementById("stmt-ai");
    if (btn) {
      btn.hidden = !aiAvailable;
      if (aiAvailable && body.model) {
        btn.title = `Send 'Other' rows to ${body.model} for categorization`;
      } else if (body.reason) {
        btn.title = body.reason;
      }
    }
  } catch {
    // server doesn't support categorization; leave button hidden
  }
}

async function aiCategorize() {
  const targets = draftTxns.filter((t) => t.category === "Other");
  const status = document.getElementById("ai-status");
  const btn = document.getElementById("stmt-ai");
  if (!targets.length) {
    status.textContent = "Nothing to categorize — no rows are tagged Other.";
    status.hidden = false;
    return;
  }
  // Snapshot the draft so a Save / Discard / new-upload during the fetch
  // can't cause us to mutate the wrong (or empty) draft on return.
  const draftAtRequest = draftTxns;
  const targetIds = new Set(targets.map((t) => t.id));
  btn.disabled = true;
  status.hidden = false;
  status.textContent = `Asking Claude to categorize ${targets.length} row${targets.length === 1 ? "" : "s"}…`;
  try {
    const token = (() => {
      try { return localStorage.getItem("couple-fund-manager:token") || ""; } catch { return ""; }
    })();
    const headers = { "Content-Type": "application/json" };
    if (token) headers.Authorization = `Bearer ${token}`;
    const r = await fetch("/api/categorize", {
      method: "POST",
      headers,
      body: JSON.stringify({
        transactions: targets.map((t) => ({ id: t.id, description: t.description })),
        categories: CATEGORIES,
      }),
    });
    const body = await r.json();
    if (!r.ok) {
      status.textContent = `AI categorization failed: ${body.error || r.statusText}`;
      return;
    }
    if (draftTxns !== draftAtRequest) {
      status.textContent = "Draft changed during request — AI result discarded.";
      return;
    }
    const results = body.results || {};
    let updated = 0;
    for (const t of draftTxns) {
      if (!targetIds.has(t.id)) continue;
      const cat = results[t.id];
      if (cat && CATEGORIES.includes(cat) && cat !== t.category) {
        t.category = cat;
        updated++;
      }
    }
    status.textContent = `Updated ${updated} of ${targets.length} rows using ${body.model || "Claude"}.`;
    renderPreview();
  } catch (e) {
    status.textContent = `AI categorization failed: ${e.message || e}`;
  } finally {
    btn.disabled = false;
  }
}

function initStatements() {
  // Default the month picker to current month
  const mEl = document.getElementById("stmt-month");
  const now = new Date();
  mEl.value = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;

  // Refresh personal labels in account selector
  refreshStmtAccountOptions();

  // File upload
  document.getElementById("stmt-file").addEventListener("change", (e) => {
    const f = e.target.files[0];
    if (!f) return;
    const reader = new FileReader();
    reader.onload = () => {
      const { transactions, skipped } = csvToTransactions(String(reader.result || ""));
      if (!transactions.length) {
        alert(`Could not parse any transactions from ${f.name}. Check that the CSV has Date, Description and Debit/Credit (or Amount) columns.`);
        return;
      }
      draftTxns = transactions;
      autoSetMonthFromDraft();
      clearAIStatus();
      if (skipped) console.warn(`Skipped ${skipped} unparseable rows`);
      renderPreview();
    };
    reader.readAsText(f);
  });

  // Paste
  document.getElementById("stmt-parse-paste").addEventListener("click", () => {
    const text = document.getElementById("stmt-paste").value;
    if (!text.trim()) return;
    const { transactions } = csvToTransactions(text);
    if (!transactions.length) {
      alert("Could not parse any transactions from pasted text.");
      return;
    }
    draftTxns = transactions;
    autoSetMonthFromDraft();
    clearAIStatus();
    renderPreview();
  });

  // Manual entry
  document.getElementById("stmt-manual-form").addEventListener("submit", (e) => {
    e.preventDefault();
    const date = document.getElementById("man-date").value;
    const desc = document.getElementById("man-desc").value.trim();
    const debit = Number(document.getElementById("man-debit").value) || 0;
    const credit = Number(document.getElementById("man-credit").value) || 0;
    if (!date || !desc || (debit <= 0 && credit <= 0)) {
      const status = document.getElementById("ai-status");
      status.textContent = "Need a date, a description, and either an outflow or inflow amount.";
      status.hidden = false;
      return;
    }
    draftTxns.push({
      id: window.CFM.uid(),
      date,
      description: desc,
      debit,
      credit,
      category: categorize(desc),
    });
    e.target.reset();
    renderPreview();
  });

  function clearAIStatus() {
    const s = document.getElementById("ai-status");
    if (s) { s.hidden = true; s.textContent = ""; }
  }

  // AI categorize
  document.getElementById("stmt-ai").addEventListener("click", aiCategorize);
  checkAIStatus();

  // Discard + Save
  document.getElementById("stmt-discard").addEventListener("click", () => {
    if (draftTxns.length && !confirm("Discard the draft preview?")) return;
    draftTxns = [];
    document.getElementById("stmt-paste").value = "";
    // Clearing .value lets the user re-select the same file (the change
    // event doesn't fire when the value is unchanged).
    document.getElementById("stmt-file").value = "";
    clearAIStatus();
    renderPreview();
  });

  document.getElementById("stmt-save").addEventListener("click", () => {
    if (!draftTxns.length) return;
    const account = document.getElementById("stmt-account").value;
    const month = document.getElementById("stmt-month").value;
    const label = document.getElementById("stmt-label").value.trim();
    if (!month) { alert("Please choose a month."); return; }

    const existing = window.CFM.state.statements.find(
      (s) => s.account === account && s.month === month && s.label === label,
    );
    if (existing) {
      if (!confirm(`A statement for ${month} (${window.CFM.accountLabel(account)}${label ? " · " + label : ""}) already exists. Replace it?`)) return;
      window.CFM.state.statements = window.CFM.state.statements.filter((s) => s !== existing);
    }
    window.CFM.state.statements.push({
      id: window.CFM.uid(),
      month,
      account,
      label,
      uploadedAt: new Date().toISOString(),
      transactions: draftTxns,
    });
    window.CFM.save();
    draftTxns = [];
    document.getElementById("stmt-paste").value = "";
    document.getElementById("stmt-file").value = "";
    clearAIStatus();
    renderPreview();
    window.CFM.render();
  });

  // History filters
  document.getElementById("hist-month").addEventListener("change", renderHistory);
  document.getElementById("hist-account").addEventListener("change", renderHistory);
}

function refreshStmtAccountOptions() {
  const sel = document.getElementById("stmt-account");
  if (!sel) return;
  const labels = {
    personalA: `Personal — ${window.CFM.state.people.a.name}`,
    personalB: `Personal — ${window.CFM.state.people.b.name}`,
    joint: "Joint",
  };
  for (const opt of sel.options) {
    if (labels[opt.value]) opt.textContent = labels[opt.value];
  }
  const histSel = document.getElementById("hist-account");
  if (histSel) {
    for (const opt of histSel.options) {
      if (labels[opt.value]) opt.textContent = labels[opt.value];
    }
    const both = histSel.querySelector('option[value="personalBoth"]');
    if (both) both.textContent = `Both personal (${window.CFM.state.people.a.name} + ${window.CFM.state.people.b.name})`;
  }
}

function autoSetMonthFromDraft() {
  if (!draftTxns.length) return;
  const months = {};
  for (const t of draftTxns) {
    const m = monthOf(t.date);
    months[m] = (months[m] || 0) + 1;
  }
  let best = null, bestCount = 0;
  for (const [m, c] of Object.entries(months)) {
    if (c > bestCount) { best = m; bestCount = c; }
  }
  if (best) document.getElementById("stmt-month").value = best;
}

function renderPreview() {
  const card = document.getElementById("stmt-preview-card");
  const tbody = document.querySelector("#stmt-preview-table tbody");
  const status = document.getElementById("ai-status");
  if (!draftTxns.length) {
    card.hidden = true;
    if (status) status.hidden = true;
    return;
  }
  card.hidden = false;
  tbody.innerHTML = "";
  let dTotal = 0, cTotal = 0;
  for (const t of draftTxns) {
    dTotal += t.debit;
    cTotal += t.credit;
    const tr = document.createElement("tr");
    const catOpts = CATEGORIES.map((c) =>
      `<option value="${c}"${c === t.category ? " selected" : ""}>${c}</option>`,
    ).join("");
    tr.innerHTML = `
      <td>${window.CFM.escapeHtml(t.date)}</td>
      <td>${window.CFM.escapeHtml(t.description)}</td>
      <td><select class="cat-select" data-id="${window.CFM.escapeHtml(t.id)}">${catOpts}</select></td>
      <td class="num">${t.debit ? window.CFM.fmt(t.debit) : ""}</td>
      <td class="num">${t.credit ? window.CFM.fmt(t.credit) : ""}</td>
      <td class="num"><button class="icon" data-del="${window.CFM.escapeHtml(t.id)}">×</button></td>
    `;
    tr.querySelector("select").addEventListener("change", (e) => {
      const row = draftTxns.find((x) => x.id === t.id);
      if (row) row.category = e.target.value;
    });
    tr.querySelector("button").addEventListener("click", () => {
      draftTxns = draftTxns.filter((x) => x.id !== t.id);
      renderPreview();
    });
    tbody.appendChild(tr);
  }
  document.getElementById("prev-debit-total").textContent = window.CFM.fmt(dTotal);
  document.getElementById("prev-credit-total").textContent = window.CFM.fmt(cTotal);
  document.getElementById("stmt-preview-count").textContent = `· ${draftTxns.length} rows`;
}

function renderStatements() {
  refreshStmtAccountOptions();
  const tbody = document.querySelector("#saved-statements-table tbody");
  tbody.innerHTML = "";
  const empty = document.getElementById("saved-empty");
  const list = [...window.CFM.state.statements].sort(
    (a, b) => (b.month + b.account).localeCompare(a.month + a.account),
  );
  empty.hidden = list.length > 0;
  for (const s of list) {
    const out = s.transactions.reduce((x, t) => x + (t.debit || 0), 0);
    const inn = s.transactions.reduce((x, t) => x + (t.credit || 0), 0);
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${window.CFM.escapeHtml(s.month)}</td>
      <td><span class="pill ${window.CFM.safeAccountClass(s.account)}">${window.CFM.escapeHtml(window.CFM.accountLabel(s.account))}</span></td>
      <td>${window.CFM.escapeHtml(s.label || "—")}</td>
      <td class="num">${s.transactions.length}</td>
      <td class="num">${window.CFM.fmt(out)}</td>
      <td class="num">${window.CFM.fmt(inn)}</td>
      <td class="num"><button class="icon" data-id="${window.CFM.escapeHtml(s.id)}" title="Delete">×</button></td>
    `;
    tr.querySelector("button").addEventListener("click", () => {
      if (!confirm(`Delete ${s.month} statement for ${window.CFM.accountLabel(s.account)}?`)) return;
      window.CFM.state.statements = window.CFM.state.statements.filter((x) => x.id !== s.id);
      window.CFM.save();
      window.CFM.render();
    });
    tbody.appendChild(tr);
  }
}

// ---------- History ----------
function renderHistory() {
  refreshStmtAccountOptions();
  const monthSel = document.getElementById("hist-month");
  const months = uniqueMonths().sort((a, b) => b.localeCompare(a));
  const prev = monthSel.value;
  monthSel.innerHTML = `<option value="__all">All months (till now)</option>` +
    months.map((m) => `<option value="${m}">${m}</option>`).join("");
  if (prev && [...monthSel.options].some((o) => o.value === prev)) monthSel.value = prev;

  const month = monthSel.value || "__all";
  const accountSel = document.getElementById("hist-account").value;
  const txns = filteredTransactions(month, accountSel);

  const inflow = txns.reduce((x, t) => x + (t.credit || 0), 0);
  const outflow = txns.reduce((x, t) => x + (t.debit || 0), 0);
  const net = inflow - outflow;
  document.getElementById("hist-inflow").textContent = window.CFM.fmt(inflow);
  document.getElementById("hist-outflow").textContent = window.CFM.fmt(outflow);
  const netEl = document.getElementById("hist-net");
  netEl.textContent = window.CFM.fmt(net);
  netEl.classList.toggle("positive", net > 0);
  netEl.classList.toggle("negative", net < 0);

  renderCategoryBreakdown(txns);
  renderMonthlyTrend(accountSel);
}

function uniqueMonths() {
  const set = new Set();
  for (const s of window.CFM.state.statements) set.add(s.month);
  return [...set];
}

function accountMatches(stmtAccount, filter) {
  if (filter === "combined") return true;
  if (filter === "personalBoth") return stmtAccount === "personalA" || stmtAccount === "personalB";
  return stmtAccount === filter;
}

function filteredTransactions(month, accountFilter) {
  const out = [];
  for (const s of window.CFM.state.statements) {
    if (!accountMatches(s.account, accountFilter)) continue;
    if (month !== "__all" && s.month !== month) continue;
    for (const t of s.transactions) out.push({ ...t, _month: s.month, _account: s.account });
  }
  return out;
}

function renderCategoryBreakdown(txns) {
  const tbody = document.querySelector("#hist-category-table tbody");
  tbody.innerHTML = "";
  const empty = document.getElementById("hist-empty");
  const expenseTxns = txns.filter((t) => t.debit > 0);
  empty.hidden = expenseTxns.length > 0;

  const byCat = {};
  for (const t of expenseTxns) {
    if (!byCat[t.category]) byCat[t.category] = { count: 0, total: 0 };
    byCat[t.category].count += 1;
    byCat[t.category].total += t.debit;
  }
  const rows = Object.entries(byCat)
    .map(([cat, v]) => ({ cat, ...v }))
    .sort((a, b) => b.total - a.total);
  const grandTotal = rows.reduce((x, r) => x + r.total, 0);
  const max = rows.length ? rows[0].total : 0;
  for (const r of rows) {
    const tr = document.createElement("tr");
    const pct = grandTotal > 0 ? (r.total / grandTotal) * 100 : 0;
    const barPct = max > 0 ? (r.total / max) * 100 : 0;
    tr.innerHTML = `
      <td>${window.CFM.escapeHtml(r.cat)}</td>
      <td class="num">${r.count}</td>
      <td class="num">${window.CFM.fmt(r.total)}</td>
      <td class="num">${pct.toFixed(1)}%</td>
      <td><div class="bar-inline"><div style="width:${barPct.toFixed(1)}%"></div></div></td>
    `;
    tbody.appendChild(tr);
  }
}

function renderMonthlyTrend(accountFilter) {
  const tbody = document.querySelector("#hist-trend-table tbody");
  tbody.innerHTML = "";
  const months = uniqueMonths().sort();
  let totalIn = 0, totalOut = 0;
  for (const m of months) {
    const txns = filteredTransactions(m, accountFilter);
    const inn = txns.reduce((x, t) => x + (t.credit || 0), 0);
    const out = txns.reduce((x, t) => x + (t.debit || 0), 0);
    totalIn += inn;
    totalOut += out;
    const net = inn - out;
    const byCat = {};
    for (const t of txns) {
      if (!t.debit) continue;
      byCat[t.category] = (byCat[t.category] || 0) + t.debit;
    }
    const top = Object.entries(byCat).sort((a, b) => b[1] - a[1]).slice(0, 3)
      .map(([c, v]) => `<span class="cat-pill">${window.CFM.escapeHtml(c)} · ${window.CFM.fmt(v)}</span>`)
      .join(" ");
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${window.CFM.escapeHtml(m)}</td>
      <td class="num">${window.CFM.fmt(inn)}</td>
      <td class="num">${window.CFM.fmt(out)}</td>
      <td class="num ${net >= 0 ? "positive" : "negative"}">${window.CFM.fmt(net)}</td>
      <td>${top || "—"}</td>
    `;
    tbody.appendChild(tr);
  }
  document.getElementById("trend-in-total").textContent = window.CFM.fmt(totalIn);
  document.getElementById("trend-out-total").textContent = window.CFM.fmt(totalOut);
  const netEl = document.getElementById("trend-net-total");
  const totNet = totalIn - totalOut;
  netEl.textContent = window.CFM.fmt(totNet);
  netEl.classList.toggle("positive", totNet > 0);
  netEl.classList.toggle("negative", totNet < 0);
}
