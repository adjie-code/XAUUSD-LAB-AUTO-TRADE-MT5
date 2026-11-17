"use strict";

const $ = (id) => document.getElementById(id);
let DATA = null;

function el(tag, cls, text) {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text != null) n.textContent = text;
  return n;
}
function fmt(v, d = 2, suffix = "") {
  return (v == null || !isFinite(Number(v))) ? "—" : Number(v).toFixed(d) + suffix;
}
function fmtSigned(v, d = 2) {
  const n = Number(v || 0);
  return `${n > 0 ? "+" : ""}${n.toFixed(d)}`;
}
function pnlClass(v) {
  return Number(v || 0) >= 0 ? "mon-pnl-pos" : "mon-pnl-neg";
}

function modeClass(mode) {
  return mode === "LIVE" ? "live" : mode === "SHADOW" ? "shadow" : "filter";
}
function modeLabel(mode) {
  return mode === "SHADOW" ? "BAYANGAN" : mode;
}
function verdictClass(v) {
  const s = String(v || "").toLowerCase();
  if (s.includes("layak")) return "pass";
  if (s.includes("revisi")) return "warn";
  return "fail";
}
function setStatus(text, kind = "is-stale") {
  const pill = $("mon-status");
  if (!pill) return;
  pill.classList.remove("is-live", "is-stale", "is-off");
  pill.classList.add(kind);
  $("mon-status-text").textContent = text;
}

function renderStats() {
  const cards = DATA.strategies || [];
  const live = cards.filter((x) => x.mode === "LIVE").length;
  const slots = DATA.slot_allocation || {};
  const totalSlots = Object.values(slots).reduce((a, b) => a + Number(b || 0), 0);
  const f = DATA.forecast;
  const t = DATA.trend;
  $("stat-live").textContent = String(live);
  $("stat-slots").textContent = totalSlots ? String(totalSlots) : "—";
  $("stat-forecast").textContent = f ? f.label : "—";
  $("stat-forecast-sub").textContent = f ? `${f.confidence || "neutral"} · ${f.rule || ""}` : "model arah";
  const pnl = DATA.pnl || {};
  const totalPnl = Number(pnl.total || 0);
  $("stat-pnl").textContent = fmtSigned(totalPnl);
  $("stat-pnl").className = pnlClass(totalPnl);
  $("stat-pnl-sub").textContent = `R ${fmtSigned(pnl.realized_total)} · F ${fmtSigned(pnl.floating_total)}`;
  const v = DATA.direction_validation;
  $("stat-direction").textContent = v && v.hit_pct != null ? fmt(v.hit_pct, 2, "%") : "—";
  $("stat-direction-sub").textContent = v
    ? `high ${fmt(v.high_hit_pct, 2, "%")} · ${v.n_signals || 0} sinyal`
    : "validasi historis";
  $("stat-trend").textContent = t ? t.dir : "—";
  $("stat-trend-sub").textContent = t && t.ema != null ? `EMA${t.period || 13} ${fmt(t.ema, 2)}` : "EMA13";
}

function renderLatest(card) {
  const l = card.latest;
  const box = el("div", "mon-latest");
  if (!l) {
    box.textContent = "Belum ada sinyal terbaru.";
    return box;
  }
  if (l.side) {
    const strong = el("strong", "", `${l.side} @ ${fmt(l.entry, 2)}`);
    box.appendChild(strong);
    box.appendChild(document.createTextNode(` · SL ${fmt(l.sl, 2)} · TP ${fmt(l.tp, 2)}`));
    if (l.reason) box.appendChild(document.createTextNode(` · ${l.reason}`));
    return box;
  }
  if (l.active) {
    if (l.active.length) {
      box.appendChild(el("strong", "", `${l.active.length} sinyal aktif`));
      const s = l.active[0];
      box.appendChild(document.createTextNode(` · ${s.side} @ ${fmt(s.entry, 2)}`));
    } else {
      box.textContent = "Tidak ada sinyal PATTERN aktif.";
    }
    if (l.entries_today != null) {
      box.appendChild(document.createTextNode(` · entry hari ini: ${l.entries_today}`));
    }
    if (l.refused_recent) {
      box.appendChild(document.createTextNode(` · penolakan log: ${l.refused_recent}`));
    }
    return box;
  }
  if (l.logs) {
    const logs = l.logs.filter((x) => x.result !== "refuse");
    const last = logs[logs.length - 1] || l.logs[l.logs.length - 1];
    if (!last) {
      box.textContent = "Belum ada entry/exit terbaru.";
    } else {
      box.appendChild(el("strong", "", `${last.side || last.id} · ${last.result || ""}`));
      box.appendChild(document.createTextNode(` · ${last.reason || ""}`));
    }
    if (l.entries_today != null) {
      box.appendChild(document.createTextNode(` · entry hari ini: ${l.entries_today}`));
    }
    if (l.refused_recent) {
      box.appendChild(document.createTextNode(` · penolakan log: ${l.refused_recent}`));
    }
    return box;
  }
  if (l.alignments) {
    if (!l.alignments.length) {
      box.textContent = "Tidak ada sinyal PATTERN untuk dikonfirmasi.";
    } else {
      const a = l.alignments[0];
      box.appendChild(el("strong", "", `${a.side} · ${a.align}`));
      box.appendChild(document.createTextNode(` @ ${fmt(a.entry, 2)}`));
    }
    return box;
  }
  box.textContent = "—";
  return box;
}

function renderStrategies() {
  const root = $("strategy-grid");
  root.replaceChildren();
  const cards = DATA.strategies || [];
  $("mon-count").textContent = `${cards.length} strategi`;
  for (const card of cards) {
    const c = el("article", "mon-card");
    const head = el("div", "mon-card-head");
    const title = el("div");
    title.appendChild(el("h3", "", card.name));
    const meta = el("div", "mon-meta");
    meta.textContent = card.magic
      ? `magic ${card.magic} · slot ${card.slots || "—"} · ${card.status}`
      : `slot ${card.slots || "—"} · ${card.status}`;
    title.appendChild(meta);
    head.appendChild(title);
    head.appendChild(el("span", `mon-mode ${modeClass(card.mode)}`, modeLabel(card.mode)));
    c.appendChild(head);
    c.appendChild(el("p", "mon-rules", card.rules || ""));
    c.appendChild(renderLatest(card));
    if (card.metrics) {
      const m = card.metrics;
      const stats = el("div", "mon-metrics");
      for (const [k, v] of [["trade", m.trades], ["net", fmt(m.net_pnl, 2)],
                            ["PF", m.profit_factor == null ? "—" : fmt(m.profit_factor, 3)],
                            ["DD", fmt(m.max_drawdown_pct, 2, "%")]]) {
        const s = el("span", "", `${k} `);
        s.appendChild(el("b", "", String(v ?? "—")));
        stats.appendChild(s);
      }
      c.appendChild(stats);
      if (card.open_count != null) {
        c.appendChild(el("p", "mon-note",
          `Posisi terbuka: ${card.open_count} · floating ${fmtSigned(card.floating_pnl)}`));
      }
      if (card.pnl) {
        c.appendChild(el("p", "mon-note",
          `P/L total ${fmtSigned(card.pnl.total)} · realized ${fmtSigned(card.pnl.realized)} · floating ${fmtSigned(card.pnl.floating)}`));
      }
      if (card.verdict) {
        const v = el("div", `mon-verdict ${verdictClass(card.verdict.verdict)}`,
          `Putusan: ${card.verdict.verdict} (${card.verdict.score || "—"})`);
        c.appendChild(v);
      }
    }
    if (card.note) c.appendChild(el("p", "mon-note", card.note));
    root.appendChild(c);
  }
}

function renderSignals() {
  const root = $("signal-list");
  root.replaceChildren();
  const rows = [];
  for (const s of DATA.shadow_signals || []) {
    rows.push({ strategy: s.strategy, side: s.side, entry: s.entry, sl: s.sl,
                tp: s.tp, status: s.status, reason: s.reason });
  }
  for (const s of (DATA.executor && DATA.executor.active_signals) || []) {
    const align = (DATA.forecast && DATA.forecast.dir > 0 && s.side === "BUY") ||
                  (DATA.forecast && DATA.forecast.dir < 0 && s.side === "SELL")
      ? "konfirmasi" : (DATA.forecast && DATA.forecast.dir === 0 ? "netral" : "konflik");
    rows.push({ strategy: "PATTERN+forecast", side: s.side, entry: s.entry,
                sl: s.sl, tp: s.tp, status: align, reason: s.id });
  }
  if (!rows.length) {
    root.appendChild(el("div", "mon-empty",
      "Belum ada sinyal aktif. Model arah sedang netral atau menunggu breakout."));
    return;
  }
  for (const s of rows) {
    const row = el("div", "mon-signal");
    const main = el("div", "mon-signal-main");
    main.appendChild(el("strong", "", s.strategy));
    main.appendChild(el("span", "", ` · ${s.side} @ ${fmt(s.entry, 2)} · SL ${fmt(s.sl, 2)} · TP ${fmt(s.tp, 2)}`));
    if (s.reason) main.appendChild(el("span", "", ` · ${s.reason}`));
    row.appendChild(main);
    row.appendChild(el("span", `mon-tag ${s.side === "BUY" ? "buy" : "sell"}`, s.status || "—"));
    root.appendChild(row);
  }
}

function fmtAge(ts) {
  if (!ts) return "—";
  const sec = Math.max(0, Math.floor(Date.now() / 1000) - ts);
  if (sec < 60) return `${sec} dtk`;
  if (sec < 3600) return `${Math.floor(sec / 60)} mnt`;
  if (sec < 86400) return `${Math.floor(sec / 3600)} jam`;
  return `${Math.floor(sec / 86400)} hr`;
}

function renderPnl() {
  const pnl = DATA.pnl;
  if (!pnl) return;
  const labels = {pattern: "PATTERN", pullback: "PULLBACK", meanrev: "MEANREV",
                  breakout: "BREAKOUT", confluence: "CONFLUENCE"};
  const ids = ["pattern", "pullback", "meanrev", "breakout", "confluence"];
  const table = $("pnl-strategy-table").querySelector("tbody");
  table.replaceChildren();
  let tr = 0, r = 0, f = 0, t = 0, o = 0;
  for (const id of ids) {
    const p = (pnl.per_strategy || {})[id] || {};
    const row = el("tr");
    row.appendChild(el("td", "", labels[id]));
    row.appendChild(el("td", "", String(p.trades || 0)));
    row.appendChild(el("td", pnlClass(p.realized), fmtSigned(p.realized)));
    row.appendChild(el("td", pnlClass(p.floating), fmtSigned(p.floating)));
    row.appendChild(el("td", pnlClass(p.total), fmtSigned(p.total)));
    row.appendChild(el("td", "", String(p.open_count || 0)));
    table.appendChild(row);
    tr += Number(p.trades || 0); r += Number(p.realized || 0);
    f += Number(p.floating || 0); t += Number(p.total || 0);
    o += Number(p.open_count || 0);
  }
  const total = el("tr", "mon-total-row");
  total.appendChild(el("td", "", "TOTAL"));
  total.appendChild(el("td", "", String(tr)));
  total.appendChild(el("td", pnlClass(r), fmtSigned(r)));
  total.appendChild(el("td", pnlClass(f), fmtSigned(f)));
  total.appendChild(el("td", pnlClass(t), fmtSigned(t)));
  total.appendChild(el("td", "", String(o)));
  table.appendChild(total);

  const dailyTable = $("pnl-daily-table").querySelector("tbody");
  dailyTable.replaceChildren();
  const days = pnl.daily || [];
  if (!days.length) {
    const row = el("tr");
    const td = el("td", "", "Belum ada deal keluar yang tercatat.");
    td.colSpan = 7;
    row.appendChild(td);
    dailyTable.appendChild(row);
  } else {
    for (const d of days) {
      const row = el("tr");
      row.appendChild(el("td", "", d.date));
      for (const id of ids) {
        const val = (d.by_strategy || {})[id] || 0;
        row.appendChild(el("td", pnlClass(val), fmtSigned(val)));
      }
      row.appendChild(el("td", pnlClass(d.total), fmtSigned(d.total)));
      dailyTable.appendChild(row);
    }
  }
  const todayRow = (pnl.daily || []).find((d) => d.date === pnl.today);
  $("pnl-meta").textContent = `${pnl.today || "—"} · hari ini ${fmtSigned(todayRow ? todayRow.total : 0)} · update ${pnl.updated || "—"}`;
}

function renderPositions() {
  const tbody = $("positions-table").querySelector("tbody");
  tbody.replaceChildren();
  const rows = DATA.open_positions || [];
  const pnl = DATA.floating_pnl == null ? 0 : Number(DATA.floating_pnl);
  $("pos-meta").textContent = `${rows.length} posisi · floating ${fmt(pnl, 2)} · snapshot ${DATA.positions_updated || "—"}`;
  if (!rows.length) {
    const tr = el("tr");
    const td = el("td", "", "Belum ada posisi terbuka.");
    td.colSpan = 10;
    tr.appendChild(td);
    tbody.appendChild(tr);
    return;
  }
  for (const p of rows) {
    const tr = el("tr");
    tr.appendChild(el("td", "", p.label || p.strategy));
    tr.appendChild(el("td", "", p.ticket));
    tr.appendChild(el("td", p.side === "BUY" ? "mon-pnl-pos" : "mon-pnl-neg", p.side));
    tr.appendChild(el("td", "", fmt(p.volume, 2)));
    tr.appendChild(el("td", "", fmt(p.entry, 2)));
    tr.appendChild(el("td", "", fmt(p.current, 2)));
    tr.appendChild(el("td", "", fmt(p.sl, 2)));
    tr.appendChild(el("td", "", fmt(p.tp, 2)));
    tr.appendChild(el("td", p.profit >= 0 ? "mon-pnl-pos" : "mon-pnl-neg", fmt(p.profit, 2)));
    tr.appendChild(el("td", "", fmtAge(p.open_time)));
    tbody.appendChild(tr);
  }
}

function renderBacktests() {
  const tbody = $("backtest-table").querySelector("tbody");
  tbody.replaceChildren();
  const cards = (DATA.strategies || []).filter((x) => x.metrics);
  if (!cards.length) {
    const tr = el("tr");
    const td = el("td", "", "Belum ada backtest strategi.");
    td.colSpan = 7;
    tr.appendChild(td);
    tbody.appendChild(tr);
    return;
  }
  for (const card of cards) {
    const m = card.metrics;
    const tr = el("tr");
    tr.appendChild(el("td", "", card.name));
    tr.appendChild(el("td", "", String(m.trades ?? "—")));
    tr.appendChild(el("td", "", fmt(m.win_rate_pct, 2, "%")));
    tr.appendChild(el("td", "", fmt(m.net_pnl, 2)));
    tr.appendChild(el("td", "", m.profit_factor == null ? "—" : fmt(m.profit_factor, 3)));
    tr.appendChild(el("td", "", fmt(m.max_drawdown_pct, 2, "%")));
    const v = card.verdict ? card.verdict.verdict : "—";
    const td = el("td", `mon-verdict ${verdictClass(v)}`, v);
    tr.appendChild(td);
    tbody.appendChild(tr);
  }
}

async function load() {
  try {
    const r = await fetch("/api/strategy-monitor", { cache: "no-store" });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    DATA = await r.json();
    setStatus("LIVE", "is-live");
    $("mon-updated").textContent = DATA.generated_at || "—";
    renderStats();
    renderStrategies();
    renderPnl();
    renderPositions();
    renderSignals();
    renderBacktests();
  } catch (e) {
    setStatus("terputus", "is-off");
    $("mon-updated").textContent = e.message;
  }
}

load();
setInterval(load, 20000);
