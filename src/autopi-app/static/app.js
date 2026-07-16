(() => {
  const HISTORY_SECONDS = 90;
  const ORDER = ["coolant", "iat", "dam", "flkc"];
  const COLORS = {
    coolant: "#e06c75",
    iat: "#6cb6ff",
    dam: "#e6a23c",
    flkc: "#6fbf73",
  };

  const state = {
    meta: {},
    values: {},
    history: {},
    gauges: {},
    charts: {},
    lastMsgT: 0,
    msgCount: 0,
    hz: 0,
  };

  const elConn = document.getElementById("conn");
  const elEcu = document.getElementById("ecu");
  const elRate = document.getElementById("rate");
  const elError = document.getElementById("error");
  const elGauges = document.getElementById("gauges");
  const elCharts = document.getElementById("charts");

  function fmt(val, units) {
    if (val == null || Number.isNaN(val)) return "—";
    if (units === "multiplier") return val.toFixed(3);
    if (units === "C" || units === "degrees") return val.toFixed(1);
    return val.toFixed(2);
  }

  function ensureLayout(metaById) {
    const metas = Object.values(metaById).sort(
      (a, b) => ORDER.indexOf(a.key) - ORDER.indexOf(b.key)
    );
    if (metas.length === 0) return;
    if (elGauges.childElementCount > 0) return;

    for (const m of metas) {
      const card = document.createElement("article");
      card.className = "gauge-card";
      card.innerHTML = `
        <h2>${m.label}</h2>
        <canvas data-gauge="${m.id}"></canvas>
        <div class="gauge-value" data-value="${m.id}">—</div>
        <div class="gauge-units">${m.units}</div>
      `;
      elGauges.appendChild(card);

      const chart = document.createElement("article");
      chart.className = "chart-card";
      chart.innerHTML = `
        <h2>${m.label} · last ${HISTORY_SECONDS}s</h2>
        <canvas data-chart="${m.id}"></canvas>
      `;
      elCharts.appendChild(chart);

      const gCanvas = card.querySelector("canvas");
      const cCanvas = chart.querySelector("canvas");
      state.gauges[m.id] = { canvas: gCanvas, ctx: gCanvas.getContext("2d"), meta: m };
      state.charts[m.id] = { canvas: cCanvas, ctx: cCanvas.getContext("2d"), meta: m };
      state.history[m.id] = state.history[m.id] || [];
    }
    resizeAll();
  }

  function resizeCanvas(canvas, cssHeight) {
    const dpr = window.devicePixelRatio || 1;
    const rect = canvas.getBoundingClientRect();
    const w = Math.max(1, Math.floor(rect.width * dpr));
    const h = Math.max(1, Math.floor((cssHeight || rect.height) * dpr));
    if (canvas.width !== w || canvas.height !== h) {
      canvas.width = w;
      canvas.height = h;
    }
    return { w, h, dpr };
  }

  function resizeAll() {
    for (const g of Object.values(state.gauges)) {
      resizeCanvas(g.canvas);
      drawGauge(g);
    }
    for (const c of Object.values(state.charts)) {
      resizeCanvas(c.canvas, 180);
      drawChart(c);
    }
  }

  function drawGauge(g) {
    const { canvas, ctx, meta } = g;
    const { w, h } = resizeCanvas(canvas);
    ctx.clearRect(0, 0, w, h);

    const cx = w / 2;
    const cy = h * 0.72;
    const r = Math.min(w, h) * 0.42;
    const start = Math.PI * 0.85;
    const end = Math.PI * 0.15 + Math.PI * 2;
    const span = end - start;
    const val = state.values[meta.id];
    const color = COLORS[meta.key] || "#e6a23c";

    ctx.lineWidth = Math.max(6, r * 0.12);
    ctx.lineCap = "round";

    ctx.beginPath();
    ctx.strokeStyle = "#3a4148";
    ctx.arc(cx, cy, r, start, end, false);
    ctx.stroke();

    if (val == null || Number.isNaN(val)) return;

    const t = Math.max(0, Math.min(1, (val - meta.min) / (meta.max - meta.min || 1)));
    ctx.beginPath();
    ctx.strokeStyle = color;
    ctx.arc(cx, cy, r, start, start + span * t, false);
    ctx.stroke();

    const angle = start + span * t;
    const nx = cx + Math.cos(angle) * (r - ctx.lineWidth * 0.2);
    const ny = cy + Math.sin(angle) * (r - ctx.lineWidth * 0.2);
    ctx.beginPath();
    ctx.fillStyle = color;
    ctx.arc(nx, ny, Math.max(3, r * 0.05), 0, Math.PI * 2);
    ctx.fill();

    ctx.fillStyle = "#9aa3ad";
    ctx.font = `${Math.max(10, r * 0.16)}px "IBM Plex Mono", monospace`;
    ctx.textAlign = "left";
    ctx.fillText(String(meta.min), cx - r * 0.95, cy + r * 0.35);
    ctx.textAlign = "right";
    ctx.fillText(String(meta.max), cx + r * 0.95, cy + r * 0.35);
  }

  function drawChart(c) {
    const { canvas, ctx, meta } = c;
    const { w, h } = resizeCanvas(canvas, 180);
    ctx.clearRect(0, 0, w, h);

    const pad = { l: 44, r: 12, t: 10, b: 24 };
    const plotW = w - pad.l - pad.r;
    const plotH = h - pad.t - pad.b;
    const now = Date.now() / 1000;
    const tMin = now - HISTORY_SECONDS;
    const series = (state.history[meta.id] || []).filter(([t]) => t >= tMin);
    const color = COLORS[meta.key] || "#e6a23c";

    // Grid
    ctx.strokeStyle = "#3a4148";
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.rect(pad.l, pad.t, plotW, plotH);
    ctx.stroke();

    const yTicks = 4;
    ctx.fillStyle = "#9aa3ad";
    ctx.font = `${Math.max(10, 11 * (window.devicePixelRatio || 1))}px "IBM Plex Mono", monospace`;
    for (let i = 0; i <= yTicks; i++) {
      const yv = meta.min + ((meta.max - meta.min) * i) / yTicks;
      const y = pad.t + plotH - (plotH * i) / yTicks;
      ctx.strokeStyle = "#2e343a";
      ctx.beginPath();
      ctx.moveTo(pad.l, y);
      ctx.lineTo(pad.l + plotW, y);
      ctx.stroke();
      ctx.textAlign = "right";
      ctx.textBaseline = "middle";
      ctx.fillStyle = "#9aa3ad";
      ctx.fillText(yv.toFixed(meta.units === "multiplier" ? 2 : 0), pad.l - 6, y);
    }

    ctx.textAlign = "center";
    ctx.textBaseline = "top";
    for (const sec of [90, 60, 30, 0]) {
      const x = pad.l + plotW * (1 - sec / HISTORY_SECONDS);
      ctx.fillText(sec === 0 ? "now" : `-${sec}s`, x, pad.t + plotH + 6);
    }

    if (series.length < 2) return;

    ctx.beginPath();
    ctx.strokeStyle = color;
    ctx.lineWidth = Math.max(1.5, 2 * (window.devicePixelRatio || 1));
    let started = false;
    for (const [t, v] of series) {
      const x = pad.l + ((t - tMin) / HISTORY_SECONDS) * plotW;
      const yNorm = (v - meta.min) / (meta.max - meta.min || 1);
      const y = pad.t + plotH - Math.max(0, Math.min(1, yNorm)) * plotH;
      if (!started) {
        ctx.moveTo(x, y);
        started = true;
      } else {
        ctx.lineTo(x, y);
      }
    }
    ctx.stroke();
  }

  function render() {
    for (const [pid, val] of Object.entries(state.values)) {
      const node = document.querySelector(`[data-value="${pid}"]`);
      const meta = state.meta[pid];
      if (node && meta) node.textContent = fmt(val, meta.units);
    }
    for (const g of Object.values(state.gauges)) drawGauge(g);
    for (const c of Object.values(state.charts)) drawChart(c);
  }

  function applySnapshot(msg) {
    state.meta = msg.meta || {};
    state.values = msg.values || {};
    state.history = {};
    for (const [pid, series] of Object.entries(msg.history || {})) {
      state.history[pid] = series.slice();
    }
    ensureLayout(state.meta);
    if (msg.ecu_id) elEcu.textContent = `ECU ${msg.ecu_id}`;
    if (msg.error) {
      elError.hidden = false;
      elError.textContent = msg.error;
    } else {
      elError.hidden = true;
    }
    render();
  }

  function applyUpdate(msg) {
    state.values = msg.values || state.values;
    const t = msg.t || Date.now() / 1000;
    for (const [pid, val] of Object.entries(state.values)) {
      if (!state.history[pid]) state.history[pid] = [];
      if (val === val) state.history[pid].push([t, val]);
      const cutoff = t - HISTORY_SECONDS;
      while (state.history[pid].length && state.history[pid][0][0] < cutoff) {
        state.history[pid].shift();
      }
    }
    if (msg.ecu_id) elEcu.textContent = `ECU ${msg.ecu_id}`;
    if (msg.error) {
      elError.hidden = false;
      elError.textContent = msg.error;
    } else {
      elError.hidden = true;
    }

    state.msgCount += 1;
    const now = performance.now();
    if (now - state.lastMsgT >= 1000) {
      state.hz = state.msgCount / ((now - state.lastMsgT) / 1000);
      state.msgCount = 0;
      state.lastMsgT = now;
      elRate.textContent = `${state.hz.toFixed(0)} Hz`;
    }
    render();
  }

  async function resolveWsUrl() {
    const proto = location.protocol === "https:" ? "wss" : "ws";
    const pageLocal = ["localhost", "127.0.0.1", "::1"].includes(
      location.hostname
    );

    // On phone / USB / LAN, always use the host that served this page.
    // Config often has autopi.local or localhost, which fail on the guest AP.
    if (!pageLocal) {
      return `${proto}://${location.hostname}:8090/ws`;
    }

    try {
      const res = await fetch("/config.json", { cache: "no-store" });
      if (res.ok) {
        const cfg = await res.json();
        if (cfg.collector_ws_url) return cfg.collector_ws_url;
      }
    } catch (_) {
      // fall through
    }
    return `${proto}://127.0.0.1:8090/ws`;
  }

  async function connect() {
    const wsUrl = await resolveWsUrl();
    const ws = new WebSocket(wsUrl);

    ws.onopen = () => {
      elConn.textContent = "live";
      elConn.classList.remove("offline");
      elConn.classList.add("online");
      state.lastMsgT = performance.now();
      state.msgCount = 0;
    };

    ws.onclose = () => {
      elConn.textContent = "reconnecting";
      elConn.classList.add("offline");
      elConn.classList.remove("online");
      setTimeout(connect, 1000);
    };

    ws.onerror = () => ws.close();

    ws.onmessage = (ev) => {
      const msg = JSON.parse(ev.data);
      if (msg.type === "snapshot") applySnapshot(msg);
      else if (msg.type === "update") applyUpdate(msg);
    };

    // Keepalive so the collector receive loop stays alive
    const ping = setInterval(() => {
      if (ws.readyState === WebSocket.OPEN) ws.send("ping");
      else clearInterval(ping);
    }, 15000);
  }

  window.addEventListener("resize", resizeAll);
  connect();
  loadApShare();

  async function loadApShare() {
    const panel = document.getElementById("apShare");
    if (!panel) return;
    try {
      const res = await fetch("/api/ap-info", { cache: "no-store" });
      if (!res.ok) return;
      const info = await res.json();
      if (!info.configured) return;

      panel.hidden = false;
      const ssid = info.guest_ssid || "AUTOPI";
      document.getElementById("guestSsid").textContent = ssid;
      document.getElementById("guestSsidCode").textContent = ssid;
      document.getElementById("guestUrl").textContent = info.guest_dashboard_url || "";
      // adminSsid element may be gone (USB-only admin on single-radio Pi)
      const adminEl = document.getElementById("adminSsid");
      if (adminEl) adminEl.textContent = info.admin_ssid || "USB only";
      document.getElementById("wifiQr").src =
        info.wifi_qr_data_uri || "/api/ap-qr.svg";
      document.getElementById("urlQr").src =
        info.url_qr_data_uri || "/api/ap-url-qr.svg";
    } catch (_) {
      // AP not configured — leave panel hidden
    }
  }
})();
