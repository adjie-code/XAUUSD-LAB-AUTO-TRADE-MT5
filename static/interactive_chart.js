"use strict";
// ============================================================================
// Interactive Candlestick Chart ala MT5 — canvas murni (tanpa library)
// Fitur: zoom (scroll/tombol), pan (drag), crosshair + tooltip OHLC,
//        skala harga kanan + waktu bawah, jumlah candle bisa diatur.
// Sumber: /api/candles (DB 667rb candle historis).
// ============================================================================

const IChart = (() => {
  const $ = (id) => document.getElementById(id);

  // ---- state chart ----
  let canvas, ctx, cssW, cssH, dpr;
  let all = [];            // buffer candle terurut naik (dari API)
  let view = { end: 0, count: 120 };  // end = index terakhir terlihat (di array all)
  const MIN_BARS = 10, MAX_BARS = 600;
  let drag = null;
  let mouse = null;        // {x, y}
  let loading = false;
  let padL = 8, padR = 68, padT = 24, padB = 24;

  function fmtTs(t) {
    const off = (typeof window.__timeOff === "number") ? window.__timeOff : 0;
    const d = new Date((t < 1e12 ? t * 1000 : t) + off * 3600000);
    return d.toISOString().replace("T", " ").slice(5, 16) + (off === 0 ? " UTC" :
      off === 7 ? "" : " (MT5)");
  }

  // ---- data ----
  async function fetchOlder(before, count) {
    const q = before ? `&before=${Math.floor(before)}` : "";
    const r = await fetch(`/api/candles?count=${Math.floor(count)}${q}`);
    const d = await r.json();
    if (!r.ok) throw new Error("API " + r.status);
    if (!d.ok || !d.candles) return [];
    return d.candles;
  }

  async function init(canvasId, initialCount = 120) {
    canvas = $(canvasId);
    if (!canvas) return api;   // elemen tidak ada -> jangan crash halaman
    ctx = canvas.getContext("2d");
    bindEvents();
    // Saat jendela/panel berubah lebar, gambar ulang setelah layout stabil.
    // Tanpa ini, bitmap lama bisa tampak mengecil dan label waktu ikut mengecil.
    if (typeof ResizeObserver !== "undefined") {
      let roTimer = null;
      const ro = new ResizeObserver(() => {
        clearTimeout(roTimer);
        roTimer = setTimeout(() => {
          if (canvas && (canvas.clientWidth !== cssW || canvas.clientHeight !== cssH)) render();
        }, 60);
      });
      ro.observe(canvas);
    }
    view.count = Math.max(MIN_BARS, Math.min(MAX_BARS, initialCount));
    // muat awal: candle terbaru + sedikit riwayat untuk pan kiri
    const first = await fetchOlder(null, Math.max(view.count + 80, 200));
    all = first.filter(c => [c.o, c.h, c.l, c.c].every(v => typeof v === "number"));
    view.end = all.length - 1;
    render();
    if (all.length === 0) {
      ctx = canvas.getContext("2d");
      ctx.fillStyle = "#0a1019"; ctx.fillRect(0, 0, canvas.clientWidth, canvas.height);
      ctx.fillStyle = "#fb7185"; ctx.font = "13px monospace";
      ctx.fillText("chart: data belum tersedia (API /api/candles gagal)", 20, 40);
    }
    return api;
  }

  function needOlder() {
    // bila view menyentuh awal buffer, muat lebih banyak ke kiri
    if (view.end - view.count < 50 && !loading && all.length >= 1) {
      loading = true;
      fetchOlder(all[0].t, 500).then((older) => {
        if (older.length > 0) {
          const added = older.length;
          all = older.concat(all);
          view.end += added;
        }
        loading = false;
        render();
      }).catch(() => { loading = false; });
    }
  }

  // ---- interaksi ----
  function bindEvents() {
    canvas.addEventListener("wheel", (e) => {
      e.preventDefault();
      const factor = e.deltaY > 0 ? 1.15 : 1 / 1.15;
      const newCount = Math.max(MIN_BARS, Math.min(MAX_BARS, Math.round(view.count * factor)));
      // jaga titik di bawah kursor tetap stabil
      const rect = canvas.getBoundingClientRect();
      const mx = e.clientX - rect.left;
      const frac = Math.max(0, Math.min(1, (mx - padL) / (cssW - padL - padR)));
      const anchor = view.end - Math.round((1 - frac) * view.count);
      view.count = newCount;
      view.end = Math.max(view.count - 1, Math.min(all.length - 1,
        anchor + Math.round((1 - frac) * view.count)));
      needOlder();
      render();
    }, { passive: false });

    canvas.addEventListener("mousedown", (e) => {
      drag = { x: e.clientX, end: view.end };
      canvas.style.cursor = "grabbing";
    });
    window.addEventListener("mousemove", (e) => {
      const rect = canvas.getBoundingClientRect();
      mouse = { x: e.clientX - rect.left, y: e.clientY - rect.top };
      if (drag) {
        const dx = e.clientX - drag.x;
        const barsPerPx = view.count / (cssW - padL - padR);
        const shift = Math.round(dx * barsPerPx);
        view.end = Math.max(view.count - 1, Math.min(all.length - 1, drag.end - shift));
        needOlder();
      }
      render();
    });
    window.addEventListener("mouseup", () => {
      drag = null;
      if (canvas) canvas.style.cursor = "crosshair";
    });
    canvas.addEventListener("mouseleave", () => { mouse = null; render(); });

    // touch (HP)
    let tPrev = null;
    canvas.addEventListener("touchstart", (e) => {
      if (e.touches.length === 1) drag = { x: e.touches[0].clientX, end: view.end };
      if (e.touches.length === 2) {
        tPrev = Math.abs(e.touches[0].clientX - e.touches[1].clientX);
      }
    }, { passive: true });
    canvas.addEventListener("touchmove", (e) => {
      if (e.touches.length === 1 && drag) {
        const dx = e.touches[0].clientX - drag.x;
        const barsPerPx = view.count / (cssW - padL - padR);
        view.end = Math.max(view.count - 1, Math.min(all.length - 1, drag.end - Math.round(dx * barsPerPx)));
        needOlder(); render();
      } else if (e.touches.length === 2 && tPrev) {
        const w = Math.abs(e.touches[0].clientX - e.touches[1].clientX);
        if (w > 0 && tPrev > 0) {
          const factor = tPrev / w;
          view.count = Math.max(MIN_BARS, Math.min(MAX_BARS, Math.round(view.count * factor)));
        }
        tPrev = w; render();
      }
    }, { passive: true });
    canvas.addEventListener("touchend", () => { drag = null; tPrev = null; }, { passive: true });
  }

  // ---- render ----
  function render() {
    if (!canvas) return;
    dpr = window.devicePixelRatio || 1;
    cssW = canvas.clientWidth || 1000;
    cssH = canvas.clientHeight || Number(canvas.getAttribute("height")) || 400;
    canvas.width = Math.round(cssW * dpr);
    canvas.height = Math.round(cssH * dpr);
    ctx = canvas.getContext("2d");
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

    ctx.fillStyle = "#0a1019";
    ctx.fillRect(0, 0, cssW, cssH);

    const start = Math.max(0, view.end - view.count + 1);
    const vis = all.slice(start, view.end + 1).filter(c =>
      [c.o, c.h, c.l, c.c].every(v => typeof v === "number"));
    if (vis.length === 0) {
      ctx.fillStyle = "#8b98a9"; ctx.font = "13px monospace"; ctx.textAlign = "center";
      ctx.fillText("belum ada data", cssW / 2, cssH / 2);
      ctx.textAlign = "start";
      return;
    }

    let max = Math.max(...vis.map(c => c.h)), min = Math.min(...vis.map(c => c.l));
    const pad5 = (max - min) * 0.06 || 1;
    max += pad5; min -= pad5;
    const plotW = cssW - padL - padR;
    const plotH = cssH - padT - padB;
    const y = (p) => padT + plotH - ((p - min) / (max - min)) * plotH;

    // ---- grid harga ----
    ctx.font = "10px monospace";
    ctx.textBaseline = "middle";
    for (let i = 0; i <= 5; i++) {
      const p = min + (i / 5) * (max - min);
      const yy = y(p);
      ctx.strokeStyle = "#1e2937"; ctx.beginPath();
      ctx.moveTo(padL, yy); ctx.lineTo(padL + plotW, yy); ctx.stroke();
      ctx.fillStyle = "#8b98a9";
      ctx.fillText(p.toFixed(2), padL + plotW + 6, yy);
    }

    // ---- candle ----
    const n = vis.length;
    const step = plotW / n;
    const bw = Math.max(1.5, Math.min(step * 0.65, 18));
    vis.forEach((c, i) => {
      const cx = padL + step * (i + 0.5);
      const col = c.c >= c.o ? "#2dd4a7" : "#fb7185";
      ctx.strokeStyle = col; ctx.lineWidth = Math.min(1.5, bw / 3);
      ctx.beginPath(); ctx.moveTo(cx, y(c.h)); ctx.lineTo(cx, y(c.l)); ctx.stroke();
      const top = y(Math.max(c.o, c.c)), bot = y(Math.min(c.o, c.c));
      ctx.fillStyle = col;
      ctx.fillRect(cx - bw / 2, top, bw, Math.max(1, bot - top));
    });

    // ---- garis waktu (vertical tiap ~jam; label adaptif agar tidak tumpang tindih) ----
    ctx.strokeStyle = "#182231";
    let lastHour = -1;
    let lastLabelX = -Infinity;
    const minLabelGap = 46;
    vis.forEach((c, i) => {
      const d = new Date((c.t + (window.__timeOff || 0) * 3600) * 1000);
      if (d.getUTCHours() !== lastHour) {
        lastHour = d.getUTCHours();
        const cx = padL + step * (i + 0.5);
        ctx.beginPath(); ctx.moveTo(cx, padT); ctx.lineTo(cx, cssH - padB); ctx.stroke();
        if (cx - lastLabelX >= minLabelGap) {
          const label = String(d.getUTCHours()).padStart(2, "0") + ":00";
          const tw = ctx.measureText(label).width;
          const lx = Math.min(Math.max(cx, padL + tw / 2 + 2), padL + plotW - tw / 2 - 2);
          ctx.fillStyle = "#6f7f93";
          ctx.textAlign = "center";
          ctx.fillText(label, lx, cssH - padB / 2);
          ctx.textAlign = "start";
          lastLabelX = lx;
        }
      }
    });

    // ---- info OHLC pojok kiri (ala MT5) ----
    let hovered = null;
    if (mouse && mouse.x >= padL && mouse.x <= padL + plotW) {
      const i = Math.floor((mouse.x - padL) / step);
      if (i >= 0 && i < vis.length) hovered = vis[i];
    } else if (vis.length) {
      hovered = vis[vis.length - 1];
    }
    if (hovered) {
      const chg = hovered.c - hovered.o;
      const chgPct = hovered.o ? (chg / hovered.o * 100) : 0;
      ctx.font = "11px monospace";
      ctx.fillStyle = "#d8e2ee";
      const info =
        `${fmtTs(hovered.t)}   O ${hovered.o.toFixed(2)}  H ${hovered.h.toFixed(2)}` +
        `  L ${hovered.l.toFixed(2)}  C ${hovered.c.toFixed(2)}` +
        `  ${chg >= 0 ? "+" : ""}${chg.toFixed(2)} (${chgPct >= 0 ? "+" : ""}${chgPct.toFixed(2)}%)` +
        `  Vol ${hovered.tv ?? "-"}`;
      ctx.fillText(info, padL + 4, 12);
    }

    // ---- crosshair ----
    if (mouse && mouse.x >= padL && mouse.x <= padL + plotW && mouse.y >= padT && mouse.y <= cssH - padB) {
      ctx.strokeStyle = "rgba(148,163,184,0.4)"; ctx.setLineDash([4, 4]); ctx.lineWidth = 1;
      ctx.beginPath(); ctx.moveTo(mouse.x, padT); ctx.lineTo(mouse.x, cssH - padB); ctx.stroke();
      ctx.beginPath(); ctx.moveTo(padL, mouse.y); ctx.lineTo(padL + plotW, mouse.y); ctx.stroke();
      ctx.setLineDash([]);
      // label harga di kursor
      const price = min + (1 - (mouse.y - padT) / plotH) * (max - min);
      ctx.fillStyle = "#263345"; ctx.fillRect(padL + plotW + 2, mouse.y - 8, padR - 8, 16);
      ctx.fillStyle = "#d8e2ee"; ctx.fillText(price.toFixed(2), padL + plotW + 6, mouse.y);
    }

    // ---- indikator loading / ujung kiri ----
    if (loading) {
      ctx.fillStyle = "#f2c14e"; ctx.font = "10px monospace";
      ctx.fillText("memuat riwayat...", padL + 4, cssH - 8);
    }
  }

  // ---- auto-refresh (C+B) ---------------------------------------------
  // PID siklus: cek candle baru tiap 20 dtk — HANYA bila view sedang di
  // posisi Live; saat menjelajah riwayat view tidak diganggu sama sekali.
  let autoTimer = null;

  function isAtLive() {
    return all.length > 0 && view.end >= all.length - 1;
  }

  async function refreshData() {
    if (loading || !isAtLive()) return;
    loading = true;
    try {
      const fresh = await fetchOlder(null, Math.max(view.count + 80, 200));
      if (fresh.length) {
        all = fresh.filter(c => [c.o, c.h, c.l, c.c].every(v => typeof v === "number"));
        view.end = all.length - 1;         // tetap menempel di candle terbaru
      }
    } catch (e) { /* diamkan: polling gagal sesekali tak berpengaruh */ }
    loading = false;
    needOlder();
    render();
  }

  function setAuto(on) {
    if (on && !autoTimer) {
      isAtLive() && refreshData();         // sinkron cepat sekali awal
      autoTimer = setInterval(refreshData, 20000);
    } else if (!on && autoTimer) {
      clearInterval(autoTimer);
      autoTimer = null;
    }
  }

  // ---- API publik ----
  const api = {
    init,
    setCount(n) {
      view.count = Math.max(MIN_BARS, Math.min(MAX_BARS, Math.round(n)));
      view.end = Math.min(all.length - 1, Math.max(view.end, view.count - 1));
      needOlder(); render();
    },
    goLive() { view.end = all.length - 1; render(); },
    bars: () => view.count,
    auto: setAuto,          // ON/OFF polling candle baru (C+B)
    refresh: refreshData,   // force sinkron manual
  };
  return api;
})();

// Ekspos ke window agar app.js (script klasik) bisa menginisialisasi chart
// tanpa bergantung pada detail global lexical binding.
window.IChart = IChart;
