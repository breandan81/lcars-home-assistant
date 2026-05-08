'use strict';

// ── State ─────────────────────────────────────────────────────────────────
const state = {
  kasa: [],
  tuya: [],
  ecoflow: { state: {}, connected: false },
  roku: { apps: [] },
  ecoSetTemp: 24,
};

// ── WebSocket ─────────────────────────────────────────────────────────────
let ws;
let wsReconnectMs = 2000;

function connectWS() {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  ws = new WebSocket(`${proto}://${location.host}/ws`);

  ws.onopen = () => {
    wsReconnectMs = 2000;
    setWsDot(true);
    setStatus('SYSTEM ONLINE');
  };

  ws.onclose = () => {
    setWsDot(false);
    setStatus('RECONNECTING…');
    setTimeout(connectWS, wsReconnectMs);
    wsReconnectMs = Math.min(wsReconnectMs * 1.5, 30000);
  };

  ws.onmessage = (e) => {
    try {
      const msg = JSON.parse(e.data);
      handlePush(msg);
    } catch {}
  };
}

function handlePush(msg) {
  if (msg.type === 'poll_kasa' && msg.devices) {
    state.kasa = msg.devices;
    renderKasa();
  }
  if (msg.type === 'poll_ecoflow' && msg.status) {
    state.ecoflow = msg.status;
    renderEcoflow();
  }
  if (msg.type === 'kasa') {
    const d = state.kasa.find(k => k.alias === msg.alias);
    if (d) { d.is_on = msg.is_on; renderKasa(); }
  }
}

function setWsDot(ok) {
  const dot   = document.getElementById('ws-dot');
  const label = document.getElementById('ws-label');
  dot.className   = 'conn-dot ' + (ok ? 'ok' : 'err');
  label.textContent = ok ? 'ONLINE' : 'OFFLINE';
}

// ── Nav ───────────────────────────────────────────────────────────────────
document.querySelectorAll('.nav-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.nav-btn').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.section').forEach(s => s.classList.remove('active'));
    btn.classList.add('active');
    const sec = document.getElementById('section-' + btn.dataset.section);
    if (sec) sec.classList.add('active');
  });
});

// ── Stardate ──────────────────────────────────────────────────────────────
function updateStardate() {
  const now  = new Date();
  const year = now.getFullYear();
  const day  = Math.floor((now - new Date(year, 0, 0)) / 86400000);
  const frac = (now.getHours() * 60 + now.getMinutes()) / 1440;
  const sd   = ((year - 2323) * 365 + day + frac).toFixed(1);
  document.getElementById('stardate').textContent = `STARDATE ${sd}`;
}
updateStardate();
setInterval(updateStardate, 30000);

// ── Toast / Status ────────────────────────────────────────────────────────
let toastTimer;
function toast(msg, color = 'var(--lt-blue)') {
  const el = document.getElementById('toast');
  el.textContent = msg;
  el.style.color = color;
  el.classList.add('show');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.remove('show'), 2500);
}

function setStatus(msg) {
  document.getElementById('status-msg').textContent = msg;
}

function setAction(msg) {
  document.getElementById('last-action').textContent = msg;
}

// ── API helper ────────────────────────────────────────────────────────────
async function api(method, path, params) {
  let url = path;
  if (method === 'GET' && params) {
    url += '?' + new URLSearchParams(params).toString();
  }
  const opts = { method };
  if (method !== 'GET' && params) {
    url += '?' + new URLSearchParams(params).toString();
  }
  try {
    const resp = await fetch(url, opts);
    return await resp.json();
  } catch (e) {
    toast('Network error: ' + e.message, 'var(--red)');
    return { error: e.message };
  }
}

// ── Indicator helper ─────────────────────────────────────────────────────
function setIndicator(id, state) {
  const el = document.getElementById(id);
  if (!el) return;
  el.className = 'indicator ' + (state === 'on' ? 'on' : state === 'warn' ? 'warn' : state === 'err' ? 'err' : '');
}

// ════════════════════════════════════════════════════════════════════════════
// KASA
// ════════════════════════════════════════════════════════════════════════════

async function kasaDiscover() {
  setAction('Discovering Kasa devices…');
  toast('Scanning for Kasa devices…');
  const data = await api('GET', '/api/kasa/discover');
  if (Array.isArray(data)) {
    state.kasa = data;
    renderKasa();
    toast(`Found ${data.length} Kasa device(s)`);
  } else {
    toast('Kasa discovery failed: ' + (data.error || 'unknown'), 'var(--red)');
  }
}

async function kasaRefresh() {
  const data = await api('GET', '/api/kasa/devices');
  if (Array.isArray(data)) {
    state.kasa = data;
    renderKasa();
  }
}

async function kasaToggle(alias, currentlyOn) {
  const newState = !currentlyOn;
  setAction(`${alias}: ${newState ? 'ON' : 'OFF'}`);
  await api('POST', `/api/kasa/${encodeURIComponent(alias)}/power`, { state: newState });
  kasaRefresh();
}

function renderKasa() {
  const container = document.getElementById('kasa-devices');
  const count = document.getElementById('kasa-count');

  if (!state.kasa.length) {
    container.innerHTML = '<div style="color:var(--dim);font-size:0.75rem">No devices found.</div>';
    setIndicator('kasa-indicator', '');
    count.textContent = '';
    return;
  }

  setIndicator('kasa-indicator', 'on');
  count.textContent = `${state.kasa.length} UNIT(S)`;

  container.innerHTML = state.kasa.map(d => `
    <div class="device-card">
      <div class="dev-name">${esc(d.alias)}</div>
      <div class="dev-ip">${esc(d.host || '')} &nbsp;·&nbsp; ${esc(d.model || '')}</div>
      <div class="dev-status">${d.error ? '⚠ ' + esc(d.error) : (d.is_on ? '● ON' : '○ OFF')}</div>
      <div class="ctrl-row">
        <button class="lbtn green" onclick="kasaToggle('${esc(d.alias)}', ${d.is_on})">${d.is_on ? 'Turn OFF' : 'Turn ON'}</button>
      </div>
      ${d.children && d.children.length ? `
        <div style="margin-top:8px;font-size:0.65rem;color:var(--dim)">STRIP OUTLETS:</div>
        ${d.children.map(c => `
          <div style="display:flex;justify-content:space-between;align-items:center;font-size:0.7rem;color:var(--lt-blue);margin-top:4px">
            <span>${esc(c.alias)}</span>
            <span>${c.is_on ? '● ON' : '○ OFF'}</span>
          </div>
        `).join('')}
      ` : ''}
    </div>
  `).join('');
}

// ════════════════════════════════════════════════════════════════════════════
// TUYA / LIGHTING
// ════════════════════════════════════════════════════════════════════════════

async function tuyaRefresh() {
  const data = await api('GET', '/api/lighting/devices');
  if (Array.isArray(data)) {
    state.tuya = data;
    renderTuya();
  }
}

async function tuyaToggle(name, currentlyOn) {
  setAction(`${name}: ${!currentlyOn ? 'ON' : 'OFF'}`);
  await api('POST', `/api/lighting/${encodeURIComponent(name)}/power`, { state: !currentlyOn });
  tuyaRefresh();
}

async function tuyaBrightness(name, val) {
  await api('POST', `/api/lighting/${encodeURIComponent(name)}/brightness`, { value: val });
}

async function tuyaColor(name, hex) {
  const [r, g, b] = hexToRgb(hex);
  const [h, s, v] = rgbToHsv(r, g, b);
  await api('POST', `/api/lighting/${encodeURIComponent(name)}/color`, {
    h: Math.round(h * 360), s: Math.round(s * 100), v: Math.round(v * 100)
  });
}

function renderTuya() {
  const container = document.getElementById('tuya-devices');
  const count = document.getElementById('tuya-count');

  if (!state.tuya.length) {
    container.innerHTML = '<div style="color:var(--dim);font-size:0.75rem">No Tuya devices. Configure tuya.devices in config.yaml.</div>';
    setIndicator('tuya-indicator', '');
    count.textContent = '';
    return;
  }

  setIndicator('tuya-indicator', state.tuya.some(d => !d.error) ? 'on' : 'err');
  count.textContent = `${state.tuya.length} BULB(S)`;

  container.innerHTML = state.tuya.map(d => `
    <div class="device-card">
      <div class="dev-name">${esc(d.name)}</div>
      <div class="dev-ip">${esc(d.ip || '')} &nbsp;·&nbsp; ${esc(d.mode || '')}</div>
      ${d.error ? `<div class="dev-status" style="color:var(--red)">⚠ ${esc(d.error)}</div>` : `
        <div class="dev-status">${d.is_on ? '● ON' : '○ OFF'}</div>
        <div class="ctrl-row">
          <button class="lbtn green" onclick="tuyaToggle('${esc(d.name)}', ${d.is_on})">${d.is_on ? 'Turn OFF' : 'Turn ON'}</button>
        </div>
        <div class="ctrl-row" style="margin-top:8px">
          <span class="ctrl-label">Bright</span>
          <input type="range" min="10" max="1000" value="${d.brightness || 500}"
            oninput="tuyaBrightness('${esc(d.name)}', this.value)">
        </div>
        <div class="color-row">
          <span style="font-size:0.65rem;color:var(--dim);width:80px">Color</span>
          <input type="color" value="#ffffff" onchange="tuyaColor('${esc(d.name)}', this.value)">
          <span style="font-size:0.65rem;color:var(--dim)">temp (K)</span>
          <input type="range" min="2700" max="6500" step="100" value="4000"
            oninput="tuyaColorTemp('${esc(d.name)}', this.value)">
        </div>
      `}
    </div>
  `).join('');
}

async function tuyaColorTemp(name, kelvin) {
  await api('POST', `/api/lighting/${encodeURIComponent(name)}/temp`, { kelvin });
}

// ════════════════════════════════════════════════════════════════════════════
// ECOFLOW
// ════════════════════════════════════════════════════════════════════════════

async function ecoRefresh() {
  const data = await api('GET', '/api/climate/status');
  state.ecoflow = data;
  renderEcoflow();
}

async function ecoPower(on) {
  setAction(`Wave 2: ${on ? 'ON' : 'OFF'}`);
  const r = await api('POST', '/api/climate/power', { state: on });
  if (r.error) toast('EcoFlow: ' + r.error, 'var(--red)');
  else toast(`AC ${on ? 'ON' : 'OFF'}`, on ? 'var(--green)' : 'var(--red)');
}

async function ecoMode(mode) {
  setAction(`Wave 2 mode: ${mode}`);
  document.querySelectorAll('[id^=mode-]').forEach(b => b.classList.remove('active'));
  document.getElementById('mode-' + mode)?.classList.add('active');
  const r = await api('POST', '/api/climate/mode', { mode });
  if (r.error) toast('Mode error: ' + r.error, 'var(--red)');
}

async function ecoFan(speed) {
  setAction(`Fan: ${speed}`);
  const r = await api('POST', '/api/climate/fan', { speed });
  if (r.error) toast('Fan error: ' + r.error, 'var(--red)');
}

async function ecoTempAdj(delta) {
  state.ecoSetTemp = Math.max(16, Math.min(30, state.ecoSetTemp + delta));
  document.getElementById('eco-set-temp').textContent = state.ecoSetTemp;
  const r = await api('POST', '/api/climate/temperature', { temp: state.ecoSetTemp });
  if (r.error) toast('Temp error: ' + r.error, 'var(--red)');
}

function renderEcoflow() {
  const d = state.ecoflow;
  const s = d.state || {};

  const connected = d.connected;
  setIndicator('eco-indicator', connected ? 'on' : 'warn');

  const note = document.getElementById('eco-setup-note');
  note.style.display = (!connected && d.mode === 'mqtt_local') ? '' : 'none';

  document.getElementById('eco-temp').textContent     = s.temp     != null ? s.temp     : '--';
  document.getElementById('eco-set-temp').textContent = s.setTemp  != null ? s.setTemp  : '--';
  if (s.setTemp) state.ecoSetTemp = s.setTemp;

  const modeNames = ['Cool', 'Heat', 'Fan'];
  document.getElementById('eco-mode-label').textContent =
    s.workMode != null ? modeNames[s.workMode] || '' : '';

  const table = document.getElementById('eco-table');
  const rows = [
    ['Status',       d.connected ? 'MQTT Connected' : 'Not Connected'],
    ['Serial',       d.serial_number || '--'],
    ['Battery',      s.batSoc    != null ? s.batSoc + '%' : '--'],
    ['Charging',     s.batInputWatts != null ? s.batInputWatts + 'W' : '--'],
    ['Draw',         s.outWatts  != null ? s.outWatts + 'W' : '--'],
    ['Fan Level',    s.fanLevel  != null ? ['Low','Mid','High'][s.fanLevel] || s.fanLevel : '--'],
    ['Compressor',   s.condenser ? 'ON' : (s.condenser === false ? 'OFF' : '--')],
  ];
  table.innerHTML = rows.map(([k, v]) =>
    `<tr><td>${k}</td><td>${v}</td></tr>`
  ).join('');
}

// ════════════════════════════════════════════════════════════════════════════
// ARDUINO IR + RF
// ════════════════════════════════════════════════════════════════════════════

function _arduinoOnline() {
  document.getElementById('arduino-status').textContent = 'Arduino ONLINE';
}

// IR send (also used for RF devices — backend routes by device type)
async function irSend(device, command) {
  setAction(`IR → ${device}: ${command}`);
  const r = await api('POST', `/api/ir/${device}/${command}`);
  if (r.error) {
    toast(`${r.error}`, 'var(--red)');
    setIndicator('proj-indicator', 'err');
    setIndicator('sb-indicator', 'err');
  } else {
    toast(`Sent: ${command}`, 'var(--green)');
    setIndicator(device === 'projector' ? 'proj-indicator' : 'sb-indicator', 'on');
    _arduinoOnline();
  }
}

async function projectorOff() {
  const btn = document.getElementById('proj-off-btn');
  btn.disabled = true;
  btn.textContent = '…';
  await irSend('projector', 'power');
  await new Promise(r => setTimeout(r, 3000));
  await irSend('projector', 'power');
  btn.disabled = false;
  btn.textContent = 'OFF';
}

// Fan commands go through the same /api/ir/ endpoint — backend routes to RF
async function fanCmd(command) {
  setAction(`Fan: ${command}`);
  const r = await api('POST', `/api/ir/ceiling_fan/${command}`);
  if (r.error) {
    toast(`Fan error: ${r.error}`, 'var(--red)');
    setIndicator('fan-indicator', 'err');
  } else {
    toast(`Fan: ${command}`, 'var(--green)');
    setIndicator('fan-indicator', 'on');
    _arduinoOnline();
    // Highlight active speed button
    ['fan-low','fan-med','fan-high'].forEach(id =>
      document.getElementById(id)?.classList.remove('active')
    );
    const speedMap = { fan_low: 'fan-low', fan_medium: 'fan-med', fan_high: 'fan-high' };
    if (speedMap[command]) document.getElementById(speedMap[command])?.classList.add('active');
  }
}

// IR learner
async function irLearn() {
  const device  = document.getElementById('learn-device').value.trim();
  const command = document.getElementById('learn-command').value.trim();
  if (!device || !command) { toast('Enter device and command name', 'var(--yellow)'); return; }

  toast('Point IR remote at Arduino and hold button…', 'var(--yellow)');
  const r = await api('GET', '/api/ir/learn', { device, command });
  const res = document.getElementById('learn-result');
  if (r.error) {
    res.style.color = 'var(--red)';
    res.textContent = '⚠ ' + r.error;
  } else if (r.code) {
    res.style.color = 'var(--green)';
    res.textContent = `✓ ${device}/${command} = ${r.code}  protocol:${r.protocol}  (add to config.yaml)`;
  }
}

// RF learner
async function rfLearn() {
  const device  = document.getElementById('rf-learn-device').value.trim();
  const command = document.getElementById('rf-learn-command').value.trim();
  if (!device || !command) { toast('Enter device and command name', 'var(--yellow)'); return; }

  toast('Hold RF remote near receiver and press button…', 'var(--yellow)');
  const r = await api('GET', '/api/rf/learn', { device, command });
  const res = document.getElementById('rf-learn-result');
  if (r.error) {
    res.style.color = 'var(--red)';
    res.textContent = '⚠ ' + r.error;
  } else if (r.code) {
    res.style.color = 'var(--green)';
    res.textContent = `✓ ${device}/${command} = ${r.code}  bits:${r.bits}  protocol:${r.protocol}  (add to config.yaml)`;
    _arduinoOnline();
  }
}

// ════════════════════════════════════════════════════════════════════════════
// ROKU
// ════════════════════════════════════════════════════════════════════════════

async function rokuDiscover() {
  toast('Scanning for Roku…');
  const data = await api('GET', '/api/roku/discover');
  if (data.length) {
    setIndicator('roku-indicator', 'on');
    const d = data[0];
    document.getElementById('roku-info').textContent =
      `${d.friendly_device_name || d.user_device_name || 'Roku'} · ${d.software_version || ''}`;
    toast(`Roku found: ${d.friendly_device_name || 'OK'}`);
    rokuLoadApps();
  } else {
    toast('No Roku found on network', 'var(--red)');
    setIndicator('roku-indicator', 'err');
  }
}

async function rokuKey(key) {
  setAction(`Roku: ${key}`);
  const r = await api('POST', `/api/roku/keypress/${key}`);
  if (r.error) toast('Roku: ' + r.error, 'var(--red)');
}

async function rokuLoadApps() {
  const apps = await api('GET', '/api/roku/apps');
  if (!Array.isArray(apps)) return;
  state.roku.apps = apps;
  const grid = document.getElementById('roku-apps');
  grid.innerHTML = apps.map(a =>
    `<button class="app-btn" onclick="rokuLaunch('${esc(a.id)}', '${esc(a.name)}')">${esc(a.name)}</button>`
  ).join('');
}

async function rokuLaunch(appId, name) {
  setAction(`Roku: Launch ${name}`);
  const r = await api('POST', `/api/roku/launch/${appId}`);
  if (r.error) toast('Roku: ' + r.error, 'var(--red)');
  else toast(`Launched: ${name}`);
}

// ════════════════════════════════════════════════════════════════════════════
// SCENES
// ════════════════════════════════════════════════════════════════════════════

async function movieMode() {
  const btn = document.getElementById('movie-btn');
  const steps = document.getElementById('movie-steps');
  btn.disabled = true;
  btn.textContent = '⏳ ACTIVATING…';
  steps.innerHTML = '<div style="color:var(--dim);font-size:0.7rem">Sending commands… (~6 s)</div>';
  toast('Movie Mode activating…', 'var(--yellow)');

  const r = await api('POST', '/api/scene/movie');

  btn.disabled = false;
  btn.textContent = '▶ ACTIVATE';

  if (r.error) {
    toast('Scene error: ' + r.error, 'var(--red)');
    steps.innerHTML = `<div style="color:var(--red);font-size:0.7rem">Error: ${esc(r.error)}</div>`;
    return;
  }

  toast('Movie Mode activated!', 'var(--green)');
  setAction('Scene: Movie Mode');

  const labels = {
    office_plug_off:  'Office plug off',
    projector_on:     'Projector on',
    soundbar_on:      'Soundbar on',
    soundbar_optical: 'Soundbar → Optical',
  };
  steps.innerHTML = Object.entries(r.steps || {}).map(([k, v]) => {
    const ok = !v?.error;
    const color = ok ? 'var(--green)' : 'var(--red)';
    const sym   = ok ? '✓' : '✗';
    const detail = v?.error || (v?.sent ? 'sent' : v?.alias ? 'ok' : '');
    return `<div style="font-size:0.7rem;color:${color};margin-top:3px">${sym} ${labels[k] || k}${detail ? ' · ' + esc(String(detail)) : ''}</div>`;
  }).join('');
}

// ════════════════════════════════════════════════════════════════════════════
// Utilities
// ════════════════════════════════════════════════════════════════════════════

function esc(str) {
  return String(str ?? '').replace(/[&<>"']/g, c => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  })[c]);
}

function hexToRgb(hex) {
  const n = parseInt(hex.slice(1), 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}

function rgbToHsv(r, g, b) {
  r /= 255; g /= 255; b /= 255;
  const max = Math.max(r, g, b), min = Math.min(r, g, b), d = max - min;
  let h = 0;
  const s = max === 0 ? 0 : d / max;
  const v = max;
  if (d !== 0) {
    if (max === r) h = (g - b) / d + (g < b ? 6 : 0);
    else if (max === g) h = (b - r) / d + 2;
    else h = (r - g) / d + 4;
    h /= 6;
  }
  return [h, s, v];
}

// ════════════════════════════════════════════════════════════════════════════
// Init
// ════════════════════════════════════════════════════════════════════════════

(async function init() {
  connectWS();

  // Load initial data
  const [kasaData, tuyaData, ecoData] = await Promise.all([
    api('GET', '/api/kasa/devices'),
    api('GET', '/api/lighting/devices'),
    api('GET', '/api/climate/status'),
  ]);

  if (Array.isArray(kasaData))  { state.kasa = kasaData;   renderKasa(); }
  if (Array.isArray(tuyaData))  { state.tuya = tuyaData;   renderTuya(); }
  if (ecoData && !ecoData.error){ state.ecoflow = ecoData; renderEcoflow(); }
})();
