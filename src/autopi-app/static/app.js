(() => {
  const VIEW = document.body.dataset.view || "detailed";
  const IS_DASH = VIEW === "dashboard";

  // Filled from /configs/<view>.json before connect().
  let ORDER = [];
  let COLORS = {};
  let HISTORY_SECONDS = 90;
  let DASH_RANGE_SECONDS = 300;
  let DASH_UI_MS = 1000 / 6;
  let HISTORY_KEEP = 90;
  let FORMAT = { multiplier: 2, C: 1, degrees: 1, default: 2 };
  /** Optional per-channel { high?, low? } from view config. */
  let THRESHOLDS = {};

  let audioCtx = null;
  let buzzTimer = null;
  let buzzUnlocked = false;
  let buzzWanted = false;
  let buzzOsc = null;
  let buzzGain = null;

  /** Dash: guest QR panel ready; shown only after speed stays 0 for 10s. */
  let apShareReady = false;
  let speedZeroSinceMs = null;
  const QR_STATIONARY_MS = 10000;

  const state = {
    meta: {},
    values: {},
    history: {},
    gauges: {},
    charts: {},
    lastMsgT: 0,
    msgCount: 0,
    hz: 0,
    dashDirty: false,
    lastDashPaint: 0,
  };

  const elConn = document.getElementById("conn");
  const elEcu = document.getElementById("ecu");
  const elRate = document.getElementById("rate");
  const elError = document.getElementById("error");
  const elMotion = document.getElementById("motion");
  const elApShare = document.getElementById("apShare");

  function applyViewConfig(cfg) {
    ORDER = (cfg.channels || []).map((c) => c.key);
    COLORS = Object.fromEntries((cfg.channels || []).map((c) => [c.key, c.color]));
    THRESHOLDS = Object.fromEntries(
      (cfg.channels || [])
        .filter((c) => c.high != null || c.low != null)
        .map((c) => [c.key, { high: c.high, low: c.low }])
    );
    FORMAT = {
      multiplier: 2,
      C: 1,
      degrees: 1,
      default: 2,
      ...(cfg.format || {}),
    };
    if (IS_DASH) {
      DASH_RANGE_SECONDS = cfg.rangeSeconds ?? 300;
      DASH_UI_MS = 1000 / (cfg.uiHz ?? 6);
      HISTORY_KEEP = DASH_RANGE_SECONDS;
    } else {
      HISTORY_SECONDS = cfg.historySeconds ?? 90;
      HISTORY_KEEP = HISTORY_SECONDS;
    }
  }

  function fmt(val, units) {
    if (val == null || Number.isNaN(val)) return "—";
    const digits =
      FORMAT[units] !== undefined ? FORMAT[units] : FORMAT.default;
    return Number(val).toFixed(digits);
  }

  function sortedMetas(metaById) {
    return Object.values(metaById)
      .filter((m) => ORDER.includes(m.key))
      .sort((a, b) => ORDER.indexOf(a.key) - ORDER.indexOf(b.key));
  }

  function findMetaByKey(key) {
    return Object.values(state.meta).find((m) => m.key === key) || null;
  }

  function setApShareVisible(show) {
    if (!elApShare || !apShareReady) return;
    elApShare.hidden = !show;
  }

  function setMotionStatus(status) {
    if (!elMotion) return;
    elMotion.dataset.state = status;
    elMotion.textContent =
      status === "moving"
        ? "moving"
        : status === "stopped"
          ? "stopped"
          : status === "parked"
            ? "parked"
            : "—";
  }

  function updateMotionAndQr() {
    if (!IS_DASH) return;
    const meta = findMetaByKey("p9");
    const val = meta ? state.values[meta.id] : NaN;
    const live = val === val;

    if (!live) {
      setMotionStatus("unknown");
      return;
    }

    if (val > 0) {
      speedZeroSinceMs = null;
      setMotionStatus("moving");
      setApShareVisible(false);
      return;
    }

    // Stationary (speed == 0)
    const now = Date.now();
    if (speedZeroSinceMs == null) speedZeroSinceMs = now;
    const parked = now - speedZeroSinceMs >= QR_STATIONARY_MS;
    setMotionStatus(parked ? "parked" : "stopped");
    setApShareVisible(parked);
  }

  function ensureContainers() {
    document.querySelector(".detail-table-wrap")?.remove();

    if (IS_DASH) {
      let readouts = document.getElementById("readouts");
      if (!readouts) {
        readouts = document.createElement("section");
        readouts.id = "readouts";
        readouts.className = "readouts";
        const anchor = elError || document.querySelector("header.top");
        if (anchor && anchor.parentNode) {
          anchor.insertAdjacentElement("afterend", readouts);
        } else {
          document.body.appendChild(readouts);
        }
      }
      return { readouts, gauges: null, charts: null };
    }

    let gauges = document.getElementById("gauges");
    if (!gauges) {
      gauges = document.createElement("section");
      gauges.id = "gauges";
      gauges.className = "gauges";
      const anchor = elError || document.querySelector("header.top");
      if (anchor && anchor.parentNode) {
        anchor.insertAdjacentElement("afterend", gauges);
      } else {
        document.body.appendChild(gauges);
      }
    }

    let charts = document.getElementById("charts");
    if (!charts) {
      charts = document.createElement("section");
      charts.id = "charts";
      charts.className = "charts";
      gauges.insertAdjacentElement("afterend", charts);
    }

    return { readouts: null, gauges, charts };
  }

  function ensureLayout(metaById) {
    const metas = sortedMetas(metaById);
    if (metas.length === 0) return;

    const { readouts, gauges: elGauges, charts: elCharts } = ensureContainers();

    if (IS_DASH) {
      if (!readouts || readouts.childElementCount > 0) return;
      const rangeLbl = rangeWindowLabel();
      for (const m of metas) {
        const card = document.createElement("article");
        card.className = "readout-card";
        card.dataset.key = m.key;
        const thr = THRESHOLDS[m.key] || {};
        const highHtml =
          thr.high != null
            ? `<div class="readout-thresh-high">
            <span class="thresh-alarm" aria-hidden="true"></span>
            <span class="readout-range-val">${fmt(thr.high, m.units)}</span>
            <span class="readout-range-lbl">(limit high)</span>
          </div>`
            : "";
        const lowHtml =
          thr.low != null
            ? `<div class="readout-thresh-low">
            <span class="thresh-alarm" aria-hidden="true"></span>
            <span class="readout-range-val">${fmt(thr.low, m.units)}</span>
            <span class="readout-range-lbl">(limit low)</span>
          </div>`
            : "";
        card.innerHTML = `
          <div class="readout-max">
            <span class="readout-range-val" data-max="${m.id}">—</span>
            <span class="readout-range-lbl">(${rangeLbl} high)</span>
          </div>
          ${highHtml}
          <div class="readout-label">${m.label}</div>
          <div class="readout-value" data-value="${m.id}">—</div>
          <div class="readout-units">${m.units}</div>
          <div class="readout-min">
            <span class="readout-range-val" data-min="${m.id}">—</span>
            <span class="readout-range-lbl">(${rangeLbl} low)</span>
          </div>
          ${lowHtml}
        `;
        readouts.appendChild(card);
        state.history[m.id] = state.history[m.id] || [];
      }
      return;
    }

    if (!elGauges || !elCharts || elGauges.childElementCount > 0) return;

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

  function rangeWindowLabel() {
    const s = DASH_RANGE_SECONDS;
    if (s >= 60 && s % 60 === 0) {
      const m = s / 60;
      return `${m} min`;
    }
    return `${s}s`;
  }

  function updateSoundUi() {
    const btn = document.getElementById("soundEnable");
    if (!btn) return;
    if (buzzUnlocked) {
      btn.textContent = "Sound on";
      btn.classList.add("sound-on");
      btn.classList.remove("sound-off");
      btn.title = "Alert sound enabled — click to test";
    } else {
      btn.textContent = "Tap for sound";
      btn.classList.add("sound-off");
      btn.classList.remove("sound-on");
      btn.title = "Browsers block audio until you tap — enable coolant (P2) high alerts";
    }
  }

  function ensureAudio() {
    if (!IS_DASH) return null;
    const AC = window.AudioContext || window.webkitAudioContext;
    if (!AC) return null;
    if (!audioCtx) audioCtx = new AC();
    return audioCtx;
  }

  function stopBuzzTone() {
    if (buzzTimer) {
      clearInterval(buzzTimer);
      buzzTimer = null;
    }
    if (buzzOsc) {
      try {
        buzzOsc.stop();
      } catch (_) {
        /* already stopped */
      }
      try {
        buzzOsc.disconnect();
      } catch (_) {
        /* ignore */
      }
      buzzOsc = null;
    }
    if (buzzGain) {
      try {
        buzzGain.disconnect();
      } catch (_) {
        /* ignore */
      }
      buzzGain = null;
    }
  }

  function startBuzzTone() {
    const ctx = ensureAudio();
    if (!ctx || ctx.state !== "running") return false;
    if (buzzOsc) return true;

    buzzOsc = ctx.createOscillator();
    buzzGain = ctx.createGain();
    buzzOsc.type = "square";
    buzzOsc.frequency.value = 1400;
    buzzGain.gain.value = 0;
    buzzOsc.connect(buzzGain);
    buzzGain.connect(ctx.destination);
    buzzOsc.start();

    let on = true;
    buzzGain.gain.setValueAtTime(0.35, ctx.currentTime);
    buzzTimer = setInterval(() => {
      if (!buzzGain || !audioCtx) return;
      on = !on;
      buzzGain.gain.cancelScheduledValues(audioCtx.currentTime);
      buzzGain.gain.setValueAtTime(on ? 0.35 : 0.0, audioCtx.currentTime);
    }, 350);
    return true;
  }

  function syncBuzz() {
    if (buzzWanted && buzzUnlocked) startBuzzTone();
    else stopBuzzTone();
  }

  /** Unlock Web Audio (requires a user gesture in most browsers). */
  async function unlockAudio({ testBeep = false } = {}) {
    const ctx = ensureAudio();
    if (!ctx) return false;
    try {
      if (ctx.state === "suspended") await ctx.resume();
    } catch (_) {
      return false;
    }
    if (ctx.state !== "running") return false;
    buzzUnlocked = true;
    updateSoundUi();
    if (testBeep) {
      const t0 = ctx.currentTime;
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.type = "square";
      osc.frequency.value = 1200;
      gain.gain.setValueAtTime(0.4, t0);
      gain.gain.setValueAtTime(0.0, t0 + 0.2);
      osc.connect(gain);
      gain.connect(ctx.destination);
      osc.start(t0);
      osc.stop(t0 + 0.22);
    }
    syncBuzz();
    return true;
  }

  function setCoolantHighBuzz(active) {
    buzzWanted = !!active;
    if (active && !buzzUnlocked) {
      // Keep trying resume (works under kiosk autoplay policies).
      const ctx = ensureAudio();
      if (ctx && ctx.state === "suspended") {
        ctx.resume().then(() => {
          if (ctx.state === "running") {
            buzzUnlocked = true;
            updateSoundUi();
            syncBuzz();
          }
        });
      }
    }
    syncBuzz();
  }

  function rangeMinMax(pid, nowSec) {
    const series = state.history[pid] || [];
    const cutoff = nowSec - DASH_RANGE_SECONDS;
    let min = Infinity;
    let max = -Infinity;
    for (const [t, v] of series) {
      if (t < cutoff || v !== v) continue;
      if (v < min) min = v;
      if (v > max) max = v;
    }
    // Always include the latest live value so min/max appear immediately.
    const live = state.values[pid];
    if (live === live) {
      if (live < min) min = live;
      if (live > max) max = live;
    }
    if (min === Infinity) return { min: NaN, max: NaN };
    return { min, max };
  }

  function renderDash() {
    const nowSec = Date.now() / 1000;
    let coolantHighAlarm = false;
    for (const [pid, val] of Object.entries(state.values)) {
      const meta = state.meta[pid];
      if (!meta) continue;
      const card = document.querySelector(`.readout-card [data-value="${pid}"]`)?.closest(
        ".readout-card"
      );
      const valueNode =
        (card && card.querySelector(`[data-value="${pid}"]`)) ||
        document.querySelector(`[data-value="${pid}"]`);
      if (valueNode) valueNode.textContent = fmt(val, meta.units);

      const { min, max } = rangeMinMax(pid, nowSec);
      const maxWrap = card && card.querySelector(".readout-max");
      const minWrap = card && card.querySelector(".readout-min");
      const maxNode =
        (maxWrap && maxWrap.querySelector(`[data-max="${pid}"]`)) ||
        document.querySelector(`[data-max="${pid}"]`);
      const minNode =
        (minWrap && minWrap.querySelector(`[data-min="${pid}"]`)) ||
        document.querySelector(`[data-min="${pid}"]`);
      if (maxNode) maxNode.textContent = fmt(max, meta.units);
      if (minNode) minNode.textContent = fmt(min, meta.units);

      const thr = THRESHOLDS[meta.key] || {};
      const liveOk = val === val;
      const highActive = thr.high != null && liveOk && val >= thr.high;
      const lowActive = thr.low != null && liveOk && val <= thr.low;
      const maxHit = thr.high != null && max === max && max >= thr.high;
      const minHit = thr.low != null && min === min && min <= thr.low;

      const threshHigh = card && card.querySelector(".readout-thresh-high");
      const threshLow = card && card.querySelector(".readout-thresh-low");
      if (threshHigh) threshHigh.classList.toggle("alarm", highActive);
      if (threshLow) threshLow.classList.toggle("alarm", lowActive);
      if (maxWrap) maxWrap.classList.toggle("flash", maxHit);
      if (minWrap) minWrap.classList.toggle("flash", minHit);

      if (meta.key === "p2" && highActive) coolantHighAlarm = true;
    }
    setCoolantHighBuzz(coolantHighAlarm);
    updateMotionAndQr();
  }

  function render() {
    if (IS_DASH) {
      renderDash();
      return;
    }
    for (const [pid, val] of Object.entries(state.values)) {
      const node = document.querySelector(`[data-value="${pid}"]`);
      const meta = state.meta[pid];
      if (node && meta) node.textContent = fmt(val, meta.units);
    }
    for (const g of Object.values(state.gauges)) drawGauge(g);
    for (const c of Object.values(state.charts)) drawChart(c);
  }

  function trimHistory(pid, nowSec) {
    if (!state.history[pid]) state.history[pid] = [];
    const cutoff = nowSec - HISTORY_KEEP;
    while (state.history[pid].length && state.history[pid][0][0] < cutoff) {
      state.history[pid].shift();
    }
  }

  function ingestValues(values, t) {
    state.values = values || state.values;
    for (const [pid, val] of Object.entries(state.values)) {
      if (!state.history[pid]) state.history[pid] = [];
      if (val === val) state.history[pid].push([t, val]);
      trimHistory(pid, t);
    }
  }

  function applySnapshot(msg) {
    state.meta = msg.meta || {};
    state.history = {};
    for (const [pid, series] of Object.entries(msg.history || {})) {
      state.history[pid] = series.slice();
    }
    const t = msg.t || Date.now() / 1000;
    ingestValues(msg.values || {}, t);
    ensureLayout(state.meta);
    if (msg.ecu_id) elEcu.textContent = `ECU ${msg.ecu_id}`;
    if (msg.error) {
      elError.hidden = false;
      elError.textContent = msg.error;
    } else {
      elError.hidden = true;
    }
    render();
    state.dashDirty = false;
    state.lastDashPaint = performance.now();
  }

  function applyUpdate(msg) {
    const t = msg.t || Date.now() / 1000;
    ingestValues(msg.values || state.values, t);
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

    if (IS_DASH) {
      state.dashDirty = true;
      return;
    }
    render();
  }

  async function resolveWsUrl() {
    const proto = location.protocol === "https:" ? "wss" : "ws";
    const pageLocal = ["localhost", "127.0.0.1", "::1"].includes(
      location.hostname
    );

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

    const ping = setInterval(() => {
      if (ws.readyState === WebSocket.OPEN) ws.send("ping");
      else clearInterval(ping);
    }, 15000);
  }

  async function loadApShare() {
    if (!IS_DASH) return;
    if (!elApShare) return;
    try {
      const res = await fetch("/api/ap-info", { cache: "no-store" });
      if (!res.ok) return;
      const info = await res.json();
      if (!info.configured) return;

      const ssid = info.guest_ssid || "AUTOPI";
      document.getElementById("guestSsid").textContent = ssid;
      document.getElementById("guestSsidCode").textContent = ssid;
      document.getElementById("guestUrl").textContent = info.guest_dashboard_url || "";
      const adminEl = document.getElementById("adminSsid");
      if (adminEl) adminEl.textContent = info.admin_ssid || "USB only";
      document.getElementById("wifiQr").src =
        info.wifi_qr_data_uri || "/api/ap-qr.svg";
      document.getElementById("urlQr").src =
        info.url_qr_data_uri || "/api/ap-url-qr.svg";
      apShareReady = true;
      // Stay hidden until vehicle has been stationary for QR_STATIONARY_MS.
      elApShare.hidden = true;
      updateMotionAndQr();
    } catch (_) {
      // AP not configured — leave panel hidden
    }
  }

  window.addEventListener("resize", () => {
    if (!IS_DASH) resizeAll();
  });

  if (IS_DASH) {
    const soundBtn = document.getElementById("soundEnable");
    if (soundBtn) {
      soundBtn.addEventListener("click", (ev) => {
        ev.preventDefault();
        unlockAudio({ testBeep: true });
      });
    }
    // Any interaction can unlock (dash is often glance-only until tapped once).
    const tryUnlock = () => {
      if (!buzzUnlocked) unlockAudio({ testBeep: false });
    };
    window.addEventListener("pointerdown", tryUnlock);
    window.addEventListener("keydown", tryUnlock);
    updateSoundUi();
  }

  async function boot() {
    try {
      const res = await fetch(`/configs/${VIEW}.json`, { cache: "no-store" });
      if (!res.ok) throw new Error(`config HTTP ${res.status}`);
      applyViewConfig(await res.json());
    } catch (err) {
      console.error("Failed to load view config; using defaults", err);
      applyViewConfig({
        uiHz: 6,
        rangeSeconds: 300,
        historySeconds: 90,
        format: FORMAT,
        channels: [
          { key: "p2", color: "#e06c75" },
          { key: "p11", color: "#6cb6ff" },
          { key: "e31", color: "#e6a23c" },
          { key: "e41", color: "#6fbf73" },
        ],
      });
    }

    if (IS_DASH) {
      setInterval(() => {
        if (!state.dashDirty) return;
        state.dashDirty = false;
        state.lastDashPaint = performance.now();
        renderDash();
      }, DASH_UI_MS);
    }
    connect();
    loadApShare();
  }

  boot();
})();
