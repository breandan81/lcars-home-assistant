'use strict';

// ── State ─────────────────────────────────────────────────────────────────
const state = {
  kasa: [],
  tuya: [],
  groups: [],
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
const NAV_SECTIONS = [...document.querySelectorAll('.nav-btn')].map(b => b.dataset.section);

function showSection(name) {
  document.querySelectorAll('.nav-btn').forEach(b => b.classList.remove('active'));
  document.querySelectorAll('.section').forEach(s => s.classList.remove('active'));
  const btn = document.querySelector(`.nav-btn[data-section="${name}"]`);
  if (btn) {
    btn.classList.add('active');
    // Scroll only nav-scroll, not the sidebar (overflow:hidden makes sidebar a scroll
    // container too, so scrollIntoView would scroll it and clip the first button).
    const navScroll = btn.closest('.nav-scroll');
    if (navScroll) {
      const sr = navScroll.getBoundingClientRect();
      const br = btn.getBoundingClientRect();
      const delta = (br.top + br.height / 2) - (sr.top + sr.height / 2);
      navScroll.scrollBy({ top: delta, behavior: 'smooth' });
    }
  }
  const sec = document.getElementById('section-' + name);
  if (sec) {
    sec.classList.add('active');
    document.getElementById('content-area').scrollTop = 0;
  }
  if (name === 'learn') learnInit();
  if (name === 'ready-room') rokuEnsureConnected();
}

document.querySelectorAll('.nav-btn').forEach(btn => {
  btn.addEventListener('click', () => showSection(btn.dataset.section));
});

// ── Swipe to change section ───────────────────────────────────────────────
(function () {
  const content = document.getElementById('content-area');
  let x0 = 0, y0 = 0, swipeLocked = false;

  content.addEventListener('touchstart', e => {
    x0 = e.touches[0].clientX;
    y0 = e.touches[0].clientY;
    swipeLocked = !!e.target.closest('input, select, textarea, button');
  }, { passive: true });

  content.addEventListener('touchend', e => {
    if (swipeLocked) return;
    const dx = e.changedTouches[0].clientX - x0;
    const dy = e.changedTouches[0].clientY - y0;
    if (Math.abs(dx) < 60 || Math.abs(dx) < Math.abs(dy)) return; // too short or mostly vertical
    const active = document.querySelector('.nav-btn.active')?.dataset.section;
    const idx = NAV_SECTIONS.indexOf(active);
    const next = dx < 0 ? NAV_SECTIONS[idx + 1] : NAV_SECTIONS[idx - 1];
    if (next) showSection(next);
  }, { passive: true });
})();

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

  const office = state.kasa.find(d => d.alias.toLowerCase() === 'office');
  const rrPlug = document.getElementById('rr-office-plug');
  if (rrPlug) {
    if (office) {
      setIndicator('rr-office-indicator', office.is_on ? 'on' : '');
      rrPlug.innerHTML = `
        <div class="dev-status">${office.is_on ? '● ON' : '○ OFF'}</div>
        <div class="ctrl-row" style="margin-top:6px">
          <button class="lbtn ${office.is_on ? 'green' : 'red'}" onclick="kasaToggle('${esc(office.alias)}', ${office.is_on})">${office.is_on ? 'Turn OFF' : 'Turn ON'}</button>
        </div>`;
    } else {
      rrPlug.innerHTML = '<div style="color:var(--dim);font-size:0.75rem">Not found</div>';
    }
  }

  container.innerHTML = state.kasa.map(d => `
    <div class="device-card">
      <div class="dev-name">${esc(d.alias)}</div>
      <div class="dev-ip">${esc(d.host || '')} &nbsp;·&nbsp; ${esc(d.model || '')}</div>
      <div class="dev-status">${d.error ? '⚠ ' + esc(d.error) : (d.is_on ? '● ON' : '○ OFF')}</div>
      <div class="ctrl-row">
        <button class="lbtn ${d.is_on ? 'green' : 'red'}" onclick="kasaToggle('${esc(d.alias)}', ${d.is_on})">${d.is_on ? 'Turn OFF' : 'Turn ON'}</button>
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
  const [devices, groups] = await Promise.all([
    api('GET', '/api/lighting/devices'),
    api('GET', '/api/lighting/groups'),
  ]);
  if (Array.isArray(devices)) { state.tuya = devices; renderTuya(); }
  if (Array.isArray(groups))  { state.groups = groups; renderGroups(); }
}

async function tuyaRelogin() {
  setAction('AiDot: re-logging in…');
  const result = await api('POST', '/api/lighting/refresh');
  if (result && typeof result.count === 'number') {
    setAction(`AiDot: found ${result.count} device(s)`);
    if (Array.isArray(result.devices)) { state.tuya = result.devices; renderTuya(); }
    const groups = await api('GET', '/api/lighting/groups');
    if (Array.isArray(groups)) { state.groups = groups; renderGroups(); }
  } else {
    setAction('AiDot re-login failed — check server logs');
  }
}

async function groupToggle(name, currentlyOn) {
  setAction(`Group ${name}: ${!currentlyOn ? 'ON' : 'OFF'}`);
  await api('POST', `/api/lighting/group/${encodeURIComponent(name)}/power`, { state: !currentlyOn });
  tuyaRefresh();
}

async function groupBrightness(name, val) {
  await api('POST', `/api/lighting/group/${encodeURIComponent(name)}/brightness`, { value: val });
}

async function groupColor(name, hex) {
  const [r, g, b] = hexToRgb(hex);
  const [h, s, v] = rgbToHsv(r, g, b);
  await api('POST', `/api/lighting/group/${encodeURIComponent(name)}/color`, {
    h: Math.round(h * 360), s: Math.round(s * 100), v: Math.round(v * 100)
  });
}

async function groupColorTemp(name, kelvin) {
  await api('POST', `/api/lighting/group/${encodeURIComponent(name)}/temp`, { kelvin });
}

function renderGroups() {
  const groups = state.groups || [];
  const panel = document.getElementById('groups-panel');
  const container = document.getElementById('light-groups');
  if (!groups.length) { panel.style.display = 'none'; return; }
  panel.style.display = '';
  setIndicator('groups-indicator', 'on');

  const html = groups.map(g => `
    <div class="device-card">
      <div class="dev-name">${esc(g.name)}</div>
      <div class="dev-status">${g.is_on ? '● ON' : '○ OFF'} &nbsp;·&nbsp; ${g.devices.length} bulb(s)</div>
      <div class="ctrl-row">
        <button class="lbtn green" onclick="groupToggle('${esc(g.name)}', ${g.is_on})">${g.is_on ? 'Turn OFF' : 'Turn ON'}</button>
      </div>
      <div class="ctrl-row" style="margin-top:8px">
        <span class="ctrl-label">Bright</span>
        <input type="range" min="10" max="1000" value="500"
          oninput="groupBrightness('${esc(g.name)}', this.value)">
      </div>
      <div class="color-row">
        <span style="font-size:0.65rem;color:var(--dim);width:80px">Color</span>
        <input type="color" value="#ffffff" onchange="groupColor('${esc(g.name)}', this.value)">
        <span style="font-size:0.65rem;color:var(--dim)">temp (K)</span>
        <input type="range" min="2700" max="6500" step="100" value="4000"
          oninput="groupColorTemp('${esc(g.name)}', this.value)">
      </div>
    </div>
  `).join('');
  container.innerHTML = html;
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

  const tempText    = s.temp    != null ? s.temp    : '--';
  const setTempText = s.setTemp != null ? s.setTemp : '--';
  document.getElementById('eco-temp').textContent     = tempText;
  document.getElementById('eco-set-temp').textContent = setTempText;
  const rrTemp    = document.getElementById('rr-eco-temp');
  const rrSetTemp = document.getElementById('rr-eco-set-temp');
  if (rrTemp)    rrTemp.textContent    = tempText;
  if (rrSetTemp) rrSetTemp.textContent = setTempText;
  if (s.setTemp) state.ecoSetTemp = s.setTemp;

  const modeNames = ['Cool', 'Heat', 'Fan'];
  const modeText = s.workMode != null ? modeNames[s.workMode] || '' : '';
  document.getElementById('eco-mode-label').textContent = modeText;
  const rrModeLabel = document.getElementById('rr-eco-mode-label');
  if (rrModeLabel) rrModeLabel.textContent = modeText;
  setIndicator('rr-eco-indicator', connected ? 'on' : 'warn');

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

function _setArduinoStatus(online) {
  const el = document.getElementById('arduino-status');
  if (el) el.textContent = online ? 'Arduino ONLINE' : 'Arduino OFFLINE';
  if (!online) {
    ['proj-indicator', 'sb-indicator', 'fan-indicator'].forEach(id => setIndicator(id, 'err'));
  }
}

function _arduinoOnline() {
  _setArduinoStatus(true);
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

// ════════════════════════════════════════════════════════════════════════════
// LEARN PAGE
// ════════════════════════════════════════════════════════════════════════════

const learnState = {
  devices: [],
  allCodes: {},
  device: null,        // selected device object
  commandName: '',     // final command name (from dropdown or custom input)
  capturedCode: null,  // { code, protocol?, bits? } from learn endpoint
};

async function learnInit() {
  const [devices, codes, ping] = await Promise.all([
    api('GET', '/api/ir/devices'),
    api('GET', '/api/ir/codes'),
    api('GET', '/api/ir/ping'),
  ]);

  learnState.devices  = Array.isArray(devices) ? devices : [];
  learnState.allCodes = (codes && !codes.error) ? codes : {};

  const label = document.getElementById('learn-arduino-label');
  if (ping.online) {
    label.textContent = `Arduino ONLINE · ${ping.mode}: ${ping.host}`;
    setIndicator('learn-indicator', 'on');
    _arduinoOnline();
  } else {
    label.textContent = 'Arduino OFFLINE';
    setIndicator('learn-indicator', 'err');
  }

  const sel = document.getElementById('learn-dev-select');
  sel.innerHTML = '<option value="">— choose device —</option>' +
    learnState.devices.map(d =>
      `<option value="${esc(d.id)}">${esc(d.name)} (${esc(d.type.toUpperCase())})</option>`
    ).join('');

  learnSetStep(1);
}

function learnSetStep(n) {
  for (let i = 1; i <= 4; i++) {
    const el = document.getElementById(`lstep${i}`);
    if (!el) continue;
    el.classList.remove('active', 'done');
    if (i < n)       el.classList.add('done');
    else if (i === n) el.classList.add('active');
  }
}

function learnSelectDevice(devId) {
  learnState.device = learnState.devices.find(d => d.id === devId) || null;
  learnState.commandName = '';
  learnState.capturedCode = null;

  document.getElementById('learn-captured').innerHTML = '';
  document.getElementById('learn-save-result').innerHTML = '';
  document.getElementById('learn-cmd-custom').value = '';
  document.getElementById('learn-current-code').innerHTML = '';

  if (!learnState.device) { learnSetStep(1); return; }

  const badge = document.getElementById('learn-dev-badge');
  const dev = learnState.device;
  badge.textContent = dev.type.toUpperCase();
  badge.className = 'code-badge ' + (dev.type === 'rf' ? 'rf-badge' : 'ir-badge');
  badge.style.display = '';

  const cmdSel = document.getElementById('learn-cmd-select');
  cmdSel.innerHTML = '<option value="">— choose existing command —</option>' +
    (dev.commands || []).map(c => `<option value="${esc(c)}">${esc(c)}</option>`).join('');

  learnSetStep(2);
}

function learnSelectCommand(cmdName) {
  if (!cmdName) return;
  document.getElementById('learn-cmd-custom').value = '';
  learnState.commandName = cmdName;
  learnState.capturedCode = null;
  document.getElementById('learn-captured').innerHTML = '';
  document.getElementById('learn-save-result').innerHTML = '';
  _learnShowCurrentCode(cmdName);
  _learnUpdateHint();
  learnSetStep(3);
}

function learnCustomCommand(val) {
  const name = val.trim().toLowerCase().replace(/\s+/g, '_');
  learnState.commandName = name;
  learnState.capturedCode = null;
  document.getElementById('learn-captured').innerHTML = '';
  document.getElementById('learn-save-result').innerHTML = '';
  if (name) {
    document.getElementById('learn-cmd-select').value = '';
    _learnShowCurrentCode(name);
    _learnUpdateHint();
    learnSetStep(3);
  } else {
    document.getElementById('learn-current-code').innerHTML = '';
    learnSetStep(2);
  }
}

function _learnShowCurrentCode(cmdName) {
  const el = document.getElementById('learn-current-code');
  const devId = learnState.device?.id;
  const code = learnState.allCodes?.[devId]?.commands?.[cmdName];
  if (code && code !== '0x000000') {
    el.innerHTML = `Current: <span class="code-badge learned">${esc(code)}</span>`;
  } else {
    el.innerHTML = `<span class="code-badge unlearned">Not yet learned</span>`;
  }
}

function _learnUpdateHint() {
  const el = document.getElementById('learn-hint');
  if (!learnState.device) return;
  if (learnState.device.type === 'rf') {
    el.textContent = 'Hold your 433 MHz remote near the receiver module and press the button when ready.';
  } else {
    el.textContent = 'Point your IR remote directly at the Arduino receiver and press the button when ready.';
  }
}

async function learnCapture() {
  const { device, commandName } = learnState;
  if (!device || !commandName) { toast('Select a device and command first', 'var(--yellow)'); return; }

  const btn = document.getElementById('learn-capture-btn');
  const resultEl = document.getElementById('learn-captured');
  btn.disabled = true;
  btn.textContent = '⏳ Listening…';
  resultEl.innerHTML = '<span style="color:var(--yellow)">Waiting for signal — up to 12 s…</span>';
  toast(device.type === 'rf' ? 'Press RF remote button…' : 'Press IR remote button…', 'var(--yellow)');

  const endpoint = device.type === 'rf' ? '/api/rf/learn' : '/api/ir/learn';
  const r = await api('GET', endpoint, { device: device.id, command: commandName });

  btn.disabled = false;
  btn.textContent = '◎ Capture (12s)';

  if (r.error) {
    resultEl.innerHTML = `<span style="color:var(--red)">⚠ ${esc(r.error)}</span>`;
    toast('Capture failed', 'var(--red)');
    return;
  }

  learnState.capturedCode = r;
  learnState.allCodes[device.id] ??= { commands: {} };
  learnState.allCodes[device.id].commands[commandName] = r.code;

  let detail = `Code: <span class="code-badge learned">${esc(r.code)}</span>`;
  if (r.protocol != null) detail += `  &nbsp;Protocol: ${esc(String(r.protocol))}`;
  if (r.bits     != null) detail += `  &nbsp;Bits: ${r.bits}`;
  resultEl.innerHTML = `<span style="color:var(--green)">✓ Captured!</span>&nbsp;&nbsp;${detail}`;
  toast('Signal captured!', 'var(--green)');
  _arduinoOnline();
  learnSetStep(4);
}

async function learnSave() {
  const { device, commandName, capturedCode } = learnState;
  if (!device || !commandName || !capturedCode) {
    toast('Capture a signal first', 'var(--yellow)');
    return;
  }

  const btn = document.getElementById('learn-save-btn');
  const resultEl = document.getElementById('learn-save-result');
  btn.disabled = true;
  btn.textContent = '⏳ Saving…';

  const r = await api('POST', '/api/ir/save-code', {
    device_id: device.id,
    command_name: commandName,
    code: capturedCode.code,
  });

  btn.disabled = false;
  btn.textContent = '✓ Save to config.yaml';

  if (r.error) {
    resultEl.innerHTML = `<span style="color:var(--red)">⚠ ${esc(r.error)}</span>`;
    toast('Save failed', 'var(--red)');
  } else {
    resultEl.innerHTML = `<span style="color:var(--green)">✓ Saved ${esc(device.id)}/${esc(commandName)} = ${esc(capturedCode.code)}</span>`;
    toast('Code saved to config.yaml', 'var(--green)');
    setAction(`Saved: ${device.id}/${commandName}`);
    // Update displayed current code
    _learnShowCurrentCode(commandName);
  }
}

// ════════════════════════════════════════════════════════════════════════════
// ROKU
// ════════════════════════════════════════════════════════════════════════════

async function rokuDiscover() {
  toast('Scanning for Roku…');
  const data = await api('GET', '/api/roku/discover');
  if (!data.length) {
    toast('No Roku found on network', 'var(--red)');
    setIndicator('roku-indicator', 'err');
    return;
  }
  setIndicator('roku-indicator', 'on');
  setIndicator('rr-roku-indicator', 'on');
  const d = data[0];
  if (data.length === 1) {
    const name = d.friendly_device_name || d.user_device_name || 'Roku';
    document.getElementById('roku-info').textContent = `${name} · ${d.software_version || ''}`;
    toast(`Roku found: ${name}`);
    await rokuSelect(d.base_url);
    rokuLoadApps();
  } else {
    // Multiple Rokus on network — show selection buttons
    const btns = data.map(r =>
      `<button class="lbtn dim" style="font-size:0.65rem;padding:2px 6px"
        onclick="rokuPick('${esc(r.base_url)}',
                          '${esc(r.friendly_device_name || r.user_device_name || r.base_url)}')"
      >${esc(r.friendly_device_name || r.user_device_name || r.base_url)}</button>`
    ).join(' ');
    document.getElementById('roku-info').innerHTML = `Pick: ${btns}`;
    toast(`Found ${data.length} Rokus — pick one`, 'var(--yellow)');
  }
}

async function rokuPick(url, name) {
  await rokuSelect(url);
  document.getElementById('roku-info').textContent = name;
  rokuLoadApps();
}

async function rokuSelect(url) {
  await api('POST', '/api/roku/select', {url});
}

async function rokuEnsureConnected() {
  if (state.roku.apps.length > 0) return;
  const apps = await api('GET', '/api/roku/apps');
  if (!Array.isArray(apps) || apps.length === 0) { rokuDiscover(); return; }
  state.roku.apps = apps;
  const html = apps.map(a =>
    `<button class="app-btn" onclick="rokuLaunch('${esc(a.id)}', '${esc(a.name)}')">${esc(a.name)}</button>`
  ).join('');
  document.getElementById('roku-apps').innerHTML = html;
  const rrApps = document.getElementById('rr-roku-apps');
  if (rrApps) rrApps.innerHTML = html;
  setIndicator('roku-indicator', 'on');
  setIndicator('rr-roku-indicator', 'on');
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
  const appsHtml = apps.map(a =>
    `<button class="app-btn" onclick="rokuLaunch('${esc(a.id)}', '${esc(a.name)}')">${esc(a.name)}</button>`
  ).join('');
  document.getElementById('roku-apps').innerHTML = appsHtml;
  const rrApps = document.getElementById('rr-roku-apps');
  if (rrApps) rrApps.innerHTML = appsHtml;
}

async function rokuLaunch(appId, name) {
  setAction(`Roku: Launch ${name}`);
  const r = await api('POST', `/api/roku/launch/${appId}`);
  if (r.error) toast('Roku: ' + r.error, 'var(--red)');
  else toast(`Launched: ${name}`);
}

// ════════════════════════════════════════════════════════════════════════════
// GARAGE
// ════════════════════════════════════════════════════════════════════════════

async function garageTrigger() {
  const btn = document.getElementById('garage-btn');
  const status = document.getElementById('garage-status');
  btn.disabled = true;
  btn.textContent = '⏳ TRIGGERING…';
  const r = await api('POST', '/api/garage/trigger');
  btn.disabled = false;
  btn.textContent = '⊡ TRIGGER';
  if (r.error) {
    toast('Garage error: ' + r.error, 'var(--red)');
    status.style.color = 'var(--red)';
    status.textContent = 'Error: ' + r.error;
  } else {
    toast('Garage triggered', 'var(--lilac)');
    status.style.color = 'var(--dim)';
    status.textContent = 'Last triggered: ' + new Date().toLocaleTimeString();
    setAction('Garage: triggered');
  }
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
// SAMSUNG TV
// ════════════════════════════════════════════════════════════════════════════

function renderSamsungStatus(d) {
  const info = document.getElementById('samsung-info');
  const table = document.getElementById('samsung-table');
  if (info) info.textContent = d.name || '';
  setIndicator('samsung-indicator', d.paired ? 'on' : 'warn');
  if (table) {
    table.innerHTML = [
      ['Host',   d.host || '--'],
      ['Status', d.paired ? 'Paired' : 'Not paired'],
    ].map(([k, v]) => `<tr><td>${k}</td><td>${v}</td></tr>`).join('');
  }
}

async function samsungRefresh() {
  const d = await api('GET', '/api/samsung/status');
  if (!d.error) renderSamsungStatus(d);
}

async function samsungDiscover() {
  const btn = document.getElementById('samsung-discover-btn');
  const el  = document.getElementById('samsung-discovered');
  btn.disabled = true;
  btn.textContent = '⏳ Scanning…';
  el.innerHTML = '<span style="color:var(--dim);font-size:0.75rem">Searching (5 s)…</span>';
  toast('Scanning for Samsung TVs…');

  const devices = await api('GET', '/api/samsung/discover');

  btn.disabled = false;
  btn.textContent = '↺ Discover';

  if (!Array.isArray(devices) || devices.length === 0) {
    el.innerHTML = '<span style="color:var(--dim);font-size:0.75rem">No Samsung TVs found — enter the TV\'s IP address above and click Connect.</span>';
    toast('No Samsung TVs found', 'var(--yellow)');
    return;
  }

  toast(`Found ${devices.length} TV(s)`, 'var(--green)');
  el.innerHTML = devices.map(d => `
    <div class="ctrl-row" style="margin-top:4px">
      <span style="font-size:0.7rem;color:var(--lt-blue);flex:1">${esc(d.name)} &nbsp;·&nbsp; ${esc(d.host)}</span>
      <button class="lbtn tan" style="font-size:0.65rem" onclick="samsungSelect('${esc(d.host)}', '${esc(d.name)}', '${esc(d.mac||'')}')">Select</button>
    </div>
  `).join('');
}

async function samsungProbeManual() {
  const input = document.getElementById('samsung-manual-ip');
  const host = input.value.trim();
  if (!host) return;
  const el = document.getElementById('samsung-discovered');
  el.innerHTML = '<span style="color:var(--dim);font-size:0.75rem">Connecting…</span>';
  const r = await api('GET', '/api/samsung/probe', { host });
  if (r.error || r.detail) {
    el.innerHTML = `<span style="color:var(--red);font-size:0.75rem">Not found: ${esc(r.detail || r.error)}</span>`;
    toast('No Samsung TV at that IP', 'var(--red)');
    return;
  }
  toast(`Found: ${r.name}`, 'var(--green)');
  el.innerHTML = `
    <div class="ctrl-row" style="margin-top:4px">
      <span style="font-size:0.7rem;color:var(--lt-blue);flex:1">${esc(r.name)} &nbsp;·&nbsp; ${esc(r.host)}</span>
      <button class="lbtn tan" style="font-size:0.65rem" onclick="samsungSelect('${esc(r.host)}', '${esc(r.name)}', '${esc(r.mac||'')}')">Select</button>
    </div>`;
}

async function samsungSelect(host, name, mac = '') {
  const r = await api('POST', '/api/samsung/select', { host, name, mac });
  document.getElementById('samsung-discovered').innerHTML = '';
  if (!r.error) {
    renderSamsungStatus(r);
    toast(`Selected: ${name}`, 'var(--green)');
    document.getElementById('samsung-pair-status').innerHTML =
      '<span style="color:var(--yellow)">TV selected — click Pair with TV to authorize.</span>';
  } else {
    toast('Select failed: ' + r.error, 'var(--red)');
  }
}

async function samsungPair() {
  const btn = document.getElementById('samsung-pair-btn');
  const statusEl = document.getElementById('samsung-pair-status');
  btn.disabled = true;
  btn.textContent = '⏳ Waiting…';
  statusEl.innerHTML = '<span style="color:var(--yellow)">Accept the popup on your TV remote — up to 30 s…</span>';
  toast('Check your TV for an authorization popup', 'var(--yellow)');

  const r = await api('POST', '/api/samsung/pair');

  btn.disabled = false;
  btn.textContent = '⇄ Pair with TV';

  if (r.paired) {
    statusEl.innerHTML = '<span style="color:var(--green)">✓ Paired successfully</span>';
    toast('Samsung TV paired!', 'var(--green)');
    setIndicator('samsung-indicator', 'on');
    setAction('Samsung TV: paired');
  } else {
    statusEl.innerHTML = `<span style="color:var(--red)">⚠ ${esc(r.error || 'Pairing failed')}</span>`;
    toast('Pairing failed: ' + (r.error || 'unknown'), 'var(--red)');
  }
  if (r.warning) {
    statusEl.innerHTML += `<br><span style="color:var(--yellow);font-size:0.65rem">${esc(r.warning)}</span>`;
  }
}

async function samsungWake() {
  setAction('Samsung: Power On');
  const r = await api('POST', '/api/samsung/wake');
  if (r.error) {
    toast('Power On failed: ' + r.error, 'var(--red)');
  } else if (r.note) {
    toast('WoL sent — may not work if TV is in deep sleep', 'var(--yellow)');
  } else {
    toast('TV powered on', 'var(--green)');
  }
}

async function samsungKey(key) {
  setAction(`Samsung: ${key}`);
  const r = await api('POST', `/api/samsung/keypress/${key}`);
  if (r.error) {
    toast('Samsung: ' + r.error, 'var(--red)');
    setIndicator('samsung-indicator', 'err');
  } else {
    toast(`Sent: ${key}`, 'var(--green)');
    setIndicator('samsung-indicator', 'on');
  }
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
  const [kasaData, tuyaData, groupData, ecoData, pingData, samsungData] = await Promise.all([
    api('GET', '/api/kasa/devices'),
    api('GET', '/api/lighting/devices'),
    api('GET', '/api/lighting/groups'),
    api('GET', '/api/climate/status'),
    api('GET', '/api/ir/ping'),
    api('GET', '/api/samsung/status'),
  ]);

  if (Array.isArray(kasaData))  { state.kasa = kasaData;     renderKasa(); }
  if (Array.isArray(tuyaData))  { state.tuya = tuyaData;     renderTuya(); }
  if (Array.isArray(groupData)) { state.groups = groupData;  renderGroups(); }
  if (ecoData && !ecoData.error){ state.ecoflow = ecoData;   renderEcoflow(); }

  _setArduinoStatus(pingData?.online === true);
  if (!pingData?.online) toast('Arduino offline — IR/RF unavailable', 'var(--red)');

  if (samsungData && !samsungData.error) renderSamsungStatus(samsungData);

  rokuEnsureConnected();
})();
