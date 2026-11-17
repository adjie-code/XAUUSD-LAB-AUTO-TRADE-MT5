"use strict";

const $ = (id) => document.getElementById(id);
let CONNECTED = false;

function message(text, kind = "") {
  const m = $("broker-message");
  m.className = "broker-message" + (kind ? " " + kind : "");
  m.textContent = text || "";
}

async function loadStatus() {
  try {
    const r = await fetch("/api/broker/status", { cache: "no-store" });
    const d = await r.json();
    if (!d.ok || !d.connected) return;
    CONNECTED = true;
    $("broker-current").hidden = false;
    $("broker-current-text").textContent =
      `${d.broker || "Broker"} · ${d.server || "-"} · akun ${d.login || "-"}` +
      (d.symbol ? ` · ${d.symbol}` : "") +
      (d.connected_at ? ` · ${d.connected_at}` : "");
  } catch (_) {
    // Status opsional; form tetap bisa dipakai.
  }
}

async function submit(e) {
  e.preventDefault();
  const btn = $("broker-submit");
  const payload = {
    broker: $("f-broker").value.trim(),
    server: $("f-server").value.trim(),
    username: $("f-username").value.trim(),
    password: $("f-password").value,
    symbol: $("f-symbol").value.trim(),
  };
  btn.disabled = true;
  message("Menulis konfigurasi MT5 dan meminta restart…", "warn");
  try {
    const r = await fetch("/api/broker/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const d = await r.json().catch(() => ({}));
    if (!r.ok || !d.ok) {
      throw new Error(d.error || `HTTP ${r.status}`);
    }
    CONNECTED = true;
    $("f-password").value = "";
    $("broker-current").hidden = false;
    $("broker-current-text").textContent =
      `${d.broker} · ${d.server} · akun ${d.login}` +
      (d.symbol ? ` · ${d.symbol}` : "") +
      ` · ${d.connected_at}`;
    message(
      d.warning
        ? `Konfigurasi tersimpan. ${d.warning}`
        : "Login dikirim ke MT5. Tunggu terminal selesai restart, lalu buka dashboard.",
      d.warning ? "warn" : "ok",
    );
    setTimeout(() => { window.location.href = "/"; }, 2500);
  } catch (err) {
    message(`Gagal: ${err.message}`, "err");
  } finally {
    btn.disabled = false;
  }
}

async function logout() {
  try {
    await fetch("/api/broker/logout", { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" });
    CONNECTED = false;
    $("broker-current").hidden = true;
    message("Sesi broker dihapus dari dashboard. MT5 tidak di-logout otomatis.", "warn");
  } catch (err) {
    message(`Gagal: ${err.message}`, "err");
  }
}

$("broker-form").addEventListener("submit", submit);
$("broker-logout").addEventListener("click", logout);
loadStatus();
