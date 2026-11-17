#!/usr/bin/env node
// MT5 Companion Monitor — dibangun dari hasil RE Ghidra:
//   - endpoint MCP: http://127.0.0.1:22345/mcp & http://127.0.0.1:22346/mcp
//   - AI backend:   https://api.inferdeck.net (hanya dicek reachability, tanpa API key)
//   - telemetri:    updates.metaquotes.net (hanya dicek reachability, opsional)
// Tidak me-reverse/rekonstruksi MT5; hanya memantau layanannya.

import http from "node:http";
import { execFile, exec } from "node:child_process";
import { promisify } from "node:util";
import fs from "node:fs";
import os from "node:os";

const execFileP = promisify(execFile);
const execP = promisify(exec);

const PORT = Number(process.env.PORT || 4100);
const MCP_A = process.env.MCP_A || "http://127.0.0.1:22345/mcp";
const MCP_B = process.env.MCP_B || "http://127.0.0.1:22346/mcp";
const LXHTTP = process.env.LXHTTP || "http://127.0.0.1:4321";
const LXEA = process.env.LXEA || "127.0.0.1:3198";
const START = Date.now();

// ---------- helpers ----------
async function pingHttp(url, timeoutMs = 1500) {
  try {
    const ctrl = new AbortController();
    const t = setTimeout(() => ctrl.abort(), timeoutMs);
    const r = await fetch(url, { signal: ctrl.signal });
    clearTimeout(t);
    return { url, ok: r.ok || (r.status < 500 && r.status >= 200), status: r.status };
  } catch (e) {
    return { url, ok: false, status: 0, err: String(e.message || e).slice(0, 80) };
  }
}

async function pingTcp(host, port, timeoutMs = 1500) {
  return new Promise((res) => {
    const net = http.socket?.constructor ? null : null; // placeholder (net imported below)
    res({ host, port, ok: false });
  });
}

// gunakan node:net untuk TCP
import net from "node:net";
function tcpCheck(host, port, timeoutMs = 1500) {
  return new Promise((resolve) => {
    const s = new net.Socket();
    let done = false;
    const fin = (ok) => { if (!done) { done = true; s.destroy(); resolve({ host, port, ok }); } };
    s.setTimeout(timeoutMs);
    s.once("connect", () => fin(true));
    s.once("timeout", () => fin(false));
    s.once("error", () => fin(false));
    s.connect(port, host);
  });
}

async function dockerStats() {
  try {
    const { stdout } = await execP(
      "docker ps --format '{{.Names}} {{.Status}}' 2>/dev/null | grep -E 'linux-mt5'"
    );
    return stdout.trim().split("\n").filter(Boolean);
  } catch { return []; }
}

async function mt5Proc() {
  try {
    const { stdout } = await execP(
      "ps -eo comm,args | grep -i terminal64.exe | grep -v grep | head -3"
    );
    return stdout.trim() || null;
  } catch { return null; }
}

async function sysInfo() {
  const total = os.totalmem(), free = os.freemem();
  const upR = await execFileP("uptime", ["-p"]).then(r => r.stdout.trim()).catch(() => "-");
  const [load1, load5, load15] = os.loadavg().map(v => v.toFixed(2));
  return { totalMem: total, freeMem: free, usedPct: ((total - free) / total * 100).toFixed(1), uptime: upR, load: `${load1} ${load5} ${load15}` };
}

// ---------- HTML dashboard ----------
const HTML = `<!doctype html><html lang="id"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>MT5 Companion Monitor</title>
<style>
body{font-family:system-ui,Segoe UI,sans-serif;background:#0d1117;color:#e6edf3;margin:0;padding:24px}
h1{font-size:20px;color:#58a6ff} .grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:14px}
.card{background:#161b22;border:1px solid #30363d;border-radius:10px;padding:14px}
.card h3{margin:.2rem 0 .6rem;font-size:14px;color:#8b949e}
.row{display:flex;justify-content:space-between;font-size:13px;padding:3px 0;border-bottom:1px solid #21262d}
.ok{color:#3fb950}.bad{color:#f85149}.warn{color:#d29922}
small{color:#8b949e}
</style></head><body>
<h1>MT5 Companion Monitor</h1>
<small>Bangun dari hasil RE Ghidra (endpoint MCP 22345/22346, LxConsole 4321/3198, status Docker).</small>
<div class="grid">
  <div class="card"><h3>MT5 MCP (dari binary)</h3><div id="mcp"></div></div>
  <div class="card"><h3>LxConsole</h3><div id="lx"></div></div>
  <div class="card"><h3>Docker &amp; proses MT5</h3><div id="dock"></div></div>
  <div class="card"><h3>Sistem</h3><div id="sys"></div></div>
</div>
<script>
const fmt=v=>v?'OK':'GAGAL';const cls=v=>v?'ok':'bad';
async function load(){
  const j=await (await fetch('/api/status')).json();
  const m=document.getElementById('mcp');
  m.innerHTML=j.mcp.map(x=>\`<div class="row"><span>\${x.url}</span><b class="\${cls(x.ok)}">\${x.ok?('+'+x.status):('x'+(x.err||x.status))}</b></div>\`).join('');
  const l=document.getElementById('lx');
  l.innerHTML=\`<div class="row"><span>\${j.lxHttp.url}</span><b class="\${cls(j.lxHttp.ok)}">\${fmt(j.lxHttp.ok)}</b></div>
  <div class="row"><span>EA TCP \${j.lxEa.host}:\${j.lxEa.port}</span><b class="\${cls(j.lxEa.ok)}">\${fmt(j.lxEa.ok)}</b></div>\`;
  const d=document.getElementById('dock');
  d.innerHTML=\`<div class="row"><span>docker: \${j.docker.length?j.docker.join(' | '):'tidak terbaca'}</span></div>
  <div class="row"><span>terminal64.exe</span><b class="\${cls(j.mt5Proc)}">\${j.mt5Proc?'JALAN':'MATI'}</b></div>\`;
  const s=document.getElementById('sys');
  s.innerHTML=\`<div class="row"><span>RAM terpakai</span><b>\${j.sys.usedPct}%</b></div>
  <div class="row"><span>load(1/5/15)</span><b>\${j.sys.load}</b></div>
  <div class="row"><span>uptime</span><b>\${j.sys.uptime}</b></div>\`;
}
load();setInterval(load,5000);
</script></body></html>`;

// ---------- server ----------
const server = http.createServer(async (req, res) => {
  const u = new URL(req.url, `http://localhost:${PORT}`);
  if (u.pathname === "/") {
    res.writeHead(200, { "Content-Type": "text/html; charset=utf-8" });
    return res.end(HTML);
  }
  if (u.pathname === "/api/status") {
    const [mcp1, mcp2, lx] = await Promise.all([pingHttp(MCP_A), pingHttp(MCP_B), pingHttp(LXHTTP)]);
    const lxEa = await tcpCheck("127.0.0.1", 3198);
    const [docks, mt5proc, sys] = await Promise.all([dockerStats(), mt5Proc(), sysInfo()]);
    res.writeHead(200, { "Content-Type": "application/json" });
    return res.end(JSON.stringify({ mcp: [mcp1, mcp2], lxHttp: lx, lxEa, docker: docks, mt5Proc: mt5proc, sys, since: START }, null, 2));
  }
  res.writeHead(404); res.end("not found");
});

server.listen(PORT, () => console.log(`MT5 Companion Monitor di port ${PORT}`));
