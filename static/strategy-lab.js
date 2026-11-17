"use strict";

const DATA_URL = "strategy-lab.json";
const CANDIDATE_KEY = "xauusd.strategyLab.candidates.v1";
const STAGES = ["Hipotesis", "Aturan", "Backtest", "Validasi EA", "Demo", "Promosi", "Ditolak"];

const state = { data: null, candidates: [] };
const $ = (id) => document.getElementById(id);

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text != null) node.textContent = text;
  return node;
}

function externalLink(url, label, className) {
  const a = el("a", className || "", label);
  a.href = url;
  a.target = "_blank";
  a.rel = "noopener";
  return a;
}

function skillName(id) {
  const skill = (state.data?.skills || []).find((s) => s.id === id);
  return skill ? skill.name : id;
}

function renderStats() {
  const skills = state.data?.skills || [];
  const live = state.candidates.filter((c) => c.stage === "Promosi").length;
  $("stat-skills").textContent = String(skills.length);
  $("stat-candidates").textContent = String(state.candidates.length);
  $("stat-live").textContent = String(live);
  $("skill-count-badge").textContent = `${skills.length} aktif`;
}

function renderPipeline() {
  const root = $("pipeline-list");
  root.replaceChildren();
  const items = state.data?.pipeline || [];
  if (!items.length) {
    root.appendChild(el("div", "candidate-empty", "Data pipeline belum tersedia."));
    return;
  }
  for (const step of items) {
    const card = el("article", "pipeline-step is-ready");
    const head = el("div", "pipeline-step-head");
    head.appendChild(el("span", "pipeline-n", String(step.n)));
    head.appendChild(el("span", "badge-soft", step.stage));
    card.appendChild(head);
    card.appendChild(el("h3", "", step.title));
    card.appendChild(el("p", "", step.desc));
    const chips = el("div", "pipeline-skills");
    for (const id of step.skills || []) {
      chips.appendChild(el("span", "pipeline-skill", skillName(id)));
    }
    card.appendChild(chips);
    root.appendChild(card);
  }
}

function renderSkills() {
  const root = $("skill-grid");
  root.replaceChildren();
  const skills = state.data?.skills || [];
  if (!skills.length) {
    root.appendChild(el("div", "candidate-empty", "Daftar skill belum tersedia."));
    return;
  }
  for (const skill of skills) {
    const card = el("article", "skill-card");
    const top = el("div", "skill-card-top");
    const titleWrap = el("div");
    titleWrap.appendChild(el("h3", "", skill.name));
    titleWrap.appendChild(el("div", "skill-source", `${skill.source} · ${skill.role}`));
    top.appendChild(titleWrap);
    top.appendChild(el("span", "skill-badge", "Terpasang"));
    card.appendChild(top);
    card.appendChild(el("p", "", skill.desc));
    const foot = el("div", "skill-card-foot");
    foot.appendChild(externalLink(skill.url, "Buka SKILL.md →"));
    foot.appendChild(el("span", "skill-license", skill.license));
    card.appendChild(foot);
    root.appendChild(card);
  }

  const skipped = state.data?.skipped || [];
  const note = $("skipped-note");
  if (skipped.length) {
    note.textContent = `Dilewati: ${skipped.map((s) => `${s.name} (${s.reason})`).join("; ")}`;
  } else {
    note.textContent = "";
  }
}

function renderConstraints() {
  const root = $("constraint-list");
  root.replaceChildren();
  for (const item of state.data?.constraints || []) {
    const row = el("div", "constraint-item");
    row.appendChild(el("span", "constraint-mark", "×"));
    const body = el("div");
    body.appendChild(el("strong", "", item.title));
    body.appendChild(el("p", "", item.text));
    row.appendChild(body);
    root.appendChild(row);
  }
}

function renderBrief() {
  $("brief-template").textContent = state.data?.brief || "";
}

function loadCandidates() {
  try {
    const raw = localStorage.getItem(CANDIDATE_KEY);
    const parsed = raw ? JSON.parse(raw) : [];
    state.candidates = Array.isArray(parsed) ? parsed.filter(validCandidate) : [];
  } catch (_) {
    state.candidates = [];
  }
  renderCandidates();
}

function validCandidate(c) {
  return c && typeof c === "object" && typeof c.name === "string" && c.name.trim();
}

function saveCandidates() {
  try {
    localStorage.setItem(CANDIDATE_KEY, JSON.stringify(state.candidates));
  } catch (_) {
    /* localStorage bisa diblokir; tracker tetap jalan di memori sesi ini. */
  }
  renderStats();
}

function renderCandidates() {
  const root = $("candidate-list");
  root.replaceChildren();
  if (!state.candidates.length) {
    root.appendChild(el("div", "candidate-empty",
      "Belum ada kandidat. Mulai dari template brief, lalu tambahkan kandidat pertama."));
    renderStats();
    return;
  }

  for (const candidate of state.candidates) {
    const row = el("article", "candidate-row");
    const main = el("div");
    main.appendChild(el("div", "candidate-name", candidate.name));
    main.appendChild(el("div", "candidate-hyp", candidate.hypothesis || "Hipotesis belum diisi."));
    const meta = el("div", "candidate-meta");
    meta.appendChild(el("span", "", `magic ${candidate.magic || "—"}`));
    meta.appendChild(el("span", "", candidate.slot || "slot belum dialokasikan"));
    if (candidate.updated) {
      meta.appendChild(el("span", "", `update ${formatDate(candidate.updated)}`));
    }
    main.appendChild(meta);
    if (candidate.notes) main.appendChild(el("div", "candidate-hyp", `Catatan: ${candidate.notes}`));
    row.appendChild(main);

    const stageWrap = el("div");
    stageWrap.appendChild(el("span", "candidate-stage", candidate.stage || "Hipotesis"));
    row.appendChild(stageWrap);

    const actions = el("div", "candidate-actions");
    const select = el("select");
    select.setAttribute("aria-label", `Ubah tahap ${candidate.name}`);
    for (const stage of STAGES) {
      const option = el("option", "", stage);
      option.value = stage;
      if (stage === candidate.stage) option.selected = true;
      select.appendChild(option);
    }
    select.addEventListener("change", () => {
      candidate.stage = select.value;
      candidate.updated = new Date().toISOString();
      saveCandidates();
      renderCandidates();
    });
    actions.appendChild(select);

    const del = el("button", "candidate-delete", "Hapus");
    del.type = "button";
    del.addEventListener("click", () => {
      if (!window.confirm(`Hapus kandidat "${candidate.name}"?`)) return;
      state.candidates = state.candidates.filter((c) => c.id !== candidate.id);
      saveCandidates();
      renderCandidates();
    });
    actions.appendChild(del);
    row.appendChild(actions);
    root.appendChild(row);
  }
  renderStats();
}

function formatDate(iso) {
  try {
    return new Date(iso).toLocaleString("id-ID", {
      day: "2-digit", month: "short", year: "numeric",
      hour: "2-digit", minute: "2-digit"
    });
  } catch (_) {
    return "—";
  }
}

function candidateId() {
  if (window.crypto && typeof window.crypto.randomUUID === "function") {
    return window.crypto.randomUUID();
  }
  return `cand-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

function bindForm() {
  const form = $("candidate-form");
  const addBtn = $("add-candidate");
  const cancelBtn = $("cancel-candidate");
  const resetBtn = $("reset-candidates");

  addBtn.addEventListener("click", () => {
    form.hidden = false;
    $("cand-name").focus();
  });
  cancelBtn.addEventListener("click", () => {
    form.hidden = true;
    form.reset();
  });

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    const name = $("cand-name").value.trim();
    const hypothesis = $("cand-hypothesis").value.trim();
    if (!name || !hypothesis) {
      window.alert("Nama strategi dan hipotesis wajib diisi.");
      return;
    }
    state.candidates.unshift({
      id: candidateId(),
      name,
      hypothesis,
      magic: $("cand-magic").value.trim(),
      slot: $("cand-slot").value,
      stage: $("cand-stage").value,
      notes: $("cand-notes").value.trim(),
      updated: new Date().toISOString()
    });
    saveCandidates();
    renderCandidates();
    form.reset();
    form.hidden = true;
  });

  resetBtn.addEventListener("click", () => {
    if (!state.candidates.length) return;
    if (!window.confirm("Hapus semua kandidat dari tracker lokal browser ini?")) return;
    state.candidates = [];
    saveCandidates();
    renderCandidates();
  });
}

function bindCopyBrief() {
  const btn = $("copy-brief");
  btn.addEventListener("click", async () => {
    const text = $("brief-template").textContent || "";
    try {
      await navigator.clipboard.writeText(text);
      btn.textContent = "Tersalin";
      window.setTimeout(() => { btn.textContent = "Salin"; }, 1500);
    } catch (_) {
      const area = document.createElement("textarea");
      area.value = text;
      area.style.position = "fixed";
      area.style.opacity = "0";
      document.body.appendChild(area);
      area.select();
      try { document.execCommand("copy"); btn.textContent = "Tersalin"; } catch (__) { btn.textContent = "Gagal"; }
      area.remove();
      window.setTimeout(() => { btn.textContent = "Salin"; }, 1500);
    }
  });
}

async function init() {
  if (window.__STRATEGY_LAB_DATA__ && typeof window.__STRATEGY_LAB_DATA__ === "object") {
    state.data = window.__STRATEGY_LAB_DATA__;
  } else {
    try {
      const response = await fetch(DATA_URL, { cache: "no-store" });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      state.data = await response.json();
    } catch (error) {
      $("pipeline-list").appendChild(el("div", "candidate-empty",
        `Gagal memuat data Strategy Lab: ${error.message}`));
      $("skill-grid").appendChild(el("div", "candidate-empty",
        "Periksa static/strategy-lab.json."));
      return;
    }
  }

  $("lab-updated").textContent = `update ${state.data.updated || "—"}`;
  renderPipeline();
  renderSkills();
  renderConstraints();
  renderBrief();
  loadCandidates();
  bindForm();
  bindCopyBrief();
  renderStats();
  initTester();
}

document.addEventListener("DOMContentLoaded", init);

// ---------------------------------------------------------------------------
// Strategy Tester — job backtest via /api/backtest/*
// ---------------------------------------------------------------------------
const BT = { jobId: null, resultJobId: null, timer: null, auth: false, summary: null, verdict: null };

function btSetStatus(kind, text) {
  const pill = $("bt-status-pill");
  if (pill) {
    pill.classList.remove("is-live", "is-stale", "is-off");
    if (kind) pill.classList.add(kind);
  }
  setText("bt-status", text || "idle");
}

function btSetAuth(loggedIn, user) {
  BT.auth = !!loggedIn;
  const badge = $("bt-auth");
  if (badge) {
    badge.textContent = loggedIn ? `admin: ${user || "admin"}` : "belum login";
    badge.style.color = loggedIn ? "var(--green)" : "var(--muted)";
    badge.style.borderColor = loggedIn ? "rgba(45,212,167,.25)" : "var(--line)";
  }
  if (loggedIn) $("bt-login").hidden = true;
}

function btNum(v, digits = 2, suffix = "") {
  return (v == null || !isFinite(Number(v))) ? "—" : Number(v).toFixed(digits) + suffix;
}

function btRenderMetrics(summary) {
  const root = $("bt-metrics");
  root.replaceChildren();
  const data = summary.data || {};
  const params = summary.params || {};
  const metrics = [
    ["Trades", summary.trades],
    ["Win rate", btNum(summary.win_rate_pct, 1, "%")],
    ["Net PnL", btNum(summary.net_pnl, 2, " USD")],
    ["Profit factor", summary.profit_factor == null ? "—" : btNum(summary.profit_factor, 3)],
    ["Max DD", btNum(summary.max_drawdown_pct, 2, "%")],
    ["Expectancy", btNum(summary.expectancy_per_trade, 2, " USD")],
    ["Tahun", btNum(summary.years, 2)],
    ["Bar", data.bars == null ? "—" : Number(data.bars).toLocaleString("id-ID")],
    ["Runtime", btNum(summary.runtime_sec, 1, " dtk")],
    ["Range", `${data.start || "—"} → ${data.end || "—"}`],
  ];
  for (const [label, value] of metrics) {
    const card = el("div", "bt-metric");
    card.appendChild(el("span", "bt-metric-label", label));
    card.appendChild(el("strong", "", String(value)));
    root.appendChild(card);
  }

  const table = $("bt-peryear");
  table.replaceChildren();
  const thead = el("thead");
  const hr = el("tr");
  for (const h of ["Tahun", "Trades", "Win rate", "Net PnL"]) hr.appendChild(el("th", "", h));
  thead.appendChild(hr);
  table.appendChild(thead);
  const tbody = el("tbody");
  const perYear = summary.per_year || {};
  for (const [year, item] of Object.entries(perYear)) {
    const tr = el("tr");
    tr.appendChild(el("td", "", year));
    tr.appendChild(el("td", "", String(item.trades ?? "—")));
    tr.appendChild(el("td", "", btNum(item.win_rate, 1, "%")));
    tr.appendChild(el("td", "", btNum(item.net_pnl, 2)));
    tbody.appendChild(tr);
  }
  table.appendChild(tbody);

  const files = [
    ["summary.json", "summary.json"],
    ["trades.csv", "trades.csv"],
    ["equity.csv", "equity.csv"],
    ["report.md", "report.md"],
    ["run.log", "log"],
  ];
  const froot = $("bt-files");
  froot.replaceChildren();
  froot.appendChild(el("span", "bt-files-label", "Unduh:"));
  for (const [name, label] of files) {
    const href = `/api/backtest/file/${encodeURIComponent(summary.__job_id || BT.jobId || "")}/${name}`;
    const a = el("a", "skill-link", label);
    a.href = href;
    a.target = "_blank";
    a.rel = "noopener";
    froot.appendChild(a);
  }
  $("bt-results").hidden = false;
}

async function btLoadResult(jobId) {
  try {
    const res = await fetch(`/api/backtest/result/${encodeURIComponent(jobId)}`, { cache: "no-store" });
    if (!res.ok) return false;
    const payload = await res.json();
    if (!payload.ok || !payload.summary) return false;
    const summary = payload.summary;
    summary.__job_id = jobId;
    BT.summary = summary;
    BT.resultJobId = jobId;
    BT.verdict = payload.verdict || null;
    btRenderMetrics(summary);
    btRenderVerdict(BT.verdict);
    const nameInput = $("bt-ea-name");
    if (nameInput) nameInput.value = `ema_cross_${jobId}`;
    return true;
  } catch (_) {
    return false;
  }
}

function btRenderHistory(jobs) {
  const root = $("bt-history");
  root.replaceChildren();
  if (!jobs || !jobs.length) {
    root.appendChild(el("div", "candidate-empty", "Belum ada run backtest."));
    return;
  }
  for (const job of jobs) {
    const row = el("div", "bt-history-row");
    const main = el("div");
    main.appendChild(el("div", "candidate-name", job.id));
    const m = job.metrics || {};
    const params = job.params || {};
    const range = params.start ? `${params.start} → ${params.end || "—"}` : "riwayat file";
    main.appendChild(el("div", "candidate-meta", range));
    const stats = el("div", "candidate-meta");
    stats.appendChild(el("span", "", `status ${job.status || "—"}`));
    if (m.trades != null) stats.appendChild(el("span", "", `trades ${m.trades}`));
    if (m.net_pnl != null) stats.appendChild(el("span", "", `net ${btNum(m.net_pnl, 2)}`));
    if (m.profit_factor != null) stats.appendChild(el("span", "", `PF ${btNum(m.profit_factor, 3)}`));
    if (m.max_drawdown_pct != null) stats.appendChild(el("span", "", `DD ${btNum(m.max_drawdown_pct, 2)}%`));
    main.appendChild(stats);
    row.appendChild(main);
    const actions = el("div", "candidate-actions");
    const view = el("button", "btn-ghost lab-small-btn", "Lihat");
    view.type = "button";
    view.addEventListener("click", async () => {
      const ok = await btLoadResult(job.id);
      if (!ok) alert("Hasil belum tersedia / job gagal.");
      else $("bt-results").scrollIntoView({ behavior: "smooth", block: "start" });
    });
    actions.appendChild(view);
    row.appendChild(actions);
    root.appendChild(row);
  }
}

async function btLoadJobs() {
  try {
    const res = await fetch("/api/backtest/jobs", { cache: "no-store" });
    if (!res.ok) return;
    const payload = await res.json();
    const jobs = payload.jobs || [];
    btRenderHistory(jobs);
    const running = jobs.find((j) => j.status === "running");
    if (running && !BT.jobId) {
      BT.jobId = running.id;
      btSetStatus("is-stale", "running");
      btStartPolling();
    }
  } catch (_) {
    /* silent */
  }
}

function btStartPolling() {
  if (BT.timer) clearInterval(BT.timer);
  BT.timer = setInterval(btPoll, 2500);
  btPoll();
}

async function btPoll() {
  if (!BT.jobId) return;
  try {
    const res = await fetch(`/api/backtest/status/${encodeURIComponent(BT.jobId)}`, { cache: "no-store" });
    if (!res.ok) return;
    const payload = await res.json();
    if (!payload.ok) return;
    const job = payload.job;
    const running = job.status === "running" || job.status === "queued";
    btSetStatus(running ? "is-stale" : (job.status === "done" ? "is-live" : "is-off"),
      job.status);
    $("bt-message").textContent = job.message || "";
    const log = $("bt-log");
    if (job.log_tail && job.log_tail.length) {
      log.hidden = false;
      log.textContent = job.log_tail.join("\n");
    }
    $("bt-cancel").hidden = !running;
    if (!running) {
      clearInterval(BT.timer);
      BT.timer = null;
      $("bt-cancel").hidden = true;
      if (job.status === "done") await btLoadResult(job.id);
      await btLoadJobs();
    }
  } catch (_) {
    /* silent, coba lagi */
  }
}

async function btStartRun(event) {
  event.preventDefault();
  const payload = {
    strategy: $("bt-strategy").value,
    start: $("bt-start").value,
    end: $("bt-end").value,
    fast: Number($("bt-fast").value),
    slow: Number($("bt-slow").value),
    atr: Number($("bt-atr").value),
    sl_atr: Number($("bt-sl").value),
    tp_atr: Number($("bt-tp").value),
    spread_points: Number($("bt-spread").value),
    lot: Number($("bt-lot").value),
  };
  try {
    const res = await fetch("/api/backtest/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await res.json().catch(() => ({}));
    if (res.status === 401) {
      $("bt-login").hidden = false;
      btSetStatus("is-off", "butuh login");
      $("bt-message").textContent = "Silakan login admin untuk menjalankan backtest.";
      return;
    }
    if (!data.ok) {
      btSetStatus("is-off", "ditolak");
      $("bt-message").textContent = data.error || `HTTP ${res.status}`;
      return;
    }
    BT.jobId = data.job_id;
    BT.resultJobId = null;
    BT.summary = null;
    BT.verdict = null;
    $("bt-results").hidden = true;
    $("bt-generate-msg").textContent = "";
    $("bt-log").hidden = true;
    $("bt-log").textContent = "";
    $("bt-cancel").hidden = false;
    btSetStatus("is-stale", "running");
    $("bt-message").textContent = "job dimulai…";
    btStartPolling();
  } catch (error) {
    btSetStatus("is-off", "gagal");
    $("bt-message").textContent = error.message;
  }
}

async function btCancelRun() {
  if (!BT.jobId) return;
  try {
    await fetch(`/api/backtest/cancel/${encodeURIComponent(BT.jobId)}`, { method: "POST" });
  } catch (_) { /* silent */ }
  btPoll();
}

async function btLogin(event) {
  event.preventDefault();
  const username = $("bt-user").value.trim();
  const password = $("bt-pass").value;
  try {
    const res = await fetch("/api/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok || !data.ok) {
      $("bt-login-error").textContent = data.error || "Login gagal.";
      return;
    }
    btSetAuth(true, data.user);
    $("bt-login-error").textContent = "";
    $("bt-pass").value = "";
  } catch (error) {
    $("bt-login-error").textContent = error.message;
  }
}


function btRenderVerdict(verdict) {
  const root = $("bt-verdict");
  root.replaceChildren();
  if (!verdict) return;
  const head = el("div", "bt-verdict-head");
  const badge = el("span", "bt-verdict-badge", verdict.verdict || "—");
  const v = String(verdict.verdict || "").toLowerCase();
  if (v.includes("layak")) badge.classList.add("is-pass");
  else if (v.includes("revisi")) badge.classList.add("is-warn");
  else badge.classList.add("is-fail");
  head.appendChild(badge);
  head.appendChild(el("span", "lab-note-inline", `skor ${verdict.score || "—"}`));
  root.appendChild(head);
  const gates = el("div", "bt-gates");
  for (const gate of verdict.gates || []) {
    const item = el("span", `bt-gate ${gate.pass ? "is-pass" : "is-fail"}`,
      `${gate.pass ? "✓" : "×"} ${gate.label}`);
    gates.appendChild(item);
  }
  root.appendChild(gates);
  const note = el("p", "lab-note");
  note.textContent = verdict.verdict === "Layak diuji"
    ? "Lolos gate dasar. Tetap butuh validasi MT5 dan demo."
    : "Belum lolos gate. Anda masih bisa membuat draft EA, tetapi sebaiknya revisi parameter dulu.";
  root.appendChild(note);
}

function btRenderGenerated(items, jobId) {
  const root = $("bt-generated");
  root.replaceChildren();
  if (!items || !items.length) {
    root.appendChild(el("div", "candidate-empty", "Belum ada EA generated."));
    return;
  }
  for (const item of items) {
    const row = el("div", "bt-generated-row");
    const a = el("a", "skill-link", item.file);
    a.href = `/api/backtest/ea/${encodeURIComponent(item.file)}`;
    a.target = "_blank";
    a.rel = "noopener";
    row.appendChild(a);
    row.appendChild(el("span", "lab-note-inline",
      `magic ${item.magic} · ${item.verdict || "—"}`));
    root.appendChild(row);
  }
}

async function btLoadGenerated() {
  try {
    const res = await fetch("/api/backtest/generated", { cache: "no-store" });
    if (!res.ok) return;
    const payload = await res.json();
    btRenderGenerated(payload.items || [], BT.jobId);
  } catch (_) { /* silent */ }
}

async function btGenerateEa() {
  const sourceJob = BT.resultJobId || BT.jobId;
  if (!sourceJob || !BT.summary) {
    $("bt-generate-msg").textContent = "Jalankan backtest dulu.";
    return;
  }
  if (BT.verdict && BT.verdict.verdict !== "Layak diuji") {
    if (!window.confirm("Hasil backtest belum lolos gate. Tetap buat draft EA?")) return;
  }
  const name = $("bt-ea-name").value.trim();
  const magicRaw = $("bt-ea-magic").value.trim();
  const payload = { job_id: sourceJob };
  if (name) payload.name = name;
  if (magicRaw) payload.magic = Number(magicRaw);
  $("bt-generate-msg").textContent = "membuat EA…";
  try {
    const res = await fetch("/api/backtest/generate-ea", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await res.json().catch(() => ({}));
    if (res.status === 401) {
      $("bt-login").hidden = false;
      $("bt-generate-msg").textContent = "Login admin diperlukan.";
      return;
    }
    if (!data.ok) {
      $("bt-generate-msg").textContent = data.error || `HTTP ${res.status}`;
      return;
    }
    const meta = data.ea;
    $("bt-generate-msg").textContent = `EA dibuat: ${meta.file}`;
    const link = el("a", "skill-link", `Buka ${meta.file}`);
    link.href = `/api/backtest/ea/${encodeURIComponent(meta.file)}`;
    link.target = "_blank";
    link.rel = "noopener";
    $("bt-generated").replaceChildren(link);
    await btLoadGenerated();
  } catch (error) {
    $("bt-generate-msg").textContent = error.message;
  }
}

function btRerun() {
  $("bt-form").scrollIntoView({ behavior: "smooth", block: "center" });
  $("bt-fast").focus();
  btSetStatus("", "idle");
  $("bt-message").textContent = "Ubah parameter lalu jalankan lagi untuk attempt baru.";
}

function initTester() {
  const end = $("bt-end");
  if (end && !end.value) end.value = new Date().toISOString().slice(0, 10);
  $("bt-form").addEventListener("submit", btStartRun);
  $("bt-cancel").addEventListener("click", btCancelRun);
  $("bt-refresh").addEventListener("click", btLoadJobs);
  $("bt-login-form").addEventListener("submit", btLogin);
  $("bt-generate").addEventListener("click", btGenerateEa);
  $("bt-rerun").addEventListener("click", btRerun);
  fetch("/api/auth/status", { cache: "no-store" })
    .then((r) => r.json())
    .then((d) => btSetAuth(!!d.logged_in, d.user))
    .catch(() => btSetAuth(false, null));
  btLoadJobs();
  btLoadGenerated();
}
