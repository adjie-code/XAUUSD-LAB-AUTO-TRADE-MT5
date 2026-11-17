"use strict";

// ---------- util ----------
// Backend memakai dua satuan waktu: milidetik (dummy) dan epoch detik (MT5).
const toMs = (t) => (t < 1e12 ? t * 1000 : t);
// offset tampilan waktu (jam) — diatur awal via payload dashboard:
// "MT5" = waktu server broker (GMT+2/3, sama seperti chart di HP), "WIB", "UTC".
// fmtTs menerima epoch detik MAUPUN string datetime "YYYY-MM-DD HH:MM:SS" (UTC)
// dan TIDAK PERNAH melempar error (hasil "-" bila tak bisa diparse).
window.__timeOff = window.__timeOff || 0;
const fmtTs = (t) => {
  if (t == null) return "-";
  const offMs = ((typeof window.__timeOff === "number" ? window.__timeOff : 0) || 0) * 3600000;
  let ms;
  if (typeof t === "string") {
    const parsed = new Date(t.replace(" ", "T") + "Z");  // sqlite "YYYY-MM-DD HH:MM:SS"
    ms = parsed.getTime();
  } else {
    ms = toMs(t);
  }
  if (!isFinite(ms)) return "-";
  const d = new Date(ms + offMs);
  if (isNaN(d.getTime())) return "-";
  return d.toISOString().replace("T", " ").slice(0, 16);
};
const fmtPct = (v) => (v == null ? "-" : (v.toFixed ? v.toFixed(2) : v) + "%");
const $ = (id) => document.getElementById(id);
const setText = (id, txt) => { const el = $(id); if (el) el.textContent = txt; };
const setConnection = (kind, text) => {
  const pill = $("conn-pill");
  if (pill) {
    pill.classList.remove("is-live", "is-stale", "is-off");
    if (kind) pill.classList.add(kind);
  }
  setText("conn-text", text);
};

// ---------- autentikasi admin (parameter riset) ----------
const authState = { loggedIn: false, user: null, expiresAt: null };
let paramDirty = false;

function setAuthUI() {
  const on = !!authState.loggedIn;
  const btn = $("auth-btn");
  if (btn) {
    btn.classList.toggle("is-on", on);
    btn.setAttribute("aria-label", on
      ? `Sesi ${authState.user || "admin"} — buka parameter`
      : "Masuk admin");
  }
  setText("auth-icon", on ? "🔓" : "🔒");
  setText("auth-label", on ? (authState.user || "admin") : "Masuk");
  setText("auth-title", on ? "Sesi admin" : "Masuk admin");
  setText("auth-user", authState.user || "-");

  const form = $("login-form");
  const session = $("auth-session");
  if (form) form.hidden = on;
  if (session) session.hidden = !on;

  const lock = $("param-lock");
  const content = $("param-content");
  if (lock) lock.hidden = on;
  if (content) content.hidden = !on;
  if (!on) {
    setText("param-summary", "🔒 masuk untuk lihat");
    setText("save-status", "");
  }
}

function showLoginError(msg) {
  setText("login-error", msg || "");
}

function openAuthModal() {
  const modal = $("auth-modal");
  if (!modal) return;
  showLoginError("");
  setAuthUI();
  modal.hidden = false;
  document.body.classList.add("modal-open");
  setTimeout(() => {
    const target = authState.loggedIn ? $("open-param-btn") : $("login-user");
    if (target) target.focus();
  }, 30);
}

function closeAuthModal() {
  const modal = $("auth-modal");
  if (!modal) return;
  modal.hidden = true;
  document.body.classList.remove("modal-open");
  showLoginError("");
  if ($("login-pass")) $("login-pass").value = "";
}

function openParamPanel() {
  const panel = document.querySelector(".param-panel");
  if (!panel) return;
  panel.open = true;
  panel.scrollIntoView({ behavior: "smooth", block: "center" });
}

function applyParamForm(cfg) {
  if (!cfg || typeof cfg !== "object") return;
  paramDirty = false;
  if ($("time-display")) $("time-display").value = cfg.time_display || "MT5";
  if ($("session")) $("session").value = cfg.prioritize_session || "Asia";
  if ($("threshold")) $("threshold").value = cfg.similarity_threshold_pct ?? "";
  if ($("top-n")) $("top-n").value = cfg.top_patterns ?? "";
  if ($("candles-n")) $("candles-n").value = cfg.candles_per_pattern ?? "";
  if ($("predict-mode")) $("predict-mode").value = cfg.predict_mode || "topk_median";
  if ($("predict-k")) $("predict-k").value = cfg.predict_top_k ?? 10;
  if (authState.loggedIn) {
    setText("param-summary",
      `ambang ${cfg.similarity_threshold_pct ?? "-"}% · top ${cfg.top_patterns ?? "-"} · N ${cfg.candles_per_pattern ?? "-"}`);
  }
}

function clearParamForm() {
  paramDirty = false;
  ["threshold", "top-n", "candles-n", "predict-k"].forEach(id => {
    const el = $(id);
    if (el) el.value = "";
  });
  ["session", "time-display", "predict-mode"].forEach(id => {
    const el = $(id);
    if (el) el.selectedIndex = 0;
  });
  setText("save-status", "");
}

async function loadConfigForAdmin() {
  const r = await fetch("/api/config", { cache: "no-store" });
  if (r.status === 401) {
    authState.loggedIn = false;
    authState.user = null;
    authState.expiresAt = null;
    setAuthUI();
    throw new Error("Sesi admin berakhir. Silakan masuk lagi.");
  }
  let d = {};
  try { d = await r.json(); } catch { d = {}; }
  if (!r.ok || d.ok === false) throw new Error(d.error || "Gagal memuat parameter");
  applyParamForm(d);
  return d;
}

async function initAuth() {
  try {
    const r = await fetch("/api/auth/status", { cache: "no-store" });
    const d = await r.json();
    authState.loggedIn = !!(r.ok && d.logged_in);
    authState.user = d.user || null;
    authState.expiresAt = d.expires_at || null;
  } catch (e) {
    authState.loggedIn = false;
    authState.user = null;
    authState.expiresAt = null;
  }
  setAuthUI();
  if (authState.loggedIn) {
    try {
      await loadConfigForAdmin();
    } catch (e) {
      setText("save-status", e.message || "Gagal memuat parameter");
    }
  }
}

function initAuthControls() {
  [$("auth-btn"), $("param-login-btn")].forEach(el => {
    if (el) el.addEventListener("click", openAuthModal);
  });
  if ($("auth-close")) $("auth-close").addEventListener("click", closeAuthModal);
  if ($("param-content")) {
    $("param-content").addEventListener("input", () => { paramDirty = true; });
    $("param-content").addEventListener("change", () => { paramDirty = true; });
  }
  if ($("auth-modal")) {
    $("auth-modal").addEventListener("click", e => {
      if (e.target === $("auth-modal")) closeAuthModal();
    });
  }
  document.addEventListener("keydown", e => {
    if (e.key === "Escape" && $("auth-modal") && !$("auth-modal").hidden) closeAuthModal();
  });
  if ($("open-param-btn")) {
    $("open-param-btn").addEventListener("click", () => {
      closeAuthModal();
      openParamPanel();
    });
  }
  if ($("logout-btn")) {
    $("logout-btn").addEventListener("click", async () => {
      try { await fetch("/api/logout", { method: "POST" }); } catch (e) { /* cookie tetap dibersihkan di server */ }
      authState.loggedIn = false;
      authState.user = null;
      authState.expiresAt = null;
      clearParamForm();
      setAuthUI();
      closeAuthModal();
      const panel = document.querySelector(".param-panel");
      if (panel) panel.open = false;
      loadDashboard();
    });
  }
  if ($("login-form")) {
    $("login-form").addEventListener("submit", async e => {
      e.preventDefault();
      const user = ($("login-user").value || "").trim();
      const pass = $("login-pass").value || "";
      if (!user || !pass) {
        showLoginError("Nama pengguna dan kata sandi wajib diisi.");
        return;
      }
      const btn = $("login-submit");
      const label = btn.textContent;
      btn.disabled = true;
      btn.textContent = "Memeriksa…";
      showLoginError("");
      try {
        const r = await fetch("/api/login", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ username: user, password: pass }),
        });
        let d = {};
        try { d = await r.json(); } catch { d = {}; }
        if (!r.ok || !d.ok) {
          showLoginError(d.error || (r.status === 429
            ? "Terlalu banyak percobaan. Coba lagi nanti."
            : "Nama pengguna atau kata sandi salah."));
          return;
        }
        authState.loggedIn = true;
        authState.user = d.user || user;
        authState.expiresAt = d.expires_at || null;
        setAuthUI();
        $("login-pass").value = "";
        closeAuthModal();
        try {
          await loadConfigForAdmin();
          openParamPanel();
        } catch (err) {
          setText("save-status", err.message || "Gagal memuat parameter");
        }
      } catch (err) {
        showLoginError("Tidak bisa menghubungi server. Coba lagi.");
      } finally {
        btn.disabled = false;
        btn.textContent = label;
      }
    });
  }
}

// ---------- grafik candlestick (canvas murni — fallback / chart lain) ----------
function drawCandles(canvas, candles, noteText, opts) {
  const o = opts || {};
  const dpr = window.devicePixelRatio || 1;
  const cssW = canvas.clientWidth || 1000;
  const cssH = canvas.clientHeight || Number(canvas.getAttribute("height")) || 220;
  canvas.width = Math.round(cssW * dpr);
  canvas.height = Math.round(cssH * dpr);
  const ctx = canvas.getContext("2d");
  ctx.scale(dpr, dpr);

  ctx.fillStyle = "#0a1019";
  ctx.fillRect(0, 0, cssW, cssH);
  const valid = (candles || []).filter(c =>
    [c.o, c.h, c.l, c.c].every(v => typeof v === "number"));
  if (valid.length === 0) {
    ctx.fillStyle = "#8b98a9";
    ctx.font = "13px monospace";
    ctx.textAlign = "center";
    ctx.fillText(noteText || "belum ada data", cssW / 2, cssH / 2);
    ctx.textAlign = "start";
    return;
  }

  const padL = 8, padR = 64, padT = 12, padB = 20;
  const plotW = cssW - padL - padR;
  const plotH = cssH - padT - padB;

  let max = Math.max(...valid.map(c => c.h)), min = Math.min(...valid.map(c => c.l));
  const pad5 = (max - min) * 0.08 || 1;
  max += pad5; min -= pad5;
  const y = (p) => padT + plotH - ((p - min) / (max - min)) * plotH;

  ctx.font = "11px monospace";
  ctx.textBaseline = "middle";
  for (let i = 0; i <= 4; i++) {
    const p = min + (i / 4) * (max - min);
    const yy = y(p);
    ctx.strokeStyle = "#1e2937"; ctx.beginPath();
    ctx.moveTo(padL, yy); ctx.lineTo(padL + plotW, yy); ctx.stroke();
    ctx.fillStyle = "#8b98a9";
    ctx.fillText(p.toFixed(2), padL + plotW + 8, yy);
  }

  const n = valid.length;
  const step = plotW / n;
  const bw = Math.min(step * 0.62, 26);
  const maxLabels = Math.max(2, Math.floor(plotW / 46));
  const labelEvery = Math.max(1, Math.ceil(n / maxLabels));

  valid.forEach((c, i) => {
    const cx = padL + step * (i + 0.5);
    const afterSplit = o.splitAt != null && i >= o.splitAt;
    const col = afterSplit ? (c.c >= c.o ? "#86efac" : "#fbbf24")
                           : (c.c >= c.o ? "#2dd4a7" : "#fb7185");
    ctx.strokeStyle = col; ctx.lineWidth = 1;
    ctx.beginPath(); ctx.moveTo(cx, y(c.h)); ctx.lineTo(cx, y(c.l)); ctx.stroke();
    const top = y(Math.max(c.o, c.c)), bot = y(Math.min(c.o, c.c));
    ctx.fillStyle = col;
    ctx.fillRect(cx - bw / 2, top, bw, Math.max(1.5, bot - top));
    if (i % labelEvery === 0 || n <= 4) {
      const label = fmtTs(c.t).slice(11);
      const tw = ctx.measureText(label).width;
      const lx = Math.max(padL + tw / 2 + 2, Math.min(cx, padL + plotW - tw / 2 - 2));
      ctx.fillStyle = "#8b98a9"; ctx.textAlign = "center";
      ctx.fillText(label, lx, cssH - padB / 2 + 2);
      ctx.textAlign = "start";
    }
  });

  // pemisah putus-putus + garis sambung (opsional)
  if (o.splitAt != null) {
    const sx = padL + step * o.splitAt;
    ctx.strokeStyle = "#f2c14e"; ctx.setLineDash([6, 5]); ctx.lineWidth = 2;
    ctx.beginPath(); ctx.moveTo(sx, padT); ctx.lineTo(sx, cssH - padT); ctx.stroke();
    ctx.setLineDash([]);
    ctx.fillStyle = "#f2c14e"; ctx.font = "11px monospace";
    if (o.labelLeft)  { ctx.textAlign = "left"; ctx.fillText(o.labelLeft,  padL + 4, padT + 8);  ctx.textAlign = "start"; }
    if (o.labelRight) { ctx.textAlign = "left"; ctx.fillText(o.labelRight, sx + 6,  padT + 8);  ctx.textAlign = "start"; }
  }
}

// Panel analisa: pola historis vs perilaku setelahnya
function drawComparison(canvas, comp) {
  if (!comp) {
    drawCandles(canvas, null, "belum ada pola tercocok yang memenuhi ambang");
    return;
  }
  const all = [...(comp.pattern_candles || []), ...(comp.following_candles || [])];
  drawCandles(canvas, all, null, {
    splitAt: (comp.pattern_candles || []).length,
    labelLeft:  `POLA · ${comp.similarity_pct != null ? comp.similarity_pct.toFixed(2) : "-"}%`,
    labelRight: "AKIBAT · aktual",
  });
}

// Panel prediksi id crossings topk_median: candle median + band 80% + badge prob arah
function drawPredictions(canvas, pred, band, direction, noteText) {
  const o = {};
  const dpr = window.devicePixelRatio || 1;
  const cssW = canvas.clientWidth || 1000;
  const cssH = canvas.clientHeight || Number(canvas.getAttribute("height")) || 220;
  canvas.width = Math.round(cssW * dpr);
  canvas.height = Math.round(cssH * dpr);
  const ctx = canvas.getContext("2d");
  ctx.scale(dpr, dpr);

  ctx.fillStyle = "#0a1019";
  ctx.fillRect(0, 0, cssW, cssH);
  const valid = (pred || []).filter(c =>
    [c.o, c.h, c.l, c.c].every(v => typeof v === "number"));
  if (valid.length === 0) {
    drawCandles(canvas, null, noteText || "belum ada data");
    return;
  }

  const padL = 8, padR = 64, padT = 22, padB = 20;
  const plotW = cssW - padL - padR;
  const plotH = cssH - padT - padB;

  // skala: candle + band dipertimbangkan
  let max = Math.max(...valid.map(c => c.h));
  let min = Math.min(...valid.map(c => c.l));
  const bnd = (band || []).filter(b => b && typeof b.p10 === "number" && typeof b.p90 === "number");
  if (bnd.length) {
    max = Math.max(max, ...bnd.map(b => b.p90));
    min = Math.min(min, ...bnd.map(b => b.p10));
  }
  const pad5 = (max - min) * 0.10 || 1;
  max += pad5; min -= pad5;
  const y = (p) => padT + plotH - ((p - min) / (max - min)) * plotH;

  ctx.font = "11px monospace";
  ctx.textBaseline = "middle";
  for (let i = 0; i <= 4; i++) {
    const p = min + (i / 4) * (max - min);
    const yy = y(p);
    ctx.strokeStyle = "#1e2937"; ctx.beginPath();
    ctx.moveTo(padL, yy); ctx.lineTo(padL + plotW, yy); ctx.stroke();
    ctx.fillStyle = "#8b98a9";
    ctx.fillText(p.toFixed(2), padL + plotW + 8, yy);
  }

  const n = valid.length;
  const step = plotW / n;
  const bw = Math.min(step * 0.62, 26);
  const maxLabels = Math.max(2, Math.floor(plotW / 46));
  const labelEvery = Math.max(1, Math.ceil(n / maxLabels));

  // ---- band 80% (p10-p90) dulu, agar berada di belakang candle ----
  ctx.fillStyle = "rgba(212,160,23,0.16)";
  ctx.strokeStyle = "rgba(212,160,23,0.35)";
  bnd.forEach((b, idx) => {
    const cx = padL + step * (idx + 0.5);
    const top = y(b.p90), bot = y(b.p10);
    ctx.fillRect(cx - step / 2 + 1, top, step - 2, Math.max(2, bot - top));
    ctx.strokeRect(cx - step / 2 + 1, top, step - 2, Math.max(2, bot - top));
  });

  // ---- candle median ----
  valid.forEach((c, i) => {
    const cx = padL + step * (i + 0.5);
    const col = c.c >= c.o ? "#2dd4a7" : "#fb7185";
    ctx.strokeStyle = col; ctx.lineWidth = 1;
    ctx.beginPath(); ctx.moveTo(cx, y(c.h)); ctx.lineTo(cx, y(c.l)); ctx.stroke();
    const top = y(Math.max(c.o, c.c)), bot = y(Math.min(c.o, c.c));
    ctx.fillStyle = col;
    ctx.fillRect(cx - bw / 2, top, bw, Math.max(1.5, bot - top));
    // label waktu ringkas (adaptif)
    if (i % labelEvery === 0 || n <= 4) {
      const label = fmtTs(c.t).slice(11);
      const tw = ctx.measureText(label).width;
      const lx = Math.max(padL + tw / 2 + 2, Math.min(cx, padL + plotW - tw / 2 - 2));
      ctx.fillStyle = "#8b98a9"; ctx.textAlign = "center";
      ctx.fillText(label, lx, cssH - padB / 2 + 2);
      ctx.textAlign = "start";
    }
  });

  // ---- badge probabilitas arah -> dipindah ke tabel terpisah ----
  ctx.font = "11px monospace";
}

// tabel per-index: median OHLC + band 80% + probabilitas arah (kolom sendiri)
function renderPredTable(pred, band, direction) {
  const tb = $("pred-table").querySelector("tbody");
  tb.innerHTML = "";
  const has = (pred || []).filter(c => [c.o, c.h, c.l, c.c].every(v => typeof v === "number"));
  if (has.length === 0) {
    tb.innerHTML = `<tr><td colspan="9" style="color:var(--muted)">belum ada data prediksi</td></tr>`;
    return;
  }
  has.forEach((c, idx) => {
    const b = (band || [])[idx] || {};
    const s = (direction || [])[idx] || {};
    const tr = document.createElement("tr");
    const upPct = s.n ? Math.round(s.up / s.n * 100) : null;
    const dnPct = s.n ? 100 - upPct : null;
    const dirTxt = s.n
      ? `<span style="color:${upPct >= 55 ? '#2dd4a7' : upPct <= 45 ? '#fb7185' : '#8b98a9'}">${upPct}% naik</span> · ${dnPct}% turun`
      : "-";
    const bandTxt = (typeof b.p10 === "number")
      ? `${b.p10.toFixed(2)} – ${b.p90.toFixed(2)}`
      : "-";
    tr.innerHTML = `<td>${idx + 1}</td>
      <td>${fmtTs(c.t).slice(11)}</td>
      <td>${c.o.toFixed(2)}</td>
      <td style="color:#2dd4a7">${c.h.toFixed(2)}</td>
      <td style="color:#fb7185">${c.l.toFixed(2)}</td>
      <td>${c.c.toFixed(2)}</td>
      <td style="color:#f2c14e">${bandTxt}</td>
      <td>${dirTxt}</td>
      <td>${s.n || "-"}</td>`;
    tb.appendChild(tr);
  });
}

// Saran riset: Entry/SL/TP/R:R dari prediksi (band 80% + median + prob arah).
// SL = band 80% candle yang sama (p10 utk BUY / p90 utk SELL) — sinkron dengan kolom
// "Band 80%" di Tabel Prediksi; TP = median close candle ke-N; prob 45–55% = netral.
// SEMUA candle selalu tampil — baris yang tak layak diberi alasan di kolom Status,
// tidak dibuang diam-diam (perbaikan sinkron tabel prediksi vs saran, 11 Nov 2026).
// TANPA transaksi otomatis — hanya tampilan level, eksekusi manual di MT5.
function sugRow(r) {
  const tr = document.createElement("tr");
  const fmt = (v) => (typeof v === "number") ? v.toFixed(2) : "-";
  const col = r.arah === "BUY" ? "#2dd4a7" : r.arah === "SELL" ? "#fb7185" : "#8b98a9";
  const bold = (r.arah === "BUY" || r.arah === "SELL") ? "font-weight:bold" : "";
  const tone = r.tone === "ok" ? "#2dd4a7" : r.tone === "warn" ? "#f2c14e" : "#8b98a9";
  const rrTxt = (typeof r.rr === "number")
    ? `<span style="color:${r.rr >= 2 ? "#2dd4a7" : r.rr >= 1 ? "#f2c14e" : "#8b98a9"}">1 : ${r.rr.toFixed(1)}</span>`
    : "-";
  tr.innerHTML = `<td style="color:${col};${bold}">${r.arah}</td>
    <td>${r.t}</td>
    <td>${r.anchorT}</td>
    <td>${fmt(r.entry)}</td>
    <td style="color:#fb7185">${fmt(r.sl)}</td>
    <td style="color:#2dd4a7">${fmt(r.tp)}</td>
    <td>${rrTxt}</td>
    <td>${r.prob}</td>
    <td>${r.n}</td>
    <td style="color:${tone}">${r.status}</td>`;
  return tr;
}

function renderSuggestions(d) {
  const tb = $("sug-table").querySelector("tbody");
  tb.innerHTML = "";
  const actual = d.actual_candles || [];
  const anchor = actual.length ? actual[actual.length - 1].c : null;
  const anchorT = actual.length ? fmtTs(actual[actual.length - 1].t).slice(11) : "-";
  const pred = d.predicted_candles || [], band = d.predict_band || [], dr = d.predict_direction || [];

  // Tren (cermin executor: EMA `trend_period` vs candle terakhir, 12 Nov 2026). Server kirim
  // d.trend hasil hitung sama dgn eksekutor — bila tak ada, anggap SIDEWAYS.
  const ec = d.auto_trade_cfg || {};
  const trendOn = ec.trend_filter !== false;
  const rrMin = (typeof ec.rr_min === "number") ? ec.rr_min : 1.0;
  const rrMinTrend = (typeof ec.rr_min_trend === "number") ? ec.rr_min_trend : 0.3;
  const trend = (d.trend && d.trend.dir) ? d.trend : { dir: "SIDE" };
  const tLbl = { UP: "NAIK", DOWN: "TURUN", SIDE: "SIDEWAYS" }[trend.dir] || "-";
  const tEl = $("sug-trend");
  if (tEl) {
    const tCol = trend.dir === "UP" ? "#2dd4a7" : trend.dir === "DOWN" ? "#fb7185" : "#8b98a9";
    tEl.textContent = trendOn ? `Tren: ${tLbl}` : "Tren: (filter mati)";
    tEl.style.color = tCol;
  }

  if (typeof anchor !== "number") {
    tb.innerHTML = `<tr><td colspan="10" style="color:var(--muted)">belum ada candle aktual sebagai anchor</td></tr>`;
    return;
  }

  // Filter (permintaan user 11-12 Nov 2026): sinyal searah tren boleh R:R
  // longgar (rr_min_trend), sinyal lawan tren diblok walau R:R besar,
  // sideways pakai rr_min normal. Mode "mean" tidak punya band -> eksekutor
  // menolak; tabel juga tidak menampilkan saran (audit 12 Nov 2026).
  if (d.predict_mode && d.predict_mode !== "topk_median") {
    tb.innerHTML = `<tr><td colspan="10" style="color:var(--muted)">mode prediksi "mean" tidak punya band 80% — saran & eksekusi hanya tersedia di mode topk_median</td></tr>`;
    return;
  }
  let shown = 0;
  pred.forEach((c, idx) => {
    const b = band[idx] || {}, s = dr[idx] || {};
    const t = (c.t != null) ? fmtTs(c.t).slice(11) : "-";
    const tp = (typeof c.c === "number") ? c.c : null;
    const upPct = s.n ? s.up / s.n * 100 : null;
    const bandOk = (typeof b.p10 === "number" && typeof b.p90 === "number");
    if (!tp || upPct == null || !bandOk) return;          // slot kosong / sampel kurang

    if (upPct > 45 && upPct < 55) return;                 // netral
    const arah = upPct >= 55 ? "BUY" : "SELL";
    const sl = arah === "BUY" ? b.p10 : b.p90;            // band 80% candle yang sama
    const reward = arah === "BUY" ? tp - anchor : anchor - tp;
    const risk   = arah === "BUY" ? anchor - sl : sl - anchor;
    if (risk <= 0 || reward <= 0) return;                 // band salah sisi / reward tidak positif
    const rr = reward / risk;
    const aligned = trendOn && ((arah === "BUY" && trend.dir === "UP") ||
                                (arah === "SELL" && trend.dir === "DOWN"));
    const anti = trendOn && ((arah === "BUY" && trend.dir === "DOWN") ||
                             (arah === "SELL" && trend.dir === "UP"));
    if (anti) return;                                     // lawan tren: diblok
    const need = aligned ? rrMinTrend : rrMin;            // searah tren = longgar
    if (rr < need) return;
    const probTxt = `${Math.round(upPct)}% naik · ${100 - Math.round(upPct)}% turun`;
    tb.appendChild(sugRow({ arah, t, anchorT, entry: anchor, sl, tp, rr,
      prob: probTxt, n: s.n,
      status: aligned && rr < 1 ? `layak · tren ${tLbl} (R:R longgar)` : "layak",
      tone: "ok" }));
    shown++;
  });

  if (!shown) {
    tb.innerHTML = `<tr><td colspan="10" style="color:var(--muted)">tidak ada sinyal layak saat ini — sisanya netral, R:R di bawah ambang, atau diblok tren</td></tr>`;
  }
}

// ---------- eksekutor (demo only) ----------
async function renderExecutor() {
  let e;
  try {
    e = await (await fetch("/api/executor")).json();
  } catch { return; }
  const badge = $("exec-badge");
  if (!badge) return;
  const modeBadge = $("mode-badge");
  if (modeBadge) {
    modeBadge.textContent = e.enabled
      ? "Riset + eksekusi DEMO otomatis"
      : "Riset saja · Tanpa transaksi otomatis";
    modeBadge.style.color = e.enabled ? "#f2c14e" : "";
  }
  if (e.enabled) {
    badge.textContent = "DEMO AKTIF";
    badge.style.color = e.signal_active ? "#2dd4a7" : "#f2c14e";
  } else {
    badge.textContent = "MATI (auto_trade.enabled = false)";
    badge.style.color = "#8b98a9";
  }

  // Hero eksekutor + chip sinyal aktif
  const es = $("exec-state");
  if (es) {
    es.textContent = e.enabled
      ? (e.signal_active ? "AKTIF · SINYAL" : "AKTIF · MENUNGGU")
      : "NONAKTIF";
    es.classList.toggle("is-on", !!e.enabled);
    es.classList.toggle("is-off", !e.enabled);
  }
  setText("exec-lot", e.lot ?? "-");
  setText("exec-lot-strong", e.lot_strong ?? "-");
  setText("exec-max", e.max_positions ?? "-");
  setText("exec-prob-min", e.prob_min != null ? e.prob_min + "%" : "-");
  setText("exec-rr", e.rr_min != null ? "1:" + Number(e.rr_min).toFixed(2) : "-");
  setText("exec-hero-reason", e.reason || "-");

  const chips = $("active-signals");
  if (chips) {
    const sigs = e.active_signals || [];
    chips.innerHTML = "";
    if (!sigs.length) {
      chips.innerHTML = '<span class="muted">tidak ada sinyal aktif saat ini</span>';
    } else {
      sigs.forEach(s => {
        const chip = document.createElement("span");
        const side = s.side === "BUY" ? "buy" : s.side === "SELL" ? "sell" : "";
        chip.className = "signal-chip " + side;
        const rr = (typeof s.rr === "number") ? s.rr.toFixed(2) : "-";
        const lot = (s.lot != null) ? s.lot : "-";
        chip.innerHTML = `<b>${s.side}</b> #${(s.idx ?? 0) + 1} <span class="chip-lot">${lot} lot</span> · 1:${rr}`;
        chips.appendChild(chip);
      });
    }
  }

  const sig = (e.active_signals || [])
    .map(s => `${s.side} #${s.idx + 1} 1:${s.rr}`).join(", ") || "-";
  const tL = e.trend && e.trend.dir
    ? ({ UP: "NAIK", DOWN: "TURUN", SIDE: "SIDEWAYS" }[e.trend.dir] || "-") : "-";
  $("exec-note").textContent =
    `${e.reason || "-"} · lot ${e.lot}${e.lot_strong ? ` (kuat ${e.lot_strong} @ prob ≥ ${e.prob_min ?? "-"}%)` : ""} · ` +
    `maks ${e.max_positions} posisi · R:R min ${e.rr_min}${e.trend_filter ? ` (searah tren ${e.rr_min_trend ?? "-"})` : ""} · ` +
    `tren ${tL} · symbol ${e.symbol} · sinyal: ${sig}`;
  const tb = $("exec-table").querySelector("tbody");
  tb.innerHTML = "";
  const log = (e.exec_log || []).slice().reverse();   // terbaru di atas
  if (!log.length) {
    tb.innerHTML = `<tr><td colspan="7" style="color:var(--muted)">belum ada eksekusi — pastikan EA XAUUSDPatternExecutor terpasang di chart MT5 (akun demo)</td></tr>`;
    return;
  }
  log.forEach(r => {
    const ok = r.result === "ok";
    const col = ok ? "#2dd4a7" : r.result === "refuse" ? "#f2c14e" : "#fb7185";
    const tr = document.createElement("tr");
    const colSide = r.side === "BUY" ? "#2dd4a7"
                  : r.side === "SELL" ? "#fb7185"
                  : r.side && r.side.startsWith("CLOSE") ? "#f2c14e" : "#8b98a9";
    tr.innerHTML = `<td>${fmtTs(r.epoch).slice(11) || "-"}</td>
      <td>${r.id}</td>
      <td style="color:${colSide}">${r.side}</td>
      <td>${r.retcode}</td>
      <td>${r.ticket || "-"}</td>
      <td style="color:${col};font-weight:${ok ? "bold" : "normal"}">${r.result}</td>
      <td style="color:var(--muted)">${r.reason || "-"}</td>`;
    tb.appendChild(tr);
  });
}

// ---------- hero / sparkline ----------
let _sparkData = [];
let _heroBusy = false;

function drawSparkline(candles) {
  const canvas = $("sparkline");
  if (!canvas) return;
  if (candles) {
    _sparkData = candles.filter(c =>
      [c.o, c.h, c.l, c.c].every(v => typeof v === "number"));
  }
  const valid = _sparkData;
  const dpr = window.devicePixelRatio || 1;
  const cssW = canvas.clientWidth || 320;
  const cssH = 64;
  canvas.width = Math.round(cssW * dpr);
  canvas.height = Math.round(cssH * dpr);
  canvas.style.height = cssH + "px";
  const ctx = canvas.getContext("2d");
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, cssW, cssH);
  if (valid.length < 2) return;

  const closes = valid.map(c => c.c);
  let lo = Math.min(...closes), hi = Math.max(...closes);
  const pad = (hi - lo) * 0.18 || 1;
  lo -= pad; hi += pad;
  const x = (i) => 1 + (i / (valid.length - 1)) * (cssW - 2);
  const y = (v) => cssH - 4 - ((v - lo) / (hi - lo)) * (cssH - 8);
  const up = closes[closes.length - 1] >= closes[0];
  const col = up ? "#2dd4a7" : "#fb7185";

  const grad = ctx.createLinearGradient(0, 0, 0, cssH);
  grad.addColorStop(0, up ? "rgba(45,212,167,0.24)" : "rgba(251,113,133,0.22)");
  grad.addColorStop(1, "rgba(5,8,13,0)");
  ctx.beginPath();
  ctx.moveTo(x(0), cssH);
  valid.forEach((c, i) => ctx.lineTo(x(i), y(c.c)));
  ctx.lineTo(x(valid.length - 1), cssH);
  ctx.closePath();
  ctx.fillStyle = grad;
  ctx.fill();

  ctx.beginPath();
  valid.forEach((c, i) => {
    const px = x(i), py = y(c.c);
    if (i) ctx.lineTo(px, py); else ctx.moveTo(px, py);
  });
  ctx.strokeStyle = col;
  ctx.lineWidth = 1.7;
  ctx.lineCap = "round";
  ctx.lineJoin = "round";
  ctx.stroke();

  const lx = x(valid.length - 1), ly = y(closes[closes.length - 1]);
  ctx.beginPath();
  ctx.arc(lx, ly, 5.5, 0, Math.PI * 2);
  ctx.fillStyle = up ? "rgba(45,212,167,0.16)" : "rgba(251,113,133,0.16)";
  ctx.fill();
  ctx.beginPath();
  ctx.arc(lx, ly, 2.5, 0, Math.PI * 2);
  ctx.fillStyle = col;
  ctx.fill();
}

async function refreshHeroPrice() {
  if (_heroBusy) return;
  _heroBusy = true;
  try {
    const r = await fetch("/api/candles?count=60");
    if (!r.ok) return;
    const d = await r.json();
    const c = (d.candles || []).filter(x =>
      [x.o, x.h, x.l, x.c].every(v => typeof v === "number"));
    if (!c.length) return;
    const last = c[c.length - 1];
    const prev = c.length > 1 ? c[c.length - 2] : last;
    const chg = last.c - prev.c;
    const pct = prev.c ? (chg / prev.c) * 100 : 0;
    setText("hero-price", last.c.toFixed(2));
    const ch = $("hero-change");
    if (ch) {
      ch.textContent = `${chg >= 0 ? "+" : ""}${chg.toFixed(2)} (${pct >= 0 ? "+" : ""}${pct.toFixed(2)}%)`;
      ch.className = "change " + (chg > 0 ? "up" : chg < 0 ? "down" : "neutral");
    }
    setText("hero-time", fmtTs(last.t));
    setText("hero-open", last.o.toFixed(2));
    setText("hero-high", last.h.toFixed(2));
    setText("hero-low", last.l.toFixed(2));
    setText("hero-close", last.c.toFixed(2));
    drawSparkline(c);
  } catch (e) {
    /* polling harga gagal sesekali tidak perlu mengganggu UI */
  } finally {
    _heroBusy = false;
  }
}

function renderHero(d) {
  const t = d.trend || {};
  const dir = t.dir === "UP" ? "UP" : t.dir === "DOWN" ? "DOWN" : "SIDE";
  const lbl = { UP: "NAIK", DOWN: "TURUN", SIDE: "SIDEWAYS" }[dir];
  const cls = dir.toLowerCase();
  [$("trend-card"), $("trend-badge"), $("trend-label"), $("trend-arrow")].forEach(el => {
    if (!el) return;
    el.classList.remove("up", "down", "side");
    el.classList.add(cls);
  });
  setText("trend-badge", lbl);
  setText("trend-label", lbl);
  setText("trend-arrow", dir === "UP" ? "↗" : dir === "DOWN" ? "↘" : "→");
  setText("trend-period", t.period ?? d.auto_trade_cfg?.trend_period ?? 13);
  setText("trend-ema", typeof t.ema === "number" ? t.ema.toFixed(2) : "-");
  setText("trend-close", typeof t.close === "number" ? t.close.toFixed(2) : "-");
  const thumb = $("trend-thumb");
  if (thumb) thumb.style.left = dir === "UP" ? "82%" : dir === "DOWN" ? "18%" : "50%";

  const eb = $("engine-badge");
  if (eb) {
    const active = !!(d.engine && d.engine.active);
    eb.textContent = active ? "engine aktif" : "engine idle";
    eb.classList.toggle("idle", !active);
  }
  setText("param-summary", authState.loggedIn
    ? `ambang ${d.similarity_threshold_pct ?? "-"}% · top ${d.top_patterns ?? "-"} · N ${d.candles_per_pattern ?? "-"}`
    : "🔒 masuk untuk lihat");

  const actual = (d.actual_candles || []).filter(c =>
    [c.o, c.h, c.l, c.c].every(v => typeof v === "number"));
  const last = actual[actual.length - 1];
  if (last) {
    const chg = last.c - last.o;
    const pct = last.o ? (chg / last.o) * 100 : 0;
    setText("hero-price", last.c.toFixed(2));
    const ch = $("hero-change");
    if (ch) {
      ch.textContent = `${chg >= 0 ? "+" : ""}${chg.toFixed(2)} (${pct >= 0 ? "+" : ""}${pct.toFixed(2)}%)`;
      ch.className = "change " + (chg > 0 ? "up" : chg < 0 ? "down" : "neutral");
    }
    setText("hero-time", fmtTs(last.t));
    setText("hero-open", last.o.toFixed(2));
    setText("hero-high", last.h.toFixed(2));
    setText("hero-low", last.l.toFixed(2));
    setText("hero-close", last.c.toFixed(2));
    if (_sparkData.length < 2 || actual.length > _sparkData.length) drawSparkline(actual);
  }
}

// ---------- dashboard ----------
async function loadDashboard() {
  try {
    return await _doLoadDashboard();
  } catch (e) {
    console.error("loadDashboard:", e);
    const st = $("chart-status");
    if (st) st.textContent = "⚠ error: " + (e && e.message ? e.message : e);
    return null;
  }
}

async function _doLoadDashboard() {
  const d = await (await fetch("/api/dashboard")).json();
  const eng = d.engine || {};

  $("phase-badge").textContent =
    "Fase " + d.phase + (d.data_source.includes("dummy") ? " · Data Dummy" : " · Data Asli");
  $("data-source").textContent = d.data_source;
  $("pair-tf").textContent = d.pair + " · " + d.timeframe +
    " · jam: " + (d.time_display === "WIB" ? "WIB (GMT+7)"
                : d.time_display === "UTC" ? "UTC"
                : "MT5 server (GMT+2/3)");
  window.__timeOff = d.time_offset_hours || 0;
  document.title = d.pair + " Pattern Lab";

  // Status koneksi & freshness di topbar
  const src = d.data_source || "";
  if (src.startsWith("stale") || src.includes("gap")) setConnection("is-stale", "stale");
  else if (src.includes("PASAR TUTUP")) setConnection("is-stale", "pasar tutup");
  else if (src.toLowerCase().includes("dummy")) setConnection("is-off", "data dummy");
  else setConnection("is-live", "live");
  setText("last-update", fmtTs(d.generated_at));
  renderHero(d);

  $("similarity").textContent = fmtPct(d.similarity_pct);
  $("threshold-view").textContent = d.similarity_threshold_pct;
  $("topn-view").textContent = d.top_patterns;
  // tampilkan mode prediksi aktif di samping heading panel prediksi
  const mv = $("pred-mode-view");
  if (mv) mv.textContent =
    d.predict_mode === "topk_median"
      ? (d.predict_mode + " — Top " + (d.predict_top_k || "-") + " pola")
      : "rata-rata pola (lama)";
  const Nc = d.candles_per_pattern || 10;
  const lens = document.querySelectorAll("#len-view-pred");
  lens.forEach(el => (el.textContent = Nc));
  $("matched-at").textContent = fmtTs(d.matched_pattern_time);
  if (authState.loggedIn && !paramDirty) {
    $("predict-mode").value = d.predict_mode || "topk_median";
    $("predict-k").value = d.predict_top_k || 10;
  }

  // Arah estimasi candle pertama
  const first = (d.predicted_candles || [])[0];
  if (first && typeof first.c === "number") {
    const dir = first.c >= first.o ? "NAIK" : "TURUN";
    $("direction").textContent = dir;
    $("direction").style.color = first.c >= first.o ? "#2dd4a7" : "#fb7185";
  } else {
    $("direction").textContent = "-";
    $("direction").style.color = "";
  }

  // Chart interaktif ditangani IChart. Fallback bila IChart gagal dimuat:
  if (!ichart) {
    const cEl = $("chart-interactive");
    if (cEl) drawCandles(cEl, d.actual_candles);
  } else {
    // update status
    const src = d.data_source || "";
    const st = $("chart-status");
    if (st) st.textContent =
      src.startsWith("stale") ? "⚠ stale — DB " + fmtTs(d.actual_candles?.slice(-1)[0]?.t)
                              : src.startsWith("PASAR TUTUP") ? "⏸ " + src.slice(0, 60) + "…"
                              : "✅ live — " + src;
  }

  const comp = d.comparison;
  if (comp) {
    drawComparison($("chart-comparison"), comp);
  } else {
    drawCandles($("chart-comparison"), null,
      eng.active ? "tidak ada pola yang memenuhi ambang" : "engine belum berjalan");
  }
  // panel prediksi: band di canvas + tabel statistik terpisah
  if (d.predict_mode === "topk_median" && (d.predict_band || []).some(b => b && b.p10 != null)) {
    drawPredictions($("chart-predicted"), d.predicted_candles,
                    d.predict_band, d.predict_direction,
                    eng.active ? null : "engine belum berjalan");
  } else {
    drawCandles($("chart-predicted"), d.predicted_candles,
      eng.active ? "tidak ada pola yang memenuhi threshold" : "engine belum berjalan");
  }
  renderPredTable(d.predicted_candles, d.predict_band, d.predict_direction);
  renderSuggestions(d);

  // Cakupan data
  const cv = d.coverage;
  if (cv) {
    const warn = cv.has_gap ? " · ⚠ ada gap data" : "";
    const targetYears = Number(cv.target_years || 20);
    const pctTarget = Math.max(0, Math.min(100, Number(cv.percent_of_target ?? 0) || 0));
    $("coverage-big").textContent = cv.span_years.toFixed(2) + " tahun rentang · " + cv.bars.toLocaleString("id-ID") + " candle (" + cv.fill_pct + "% terisi)";
    $("coverage-sub").textContent =
      `${fmtTs(cv.from)} s/d ${fmtTs(cv.to)} · ${cv.percent_of_target}% dari target ${targetYears} tahun` + warn;
    setText("coverage-pct", pctTarget.toFixed(1) + "% dari target");
    setText("coverage-badge", cv.has_gap ? "⚠ gap data" : "kontinu");
    const bar = $("coverage-bar");
    if (bar) bar.style.width = pctTarget + "%";
  } else {
    $("coverage-big").textContent = "-";
    $("coverage-sub").textContent = "database kosong";
    setText("coverage-pct", "-");
    setText("coverage-badge", "kosong");
    const bar = $("coverage-bar");
    if (bar) bar.style.width = "0%";
  }

  renderTopMatches(eng.top_matches || []);
  await Promise.all([renderHistory(), renderAccuracy(), renderExecutor()]);

  if (authState.loggedIn && !paramDirty) {
    $("session").value = d.prioritize_session || "Asia";
    if ($("time-display")) $("time-display").value = d.time_display || "MT5";
    $("threshold").value = d.similarity_threshold_pct;
    $("top-n").value = d.top_patterns;
    $("candles-n").value = d.candles_per_pattern || 10;
  }

  return d;
}

// ---------- top matches ----------
function renderTopMatches(matches) {
  const tb = $("top-match-table").querySelector("tbody");
  tb.innerHTML = "";
  if (matches.length === 0) {
    tb.innerHTML = `<tr><td colspan="5" style="color:var(--muted)">belum ada pola yang memenuhi threshold</td></tr>`;
    return;
  }
  matches.forEach((m, i) => {
    const tr = document.createElement("tr");
    tr.innerHTML = `<td>#${i + 1}</td>
      <td>${m.session}</td>
      <td>${fmtTs(m.pattern_start_t)}</td>
      <td style="color:#f2c14e">${fmtPct(m.similarity_pct)}</td>
      <td>${m.predicted_start_t != null ? "ada sampel" : "ujung riwayat"}</td>`;
    tb.appendChild(tr);
  });
}

// ---------- riwayat ----------
async function renderHistory() {
  const d = await (await fetch("/api/history")).json();
  const tb = $("history-table").querySelector("tbody");
  tb.innerHTML = "";
  const total = (d.history || []).length;
  setText("history-count", total ? `${Math.min(10, total)} dari ${total} run` : "0 run");
  if (!d.history || d.history.length === 0) {
    tb.innerHTML = `<tr><td colspan="7" style="color:var(--muted)">belum ada run prediksi tersimpan</td></tr>`;
    return;
  }
  d.history.slice(0, 10).forEach(h => {
    const evalTxt = h.n_evaluated > 0
      ? `${h.n_evaluated} idx · avg err ${h.avg_abs_error_usd ?? "-"} USD`
      : "menunggu candle matang";
    const tr = document.createElement("tr");
    tr.innerHTML = `<td>${fmtTs(h.run_at)}</td>
      <td>${fmtTs(h.last_candle_t)}</td>
      <td>${h.bars_count}</td>
      <td>${h.n_matches}</td>
      <td style="color:#f2c14e">${fmtPct(h.similarity_pct)}</td>
      <td style="color:${h.direction === "naik" ? "#2dd4a7" : h.direction ? "#fb7185" : ""}">${h.direction || "-"}</td>
      <td>${evalTxt}</td>`;
    tb.appendChild(tr);
  });
}

// ---------- akurasi ----------
async function renderAccuracy() {
  let a;
  try {
    a = await (await fetch("/api/accuracy")).json();
  } catch { return; }
  const ring = $("accuracy-ring");
  if (!a) return;
  setText("accuracy", a.avg_error_pct != null ? fmtPct(a.avg_error_pct) : "—");
  const v = a.direction_validation;
  const liveN = Number(a.direction_live_n) || 0;
  let hit = Number(a.hit_within_1usd_pct) || 0;
  let source = `${a.n_evaluated.toLocaleString("id-ID")} evaluasi harga`;
  if (liveN >= 200 && a.direction_live_hit_pct != null) {
    hit = Number(a.direction_live_hit_pct) || 0;
    source = `${liveN.toLocaleString("id-ID")} evaluasi arah live`;
  } else if (v && v.hit_pct != null) {
    hit = Number(v.hit_pct) || 0;
    source = `${v.n_signals.toLocaleString("id-ID")} sinyal · uji ${v.period}`;
  }
  setText("accuracy-hit", hit.toFixed(1) + "%");
  setText("accuracy-count", source);
  const high = v && v.high_hit_pct != null
    ? ` · high ${v.high_hit_pct}% (${v.n_high})` : "";
  const cov = v && v.coverage_pct != null ? ` · coverage ${v.coverage_pct}%` : "";
  const hit1 = a.hit_within_1usd_pct != null
    ? ` · hit ±$1 ${a.hit_within_1usd_pct}%` : "";
  const liveTxt = liveN
    ? ` · live ${liveN}${a.direction_live_hit_pct != null ? ` (${a.direction_live_hit_pct}%)` : ""}`
    : "";
  setText("accuracy-sub",
    `${source}${high}${cov}${hit1}${liveTxt} · MAE ${
      a.avg_abs_error_usd != null ? "$" + a.avg_abs_error_usd.toFixed(2) : "-"
    }/candle`);
  if (ring) ring.style.setProperty("--p", String(Math.max(0, Math.min(100, hit))));
}

// ---------- simpan parameter ----------
$("save-btn").addEventListener("click", async () => {
  if (!authState.loggedIn) {
    openAuthModal();
    return;
  }
  const payload = {
    prioritize_session: $("session").value,
    similarity_threshold_pct: Number($("threshold").value),
    top_patterns: Number($("top-n").value),
    candles_per_pattern: Number($("candles-n").value),
  };
  if ($("time-display"))    payload.time_display = $("time-display").value;
  if ($("predict-mode"))    payload.predict_mode = $("predict-mode").value;
  if ($("predict-k") && $("predict-k").value)
    payload.predict_top_k = Math.max(3, Math.min(50, Number($("predict-k").value)));
  const r = await fetch("/api/config", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  let res = {};
  try { res = await r.json(); } catch { res = {}; }
  if (r.status === 401) {
    authState.loggedIn = false;
    authState.user = null;
    authState.expiresAt = null;
    setAuthUI();
    openAuthModal();
    showLoginError("Sesi admin berakhir. Silakan masuk lagi.");
    return;
  }
  if (res.ok) paramDirty = false;
  const status = $("save-status");
  if (status) {
    status.textContent = res.ok ? "Tersimpan ✔" : "Gagal: " + (res.error || `HTTP ${r.status}`);
    status.style.color = res.ok ? "var(--green)" : "var(--red)";
  }
  setTimeout(() => {
    if (status) { status.textContent = ""; status.style.color = ""; }
  }, 2500);
  loadDashboard();
});

// ---------- countdown ----------
let intervalMin = 5 * 10;
let lastGen = 0;

function tickCountdown() {
  if (!lastGen) return;
  const perMs = intervalMin * 60000;
  let s = Math.round((toMs(lastGen) + perMs - Date.now()) / 1000);
  if (s <= 0) s = intervalMin * 60;   // siklus baru: jangan macet di 00:00
  $("countdown").textContent =
    String(Math.floor(s / 60)).padStart(2, "0") + ":" + String(s % 60).padStart(2, "0");
}

// ---------- toolbar chart interaktif ----------
function initChartToolbar() {
  // tombol jumlah candle
  document.querySelectorAll(".tb-btn[data-bars]").forEach(btn => {
    btn.addEventListener("click", () => {
      const n = parseInt(btn.dataset.bars);
      if (ichart) { ichart.setCount(n); updateCountUI(n); }
    });
  });

  // input manual
  $("bars-apply").addEventListener("click", () => {
    const n = parseInt($("bars-input").value);
    if (ichart && n >= 10 && n <= 600) { ichart.setCount(n); updateCountUI(n); }
  });
  $("bars-input").addEventListener("keydown", e => { if (e.key === "Enter") $("bars-apply").click(); });

  // tombol live
  $("go-live").addEventListener("click", () => {
    if (ichart) { ichart.goLive(); updateCountUI(ichart.bars()); }
  });
}

function updateCountUI(n) {
  $("bars-input").value = n;
  setText("live-count-view", n);
  document.querySelectorAll(".tb-btn[data-bars]").forEach(btn => {
    const on = parseInt(btn.dataset.bars) === n;
    btn.classList.toggle("active", on);
    btn.setAttribute("aria-pressed", on ? "true" : "false");
  });
}

// ---------- init ----------
async function init() {
  initAuthControls();
  await initAuth();
  const d = await loadDashboard();
  if (!d) return;                     // API gagal -> jangan crash, tunggu refresh
  intervalMin = d.timeframe === "M5" ? 5 * d.update_every_n_candles : 5 * 10;
  lastGen = d.generated_at;
  tickCountdown();
  setInterval(tickCountdown, 1000);

  // inisialisasi chart interaktif MT5-like
  if (typeof IChart !== "undefined") {
    try {
      ichart = await IChart.init("chart-interactive", 120);
      updateCountUI(ichart.bars());
      // default: auto-refresh ON (C+B) — mati/menyala via tombol ⟳ di toolbar
      const ab = $("chart-auto");
      if (ab) { window.__chartAuto = true; ab.textContent = "⟳ Auto: ON"; if (ichart.auto) ichart.auto(true); }
    } catch (e) {
      console.error("chart interaktif:", e);
      const st = $("chart-status");
      if (st) st.textContent = "⚠ chart gagal: " + e.message;
    }
  }

  initChartToolbar();

  // handler toggle ⟳ Auto berada di sini (elemen sudah pasti ada)
  const autoBtn = $("chart-auto");
  if (autoBtn) {
    autoBtn.addEventListener("click", () => {
      window.__chartAuto = !window.__chartAuto;
      autoBtn.textContent = "⟳ Auto: " + (window.__chartAuto ? "ON" : "OFF");
      if (ichart && ichart.auto) ichart.auto(window.__chartAuto);
    });
  }

  setInterval(() => {
    if (lastGen && Date.now() >= toMs(lastGen) + intervalMin * 60000) {
      lastGen = Date.now();   // restart countdown SEGERA (tidak macet di 00:00)
      loadDashboard().then(dd => { if (dd && dd.generated_at) lastGen = dd.generated_at; });
    }
  }, 15000);

  // Log eksekutor lebih cepat dari siklus candle (±20 dtk) supaya order
  // yang masuk langsung terlihat tanpa menunggu 5 menit (audit 12 Nov 2026).
  setInterval(() => { renderExecutor().catch(() => {}); }, 20000);

  // Harga hero + sparkline lebih segar dari siklus engine (30 dtk).
  refreshHeroPrice();
  setInterval(refreshHeroPrice, 30000);
}

// global untuk diakses dari toolbar sebelum init selesai
let ichart = null;

let _resizeTimer = null;
window.addEventListener("resize", () => {
  // Tunggu layout selesai sebelum membaca clientWidth/clientHeight.
  clearTimeout(_resizeTimer);
  _resizeTimer = setTimeout(() => {
    if (ichart) ichart.render && ichart.render();
    drawSparkline();
    loadDashboard();
  }, 180);
});

init();
