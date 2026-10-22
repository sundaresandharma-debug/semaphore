"use strict";
/* ============================== helpers ============================== */
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = s => String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const fmt = n => (n === null || n === undefined || Number.isNaN(n)) ? '-' : Number(n).toLocaleString('en-US');
const sleep = ms => new Promise(r => setTimeout(r, ms));

class ApiError extends Error {
  constructor(message, status, data) { super(message); this.status = status; this.data = data || {}; }
}
/* Every request goes through here, so every failure gets a message a person can act on. */
async function api(path, opts) {
  let res;
  try { res = await fetch(path, {credentials: 'same-origin', ...opts}); }
  catch (e) {
    if (e.name === 'AbortError') throw e;
    throw new ApiError('Could not reach the server. Check your internet connection and try again.', 0);
  }
  const text = await res.text();
  let data = null;
  try { data = JSON.parse(text); } catch (e) { /* not JSON, e.g. a platform error page */ }
  if (!res.ok) {
    let msg = data && data.error;
    if (!msg) msg = res.status === 504 ? 'The server took too long to answer. Try smaller settings.'
      : res.status >= 500 ? 'The server had a problem. Please try again in a moment.'
      : res.status === 404 ? 'That address was not found.' : `The request failed (error ${res.status}).`;
    if (data && data.ref) msg += ` If it keeps happening, quote reference ${data.ref}.`;
    throw new ApiError(msg, res.status, data);
  }
  if (data === null) throw new ApiError('The server sent an unexpected answer. Please reload the page.', res.status);
  return data;
}
const post = (path, body, signal) => api(path, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body || {}), signal});

function fatal(msg) {
  const skel = $('#bootSkel'); if (skel) skel.remove();
  $('#main').innerHTML = `<div class="fatal" role="alert"><h2>The site could not load</h2>
  <p>${esc(msg)}</p><p>This is usually temporary. Please try again in a moment.</p>
  <p><button class="btn primary" id="retryBoot">Try again</button></p></div>`;
  $('#retryBoot').addEventListener('click', () => location.reload());
}

/* The signal gauge: arm horizontal + red = stop (value 0), arm lowered + green = clear. */
function gauge(name, s, max, big) {
  s = s || {value: '-', waiting: 0};
  const clear = typeof s.value === 'number' && s.value > 0;
  const w = s.waiting || 0;
  const cars = '<i></i>'.repeat(Math.min(w, 8)) + (w > 8 ? `<em>+${w - 8}</em>` : '');
  const maxTxt = max ? `<span class="sig-q" style="color:var(--ink2)">of ${max} permits</span>` : '';
  return `<div class="sig ${clear ? 'clear' : 'stop'} ${big ? 'big' : ''}" role="img" aria-label="${esc(name)}: value ${s.value}, ${w} thread(s) blocked">
    <svg viewBox="0 0 56 56" width="46" height="46" aria-hidden="true">
      <rect x="26" y="7" width="4" height="46" class="pole"/><rect x="19" y="50" width="18" height="4" class="pole"/>
      <g style="transform-origin:28px 12.5px;transform:rotate(${clear ? 38 : 0}deg)">
        <rect class="arm" x="28" y="9" width="24" height="7" rx="1.5"/><rect x="43" y="9" width="5" height="7" fill="#fff" opacity=".85"/></g>
      <circle class="lamp" cx="28" cy="7" r="4.5"/></svg>
    <div class="sig-txt"><span class="sig-name">${esc(name)}</span><span class="sig-val">${s.value}</span>${maxTxt}
      <span class="sig-q">${w ? cars + ' blocked' : 'none blocked'}</span></div></div>`;
}

const STATUS_TEXT = {working: 'working', blocked: 'blocked', active: 'in buffer', done: 'done', aborted: 'stopped',
  idle: 'idle', waiting: 'waiting', reading: 'reading', writing: 'writing', thinking: 'thinking', hungry: 'hungry',
  eating: 'eating', deadlocked: 'deadlocked'};
function actorRows(map, blockedText, countLabel) {
  return Object.entries(map || {}).map(([name, a]) => {
    const st = a.status || 'idle';
    const label = (st === 'blocked' && blockedText) ? blockedText : (STATUS_TEXT[st] || st);
    return `<li class="actor st-${st}"><span class="dot"></span><span class="who"><b>${esc(name)}</b><small>${countLabel}: ${a.count ?? a.ops ?? 0}</small></span><span class="stt">${esc(label)}</span></li>`;
  }).join('');
}

/* =========================== demo renderers =========================== */
const RENDER = {};

RENDER.race = {
  setup(stage) {
    stage.innerHTML = `<div class="lanes">
      <section class="lane" data-lane="u"><h3>Without a semaphore</h3><output class="big" data-k="uc">-</output>
        <p class="sub">expected <b data-k="ue">-</b></p><div class="bar"><i data-k="ub"></i></div>
        <p class="verdict" data-k="uv"></p><ul class="chips" data-k="ur"></ul></section>
      <section class="lane" data-lane="s"><h3>With a BinarySemaphore</h3><output class="big" data-k="sc">-</output>
        <p class="sub">expected <b data-k="se">-</b></p><div class="bar"><i data-k="sb"></i></div>
        <p class="verdict" data-k="sv"></p><div class="gauges" data-k="mx"></div></section></div>
      <div class="tracks" data-k="tracks" aria-label="Progress of each thread"></div>`;
    this.update(stage, {});
  },
  update(stage, st) {
    const q = k => $(`[data-k=${k}]`, stage);
    const exp = st.expected, ph = st.phase;
    const results = st.unsync_results || [];
    q('ue').textContent = fmt(exp); q('se').textContent = fmt(exp);
    q('uc').textContent = fmt(st.unsync_count);
    q('sc').textContent = fmt(st.sync_count);
    q('ub').style.width = exp ? Math.min(100, (st.unsync_count || 0) / exp * 100) + '%' : '0';
    q('sb').style.width = exp ? Math.min(100, (st.sync_count || 0) / exp * 100) + '%' : '0';
    $$('.lane', stage).forEach(l => l.classList.toggle('active', (l.dataset.lane === 'u' && ph === 'unsync') || (l.dataset.lane === 's' && ph === 'sync')));
    const uv = q('uv');
    if (ph === 'unsync') { uv.className = 'verdict'; uv.textContent = `Run ${st.run_no}: the threads are racing...`; }
    else if (results.length) {
      const lost = exp - results[results.length - 1];
      uv.className = 'verdict ' + (lost ? 'bad' : ''); uv.textContent = lost ? `Lost ${fmt(lost)} updates in the last run` : 'No update lost this time (races are random)';
    } else { uv.className = 'verdict'; uv.textContent = ''; }
    const sv = q('sv');
    if (ph === 'sync') { sv.className = 'verdict'; sv.textContent = 'Threads take turns at the semaphore...'; }
    else if (ph === 'done' && st.sync_count !== undefined) {
      sv.className = 'verdict ' + (st.sync_count === exp ? 'good' : 'bad');
      sv.textContent = st.sync_count === exp ? 'Exact: no update lost' : `Lost ${fmt(exp - st.sync_count)} updates`;
    } else { sv.className = 'verdict'; sv.textContent = ''; }
    q('ur').innerHTML = results.map((r, i) => `<li>Run ${i + 1}: <b>${fmt(r)}</b> <span>(lost ${fmt(exp - r)})</span></li>`).join('');
    q('mx').innerHTML = gauge('mutex', st.sem && st.sem.mutex);
    const per = exp && st.threads ? exp / st.threads : 0;
    q('tracks').innerHTML = (st.progress || []).map((p, i) =>
      `<div class="track"><span>Thread ${i + 1}</span><div class="bar"><i style="width:${per ? Math.min(100, p / per * 100) : 0}%"></i></div><span>${per ? Math.round(Math.min(100, p / per * 100)) : 0}%</span></div>`).join('');
  }
};

RENDER.producer_consumer = {
  setup(stage) {
    stage.innerHTML = `<div class="gauges" data-k="g"></div><div class="pc-grid">
      <div><h3>Producers</h3><ul class="actors" data-k="prod"></ul></div>
      <div><h3>Buffer</h3><div class="slots" data-k="slots"></div><p class="flow" data-k="flow">Waiting to start.</p></div>
      <div><h3>Consumers</h3><ul class="actors" data-k="cons"></ul></div></div>`;
    this.update(stage, {});
  },
  update(stage, st) {
    const q = k => $(`[data-k=${k}]`, stage), sem = st.sem || {}, cap = st.capacity || 0;
    q('g').innerHTML = gauge('empty', sem.empty, cap) + gauge('full', sem.full, cap) + gauge('mutex', sem.mutex);
    const buf = st.buffer || [];
    q('slots').innerHTML = Array.from({length: cap}, (_, i) => `<div class="slot ${buf[i] ? 'full' : ''}">${buf[i] ? esc(buf[i]) : 'free'}</div>`).join('');
    q('flow').textContent = st.total ? `Produced ${st.produced} of ${st.total}, consumed ${st.consumed} of ${st.total}. Buffer holds ${buf.length} of ${cap}.` : 'Waiting to start.';
    q('prod').innerHTML = actorRows(st.producers, 'blocked: buffer full', 'made');
    q('cons').innerHTML = actorRows(st.consumers, 'blocked: buffer empty', 'took');
  }
};

RENDER.readers_writers = {
  setup(stage) {
    stage.innerHTML = `<div class="gauges" data-k="g"></div><div class="rw-grid">
      <div><h3>Readers</h3><ul class="actors" data-k="rd"></ul></div>
      <div><div class="resource" data-k="res"><h3>Shared resource</h3><p class="rs" data-k="rs">idle</p>
        <p class="data">a = <b data-k="da">0</b>, b = <b data-k="db">0</b>, version <b data-k="dv">0</b></p></div>
        <p class="rc">read_count = <b data-k="rc">0</b></p><p class="viol" data-k="viol">0 violations detected</p></div>
      <div><h3>Writers</h3><ul class="actors" data-k="wr"></ul></div></div>`;
    this.update(stage, {});
  },
  update(stage, st) {
    const q = k => $(`[data-k=${k}]`, stage), sem = st.sem || {}, d = st.data || {a: 0, b: 0, version: 0};
    q('g').innerHTML = gauge('mutex', sem.mutex) + gauge('rw', sem.rw);
    q('rd').innerHTML = actorRows(st.readers, '', 'reads');
    q('wr').innerHTML = actorRows(st.writers, '', 'writes');
    const ar = st.active_readers || 0, aw = st.active_writers || 0, res = q('res');
    res.className = 'resource ' + (aw ? 'writing' : ar ? 'reading' : '');
    q('rs').textContent = aw ? 'a writer is writing' : ar ? `${ar} reader${ar > 1 ? 's' : ''} reading` : 'idle';
    q('da').textContent = d.a; q('db').textContent = d.b; q('dv').textContent = d.version;
    q('rc').textContent = st.read_count ?? 0;
    const v = st.violations || 0, ve = q('viol');
    ve.className = 'viol ' + (v ? 'bad' : ''); ve.textContent = `${v} violation${v === 1 ? '' : 's'} detected`;
  }
};

RENDER.dining_philosophers = {
  setup(stage) {
    const cx = 220, cy = 220, R = 150, N = 5;
    const pos = (deg, r) => [cx + r * Math.cos(deg * Math.PI / 180), cy + r * Math.sin(deg * Math.PI / 180)];
    let svg = `<svg viewBox="0 0 440 440" role="img" aria-label="Round table with five philosophers and five forks"><circle cx="${cx}" cy="${cy}" r="98" class="table" stroke-width="2"/>`;
    for (let k = 0; k < N; k++) svg += `<line class="fork" data-fork="${k}" x1="0" y1="0" x2="0" y2="0"/>`;
    for (let i = 0; i < N; i++) {
      const [x, y] = pos(-90 + 72 * i, R), [lx, ly] = pos(-90 + 72 * i, 196);
      svg += `<g class="ph s-thinking" data-ph="${i}"><circle class="plate" cx="${x}" cy="${y}" r="33"/>
        <text x="${x}" y="${y - 3}" text-anchor="middle" font-size="15" font-weight="700" class="svg-ink" font-family="Bahnschrift,Segoe UI,sans-serif">P${i}</text>
        <text x="${x}" y="${y + 14}" text-anchor="middle" font-size="12" class="svg-ink2" data-meals="${i}">0 meals</text></g>`;
    }
    svg += `<text x="${cx}" y="${cy - 4}" text-anchor="middle" font-size="14" class="svg-ink2">room</text>
      <text x="${cx}" y="${cy + 22}" text-anchor="middle" font-size="26" font-weight="700" class="svg-ink" font-family="Bahnschrift,Segoe UI,sans-serif" data-k="room">-</text></svg>`;
    stage.innerHTML = `<div class="gauges" data-k="g"></div><div class="dining"><div>${svg}
      <p class="banner" data-k="banner" hidden></p></div>
      <div><h3>Philosophers</h3><ul class="actors" data-k="list"></ul>
      <p class="legend">Each philosopher needs the fork on the left and the fork on the right. A fork turns amber when it is picked up, green while its owner eats, and red when the watchdog gives up.</p></div></div>`;
    this.pos = pos;
    this.update(stage, {});
  },
  update(stage, st) {
    const q = k => $(`[data-k=${k}]`, stage), sem = st.sem || {}, phil = st.phil || {}, forks = st.forks || {};
    q('g').innerHTML = st.use_room === false ? '<p class="muted"><b>Room semaphore is switched off.</b> Nothing stops all five philosophers from picking up their left fork at the same time.</p>'
      : gauge('room', sem.room, st.room_size || 4);
    q('room').textContent = st.use_room === false ? 'off' : (sem.room ? `${sem.room.value} free` : '-');
    $$('[data-ph]', stage).forEach(g => {
      const i = g.dataset.ph, p = phil[i] || {status: 'thinking', meals: 0};
      g.setAttribute('class', `ph s-${p.status}`);
      $(`[data-meals="${i}"]`, g).textContent = `${p.meals ?? 0} meal${p.meals === 1 ? '' : 's'}`;
    });
    $$('[data-fork]', stage).forEach(line => {
      const k = +line.dataset.fork, holder = forks[k];
      let a, b, cls = 'fork';
      if (holder === null || holder === undefined) { a = this.pos(-90 + 72 * k - 36, 66); b = this.pos(-90 + 72 * k - 36, 112); }
      else {
        const side = (k === +holder) ? -16 : 16, deg = -90 + 72 * holder + side;
        a = this.pos(deg, 98); b = this.pos(deg, 118);
        const status = (phil[holder] || {}).status;
        cls += status === 'eating' ? ' eat' : status === 'deadlocked' ? ' dead' : ' held';
      }
      line.setAttribute('class', cls);
      line.setAttribute('x1', a[0]); line.setAttribute('y1', a[1]); line.setAttribute('x2', b[0]); line.setAttribute('y2', b[1]);
    });
    const meals = n => `<li class="actor st-${phil[n].status}"><span class="dot"></span><span class="who"><b>Philosopher ${n}</b><small>meals eaten: ${phil[n].meals}</small></span><span class="stt">${esc(STATUS_TEXT[phil[n].status] || phil[n].status)}</span></li>`;
    q('list').innerHTML = Object.keys(phil).sort().map(meals).join('');
    const b = q('banner');
    b.hidden = !st.deadlock;
    b.textContent = st.deadlock ? 'DEADLOCK detected by the watchdog: every philosopher holds one fork and waits for the next one, forever.' : '';
  }
};

/* ============================ app / navigation ============================ */
const App = {demos: [], views: {}};
const NAV = [
  {id: 'overview', label: 'Overview'},
  {id: 'race', label: 'Race condition'},
  {id: 'producer_consumer', label: 'Producer-consumer'},
  {id: 'readers_writers', label: 'Readers-writers'},
  {id: 'dining_philosophers', label: 'Dining philosophers'},
  {id: 'playground', label: 'Playground', gap: true},
  {id: 'account', label: 'Account', gap: true},
];

function show(id, fromHistory) {
  if (!$('#view-' + id)) id = 'overview';
  const nav = NAV.find(n => n.id === id);
  document.title = id === 'overview' ? 'Semaphore Lab' : `${nav ? nav.label : id} · Semaphore Lab`;
  $$('.view').forEach(v => v.classList.toggle('active', v.id === 'view-' + id));
  $$('.station').forEach(b => b.toggleAttribute('aria-current', b.dataset.id === id));
  $$('.station').forEach(b => { if (b.dataset.id === id) b.setAttribute('aria-current', 'page'); else b.removeAttribute('aria-current'); });
  if (location.hash !== '#' + id) history[fromHistory ? 'replaceState' : 'pushState'](null, '', '#' + id);
  if (id === 'playground') Playground.refresh();
  if (id === 'account') Account.open();
  window.scrollTo(0, 0);
  if (!fromHistory || App.ready) { const h = $('#view-' + id + ' h2'); if (h) { h.setAttribute('tabindex', '-1'); h.focus({preventScroll: true}); } }
}

/* ------------------------------ demo views ------------------------------ */
function paramField(p) {
  if (p.type === 'bool') return `<label class="f chk"><input type="checkbox" name="${p.name}" ${p.default ? 'checked' : ''}> ${esc(p.label)}</label>`;
  const step = p.type === 'float' ? 'any' : '1';
  return `<label class="f">${esc(p.label)}<input type="number" name="${p.name}" min="${p.min}" max="${p.max}" step="${step}" value="${p.default}" required inputmode="${p.type === 'float' ? 'decimal' : 'numeric'}" title="${p.min} to ${p.max}"></label>`;
}

/* Rough run time in seconds for the current settings (the server stops runs at 50 s). */
const TIME_LIMIT = 50;
const ESTIMATE = {
  race: p => p.threads * p.increments * (p.unsync_runs + 1) * 1e-5 + p.phase_pause * (p.unsync_runs + 1),
  producer_consumer: p => Math.max(p.items * p.produce_time, Math.ceil(p.producers * p.items / p.consumers) * p.consume_time) + 0.2,
  readers_writers: p => p.rounds * (p.idle_time + p.read_time) + p.writers * p.rounds * p.write_time + 0.2,
  dining_philosophers: p => p.use_room
    ? Math.max(p.meals * (p.think_time + p.pick_time + p.eat_time), 5 * p.meals * (p.eat_time + p.pick_time) / 2) + 0.2
    : p.watchdog + Math.max(p.pick_time, 0.1) + 1,
};
const fmtSec = s => s < 1 ? 'under 1 s' : s < 90 ? `about ${Math.round(s)} s` : `about ${Math.round(s / 60)} min`;

function buildDemoView(meta) {
  const sec = document.createElement('section');
  sec.className = 'view'; sec.id = 'view-' + meta.id;
  sec.innerHTML = `<header class="vhead"><h2>${esc(meta.title)}</h2><p class="lede">${esc(meta.description)}</p></header>
    <form class="controls" aria-label="Settings for ${esc(meta.title)}">${meta.params.map(paramField).join('')}
      <div class="actions"><span class="badge" data-k="status" role="status">Ready</span>
      <button type="button" class="btn" data-k="stop" disabled>Stop</button>
      <button type="button" class="btn" data-k="quick" title="Run with fast settings and see the verified result in a second or two">Quick run</button>
      <button type="submit" class="btn primary" data-k="run">Run</button></div>
      <div class="form-foot"><span class="est" data-k="est"></span><button type="button" class="linklike" data-k="defaults">Reset to defaults</button></div></form>
    <div class="workspace"><div class="stage-col"><div class="stage" data-k="stage"></div>
      <div class="replaybar"><span class="rb-label">Replay speed</span>
        <div class="seg" role="group" aria-label="Replay speed">${[0.5, 1, 2, 4].map(s => `<button type="button" data-speed="${s}" aria-pressed="${s === 1}">${s}×</button>`).join('')}</div>
        <button type="button" class="btn" data-k="again" disabled title="Play the last run again without running it again">Replay again</button></div></div>
      <aside class="side"><section class="verify" data-k="verify"><h3>Verification</h3>
        <p class="muted">Run the demonstration to see which properties were checked.</p></section>
      <section><h3>Live log</h3><div class="tabs"><button type="button" data-tab="main" class="on">Events</button><button type="button" data-tab="sem">Semaphore trace</button></div>
        <ol class="events" data-k="events"><li><span class="empty">Nothing yet. Press Run.</span></li></ol></section></aside></div>
    <ul class="watch">${meta.watch_for.map(w => `<li>${esc(w)}</li>`).join('')}</ul>`;
  $('#main').appendChild(sec);

  const v = {meta, el: sec, runId: 0, ctrl: null, events: {main: [], sem: []}, tab: 'main', state: {}, speed: 1, last: null};
  App.views[meta.id] = v;
  const q = k => $(`[data-k=${k}]`, sec);
  const renderer = RENDER[meta.id];
  renderer.setup(q('stage'));
  q('stage').insertAdjacentHTML('beforeend', `<div class="pending" data-k="pending" hidden><div class="pend-box">
    <svg viewBox="0 0 56 56" width="54" height="54" aria-hidden="true"><rect x="26" y="7" width="4" height="46" class="pole"/><rect x="19" y="50" width="18" height="4" class="pole"/>
      <g class="pend-arm"><rect x="28" y="9" width="24" height="7" rx="1.5"/></g><circle cx="28" cy="7" r="4.5" class="pend-lamp"/></svg>
    <p><b data-k="ptitle">Running the real Python threads on the server</b><span data-k="ptime">0 s</span></p>
    <small>The animation starts as soon as the run finishes. It is replayed at the speed the threads actually ran.</small></div></div>`);

  $$('.tabs button', sec).forEach(b => b.addEventListener('click', () => {
    v.tab = b.dataset.tab;
    $$('.tabs button', sec).forEach(x => x.classList.toggle('on', x === b));
    renderEvents(v, true);
  }));
  $$('[data-speed]', sec).forEach(b => b.addEventListener('click', () => {
    v.speed = Number(b.dataset.speed);
    $$('[data-speed]', sec).forEach(x => x.setAttribute('aria-pressed', String(x === b)));
  }));
  q('stop').addEventListener('click', () => { if (v.ctrl) v.ctrl.abort(); q('stop').disabled = true; });
  q('quick').addEventListener('click', () => startDemo(v, true));
  q('again').addEventListener('click', () => replayAgain(v));
  sec.addEventListener('click', e => {
    if (e.target.closest('[data-save]')) saveResult(v, e.target.closest('[data-save]'));
    if (e.target.closest('[data-goto-account]')) show('account');
  });
  q('defaults').addEventListener('click', () => {
    meta.params.forEach(p => {
      const i = $(`input[name="${p.name}"]`, sec);
      if (i.type === 'checkbox') i.checked = !!p.default; else i.value = p.default;
    });
    updateEstimate(v);
  });
  $('form', sec).addEventListener('input', () => updateEstimate(v));
  $('form', sec).addEventListener('submit', ev => { ev.preventDefault(); startDemo(v, false); });
  updateEstimate(v);
}

function quickParams(meta) { const o = {}; meta.params.forEach(p => { o[p.name] = p.quick; }); return o; }

function updateEstimate(v) {
  const el = $('[data-k=est]', v.el), form = $('form', v.el);
  if (!form.checkValidity()) { el.className = 'est warn'; el.textContent = 'Some settings are out of range. Hover a field to see its limits.'; return; }
  const s = ESTIMATE[v.meta.id](collectParams(form));
  if (s > TIME_LIMIT - 5) { el.className = 'est warn'; el.textContent = `Estimated run time: ${fmtSec(s)}. The server stops runs at ${TIME_LIMIT} s, so this one will be cut short.`; }
  else { el.className = 'est'; el.textContent = `Estimated run time: ${fmtSec(s)}.`; }
}

function collectParams(form) {
  const out = {};
  $$('input', form).forEach(i => { out[i.name] = i.type === 'checkbox' ? i.checked : Number(i.value); });
  return out;
}

function setBadge(v, cls, text) { const b = $('[data-k=status]', v.el); b.className = 'badge ' + cls; b.textContent = text; }

function setBusy(v, busy) {
  const q = k => $(`[data-k=${k}]`, v.el);
  q('run').disabled = busy; q('quick').disabled = busy; q('again').disabled = busy || !v.last; q('stop').disabled = !busy;
}

function resetStage(v) {
  v.events = {main: [], sem: []};
  renderEvents(v, true);
  RENDER[v.meta.id].update($('[data-k=stage]', v.el), {});
}

async function startDemo(v, quick) {
  const q = k => $(`[data-k=${k}]`, v.el);
  const runId = ++v.runId, ctrl = new AbortController();
  if (v.ctrl) v.ctrl.abort();
  v.ctrl = ctrl;
  resetStage(v);
  q('verify').innerHTML = '<h3>Verification</h3><p class="muted">Waiting for the server...</p>';
  setBusy(v, true); setBadge(v, 'running', 'Running');
  const pend = q('pending'); pend.hidden = false; q('ptime').textContent = '0 s';
  q('ptitle').textContent = quick ? 'Quick run with fast settings' : 'Running the real Python threads on the server';
  const began = performance.now();
  const tick = setInterval(() => {
    const s = Math.round((performance.now() - began) / 1000);
    if (v.runId === runId && !ctrl.signal.aborted) { setBadge(v, 'running', `Running ${s} s`); q('ptime').textContent = `${s} s`; }
  }, 1000);
  try {
    const params = quick ? quickParams(v.meta) : collectParams($('form', v.el));
    v.lastParams = params; v.lastResult = null; renderSaveRow(v);
    const d = await post('/api/run', {demo: v.meta.id, params, record: true}, ctrl.signal);
    clearInterval(tick); pend.hidden = true;
    if (v.runId !== runId) return;
    v.last = d;
    await playRecording(v, d, runId, ctrl);
  } catch (e) {
    clearInterval(tick); pend.hidden = true;
    if (v.runId !== runId) return;
    if (e.name === 'AbortError') return stopped(v);
    setBadge(v, 'fail', 'Error'); q('verify').innerHTML = `<h3>Verification</h3><p class="muted">${esc(e.message)}</p>`;
  } finally {
    clearInterval(tick);
    if (v.runId === runId) { pend.hidden = true; v.ctrl = null; setBusy(v, false); }
  }
}

async function replayAgain(v) {
  if (!v.last) return;
  const runId = ++v.runId, ctrl = new AbortController();
  if (v.ctrl) v.ctrl.abort();
  v.ctrl = ctrl;
  resetStage(v); setBusy(v, true);
  try { await playRecording(v, v.last, runId, ctrl); }
  finally { if (v.runId === runId) { v.ctrl = null; setBusy(v, false); } }
}

function stopped(v) {
  setBadge(v, 'cancelled', 'Stopped');
  $('[data-k=verify]', v.el).innerHTML = '<h3>Verification</h3><p class="muted">Stopped. Press Run to start again' + (v.last ? ', or Replay again to watch the last run.' : '.') + '</p>';
}

async function playRecording(v, d, runId, ctrl) {
  const q = k => $(`[data-k=${k}]`, v.el);
  setBadge(v, 'running', 'Replaying');
  q('verify').innerHTML = '<h3>Verification</h3><p class="muted">Replaying the recorded run...</p>';
  const finished = await replay(v, d, ctrl.signal, (evs, state) => {
    addEvents(v, evs);
    RENDER[v.meta.id].update(q('stage'), state);
  });
  if (v.runId !== runId) return;
  if (!finished) return stopped(v);
  if (d.error) { setBadge(v, 'fail', 'Error'); q('verify').innerHTML = `<h3>Verification</h3><pre class="muted">${esc(d.error)}</pre>`; return; }
  showResult(v, d.result);
  if (d.timed_out) {
    setBadge(v, 'cancelled', 'Time limit');
    q('verify').insertAdjacentHTML('afterbegin', `<p class="limit">This run reached the ${TIME_LIMIT}-second server limit and was stopped early. Use fewer threads, fewer items or shorter times.</p>`);
  }
}

/* Play back the recorded frames at the speed the real threads ran, times v.speed. */
async function replay(v, d, signal, onFrame) {
  const frames = d.frames || [], events = d.events || [];
  let vt = 0, prev = performance.now(), shown = 0;
  for (let i = 0; i < frames.length; i++) {
    const f = frames[i], last = i === frames.length - 1, target = f.t * 1000;
    while (!last && vt < target) {
      if (signal.aborted) return false;
      await sleep(Math.max(4, Math.min(60, (target - vt) / v.speed)));
      const now = performance.now(); vt += (now - prev) * v.speed; prev = now;
    }
    if (signal.aborted) return false;
    const upto = last ? events.length : Math.min(f.seq, events.length);
    onFrame(events.slice(shown, upto), f.state || {});
    shown = Math.max(shown, upto);
  }
  return true;
}

function showResult(v, r) {
  const q = k => $(`[data-k=${k}]`, v.el);
  const cls = {PASS: 'pass', FAIL: 'fail', DEADLOCK: 'deadlock', CANCELLED: 'cancelled'}[r.status] || 'fail';
  setBadge(v, cls, r.status === 'PASS' ? 'Passed' : r.status === 'DEADLOCK' ? 'Deadlock' : r.status === 'CANCELLED' ? 'Stopped' : 'Failed');
  const items = r.checks.map(c => `<li class="${c.info ? 'info' : c.ok ? 'ok' : 'bad'}"><span class="tag">${c.info ? 'Note' : c.ok ? 'Pass' : 'Fail'}</span><span>${esc(c.name)}${c.detail ? `<span class="d">${esc(c.detail)}</span>` : ''}</span></li>`).join('');
  const stats = Object.entries(r.stats).map(([k, val]) => `<dt>${esc(k.replace(/_/g, ' '))}</dt><dd>${esc(Array.isArray(val) ? val.map(fmt).join(', ') : typeof val === 'number' ? fmt(val) : String(val))}</dd>`).join('');
  q('verify').innerHTML = `<h3>Verification (${r.duration.toFixed(2)} s)</h3><ul>${items}</ul><dl class="stats">${stats}</dl>${r.notes.map(n => `<p class="muted">${esc(n)}</p>`).join('')}<div class="save-row" data-k="save"></div>`;
  v.lastResult = r; v.saved = false; renderSaveRow(v);
}

/* ------------------------------- event log ------------------------------- */
function eventLi(e) {
  return `<li class="k-${esc(e.kind)}"><time>${e.t.toFixed(2)}</time><b title="${esc(e.actor)}">${esc(e.actor)}</b><span>${esc(e.msg)}</span></li>`;
}
function addEvents(v, evs) {
  if (!evs.length) return;
  for (const e of evs) v.events[e.ch].push(e);
  const list = $('[data-k=events]', v.el), shown = evs.filter(e => e.ch === v.tab);
  if (!shown.length) return;
  const stick = list.scrollTop + list.clientHeight >= list.scrollHeight - 30;
  if (list.querySelector('.empty')) list.innerHTML = '';
  list.insertAdjacentHTML('beforeend', shown.map(eventLi).join(''));
  while (list.children.length > 400) list.removeChild(list.firstChild);
  if (stick) list.scrollTop = list.scrollHeight;
}
function renderEvents(v, reset) {
  const list = $('[data-k=events]', v.el), arr = v.events[v.tab].slice(-400);
  list.innerHTML = arr.length ? arr.map(eventLi).join('') : '<li><span class="empty">Nothing yet. Press Run.</span></li>';
  list.scrollTop = list.scrollHeight;
}

/* -------------------------------- overview -------------------------------- */
const ICON = {
  race: '<rect x="3" y="5" width="18" height="3"/><rect x="3" y="10.5" width="12" height="3"/><rect x="3" y="16" width="7" height="3"/>',
  producer_consumer: '<rect x="2" y="9" width="5" height="6"/><rect x="9.5" y="9" width="5" height="6"/><rect x="17" y="9" width="5" height="6"/><rect x="1" y="5" width="22" height="1.6"/><rect x="1" y="17.4" width="22" height="1.6"/>',
  readers_writers: '<rect x="3" y="3" width="12" height="18"/><rect x="17" y="3" width="4" height="12"/><path d="M17 16h4l-2 4z"/>',
  dining_philosophers: '<circle cx="12" cy="12.5" r="5"/><circle cx="12" cy="3" r="2"/><circle cx="21" cy="9.5" r="2"/><circle cx="17.5" cy="21" r="2"/><circle cx="6.5" cy="21" r="2"/><circle cx="3" cy="9.5" r="2"/>',
};
const icon = id => `<svg class="ico" viewBox="0 0 24 24" width="22" height="22" aria-hidden="true">${ICON[id] || ''}</svg>`;
const SHORT = {
  race: 'Shared counter: lost updates without a lock, exact with one.',
  producer_consumer: 'Bounded buffer guarded by empty, full and mutex.',
  readers_writers: 'Many readers at once, or exactly one writer.',
  dining_philosophers: 'Five forks, a room semaphore, and no deadlock.',
};

const FACTS = {
  race: s => `Protected counter: ${fmt(s.protected_result)} of ${fmt(s.expected)}. Unprotected runs ended at ${s.unprotected_results.map(fmt).join(', ')}.`,
  producer_consumer: s => `${s.items_consumed} of ${s.items_planned} items consumed exactly once. Buffer peaked at ${s.max_buffer_size} of ${s.capacity}. Producers blocked ${s.producer_blocks} times, consumers ${s.consumer_blocks} times.`,
  readers_writers: s => `${s.reads} reads and ${s.writes} writes with ${s.violations} violations. Up to ${s.max_concurrent_readers} readers at once.`,
  dining_philosophers: s => `Meals eaten: ${s.meals_eaten.join(', ')} (each needed ${s.meals_required}). Fork conflicts: ${s.fork_violations}.`,
};

function buildOverview() {
  const sec = document.createElement('section');
  sec.className = 'view'; sec.id = 'view-overview';
  const rows = App.demos.map(d => `<tr data-row="${d.id}"><td><button class="dname linklike" data-open="${d.id}">${icon(d.id)}${esc(d.title)}</button></td><td><span class="badge" data-k="b">Not run</span></td><td data-k="t">-</td><td data-k="f" class="muted">${esc(SHORT[d.id] || '')}</td></tr>`).join('');
  sec.innerHTML = `<header class="vhead"><h2>Semaphores, built from scratch</h2>
    <p class="lede">A semaphore is a counter that decides how many threads may enter a piece of code at once. This project builds one in Python from just a lock and an event, then proves it works on four classic synchronization problems.</p></header>
    <div class="hero-actions"><button class="btn primary big" id="runAll">Run all four demonstrations</button></div>
    <p class="hint">This uses quick settings so it finishes in a few seconds. Open a demonstration for the slower, animated version.</p>
    <table class="summary"><thead><tr><th>Demonstration</th><th>Result</th><th>Time</th><th>What was verified</th></tr></thead><tbody>${rows}</tbody></table>
    <p class="overall" id="overall" aria-live="polite"></p>
    <aside class="howto"><h3>How this site works</h3>
      <p>Every button runs the project's real Python code on the server: the custom <code>Semaphore</code> class and real threads. A demonstration runs to completion on the server while the semaphores are sampled every 0.1 s. The page then animates those samples at the speed the threads actually ran. Nothing in the animation is simulated in the browser.</p></aside>
    <h3 class="explain-title">The two operations</h3>
    <dl class="explain">
      <dt><code>wait()</code></dt><dd>If a permit is free, take it and carry on. If not, join the back of the queue and sleep. A sleeping thread uses no CPU.</dd>
      <dt><code>signal()</code></dt><dd>If someone is queued, hand the permit straight to the thread at the front. Otherwise add one to the counter.</dd>
      <dt>Why it is safe</dt><dd>The permit goes directly to the waiter, so nobody can sneak in ahead and no wake-up can be lost. The counter is only touched while holding a lock.</dd></dl>`;
  $('#main').appendChild(sec);
  $$('[data-open]', sec).forEach(b => b.addEventListener('click', () => show(b.dataset.open)));
  $('#runAll', sec).addEventListener('click', runAll);
}

function rowSet(id, cls, badge, time, facts) {
  const r = $(`[data-row="${id}"]`);
  const b = $('[data-k=b]', r); b.className = 'badge ' + cls; b.textContent = badge;
  $('[data-k=t]', r).textContent = time; const f = $('[data-k=f]', r); f.textContent = facts; f.className = '';
}
const BADGE = {PASS: ['pass', 'Passed'], FAIL: ['fail', 'Failed'], DEADLOCK: ['deadlock', 'Deadlock'], CANCELLED: ['cancelled', 'Stopped']};

async function runToEnd(body) {
  const d = await post('/api/run', {...body, record: false});
  if (d.error) throw new Error(d.error);
  return d.result;
}

async function runAll() {
  const btns = $$('#runAll'); btns.forEach(b => b.disabled = true);
  $('#overall').textContent = 'Running...';
  let passed = 0;
  try {
    for (const d of App.demos) {
      rowSet(d.id, 'running', 'Running', '-', 'Running...');
      const r = await runToEnd({demo: d.id, params: {}});
      const [cls, text] = BADGE[r.status] || BADGE.FAIL;
      rowSet(d.id, cls, text, r.duration.toFixed(2) + ' s', FACTS[d.id](r.stats) + (r.status === 'DEADLOCK' ? ' Watchdog detected a deadlock.' : ''));
      if (r.status === 'PASS') passed++;
    }
  } catch (e) { $('#overall').textContent = 'Error: ' + e.message; btns.forEach(b => b.disabled = false); return; }
  btns.forEach(b => b.disabled = false);
  $('#overall').textContent = `${passed} of ${App.demos.length} demonstrations passed.`;
}

/* ------------------------------- playground ------------------------------- */
const Playground = {
  built: false, initial: 1, actions: [], t0: performance.now(), busy: false,
  build() {
    const sec = document.createElement('section'); sec.className = 'view'; sec.id = 'view-playground';
    sec.innerHTML = `<header class="vhead"><h2>Playground</h2><p class="lede">Operate a real semaphore by hand. Each button calls <code>wait()</code> or <code>signal()</code> on the Python <code>Semaphore</code> object, from a separate thread.</p></header>
      <form class="controls" id="pgForm"><label class="f">Initial value<input type="number" id="pgInit" min="0" max="5" value="1"></label>
        <div class="actions"><button type="submit" class="btn primary">New semaphore</button></div></form>
      <p class="tip"><b>Try it:</b> start with value 1. Press <b>A</b> wait() (A gets the permit), then B, then C (they queue up). Now press A signal(): the permit goes straight to B, and the counter stays at 0.</p>
      <div class="play"><div class="stage">
        <div class="pg-top"><div class="gauges" id="pgGauge"></div>
          <div class="zone pg-q"><h3>Blocked queue <small class="muted">front of the line is on the right</small></h3>
            <div class="lane-track"><div class="queue" id="pgQueue"></div></div></div></div>
        <div class="zone"><h3>Threads</h3><div class="tbtns" id="pgBtns"></div></div>
        <div class="zone pg-sig"><button class="btn" id="pgSig">signal() from outside</button> <span class="hint">adds a permit, or wakes the thread at the front</span></div></div>
        <aside class="side"><section><h3>Semaphore trace</h3><ol class="events" id="pgTrace"></ol></section></aside></div>`;
    $('#main').appendChild(sec);
    $('#pgForm').addEventListener('submit', e => {
      e.preventDefault();
      const n = Math.max(0, Math.min(5, Math.round(Number($('#pgInit').value) || 0)));
      $('#pgInit').value = n;
      this.initial = n; this.actions = []; this.t0 = performance.now();
      this.refresh();
    });
    $('#pgSig').addEventListener('click', () => this.act({action: 'signal'}));
    $('#pgBtns').addEventListener('click', e => {
      const b = e.target.closest('button[data-act]'); if (b) this.act({action: b.dataset.act, name: b.dataset.name});
    });
    this.built = true;
  },
  /* The server is stateless: every request replays all actions on a fresh, real Semaphore. */
  async act(body) {
    if (this.busy) return;
    this.actions.push({...body, t: (performance.now() - this.t0) / 1000});
    if (!(await this.refresh())) this.actions.pop();
  },
  async refresh() {
    this.busy = true; $('#view-playground').classList.add('busy');
    try { this.render(await post('/api/playground', {initial: this.initial, actions: this.actions})); return true; }
    catch (e) { $('#pgTrace').innerHTML = `<li><span class="empty">Error: ${esc(e.message)}</span></li>`; return false; }
    finally { this.busy = false; $('#view-playground').classList.remove('busy'); }
  },
  render(s) {
    $('#pgGauge').innerHTML = gauge('sem', {value: s.value, waiting: s.waiting}, null, true);
    $('#pgQueue').innerHTML = s.queue.map(n => `<span class="car">${n}</span>`).join('') || '<span class="muted">Nobody is waiting.</span>';
    $('#pgBtns').innerHTML = Object.entries(s.threads).map(([n, st]) => {
      if (st === 'blocked') return `<button class="btn tcard t-blocked" disabled><b>${n}</b><span>blocked in wait()</span></button>`;
      if (st === 'holding') return `<button class="btn tcard t-holding" data-act="release" data-name="${n}"><b>${n}</b><span>holds a permit</span><em>press for signal()</em></button>`;
      return `<button class="btn tcard t-idle" data-act="wait" data-name="${n}"><b>${n}</b><span>${st === 'released' ? 'released' : 'idle'}</span><em>press for wait()</em></button>`;
    }).join('');
    $('#pgTrace').innerHTML = s.trace.map(eventLi).join('') || '<li><span class="empty">No operations yet.</span></li>';
    const t = $('#pgTrace'); t.scrollTop = t.scrollHeight;
  }
};

/* -------------------------------- account -------------------------------- */
const Account = {
  mode: 'signin', notice: '', recovery: null, runs: null, loadingRuns: false,
  build() {
    const sec = document.createElement('section'); sec.className = 'view'; sec.id = 'view-account';
    sec.innerHTML = `<header class="vhead"><h2 tabindex="-1">Account</h2><p class="lede">An account is optional. It only lets you keep demonstration results you choose to save. Every demonstration and the Playground work without one.</p></header>
      <div id="acct" aria-live="polite"></div>`;
    $('#main').appendChild(sec);
    sec.addEventListener('click', e => this.onClick(e));
    sec.addEventListener('submit', e => { e.preventDefault(); this.onSubmit(e.target); });
    sec.addEventListener('input', e => {                       // clear a field's error once it is edited
      const i = e.target; if (!i.name) return;
      i.removeAttribute('aria-invalid'); const slot = $('#err-' + i.name, sec); if (slot) slot.textContent = '';
    });
  },
  open() { this.render(); if (App.auth.user && this.runs === null) this.loadRuns(); },
  set(mode, notice) { this.mode = mode; this.notice = notice || ''; this.render(); },
  field(name, label, type, auto, extra) {
    return `<label class="f wide">${label}<input name="${name}" type="${type}" autocomplete="${auto}" ${extra || ''} aria-describedby="err-${name}"><span class="ferr" id="err-${name}"></span></label>`;
  },
  render() {
    const el = $('#acct'); if (!el) return;
    const note = this.notice ? `<p class="notice" role="status">${esc(this.notice)}</p>` : '';
    if (!App.auth.configured) {
      el.innerHTML = `<div class="panel"><h3>Accounts are not switched on yet</h3><p class="muted">The site owner has not connected the account service on this deployment. Everything else on the site works normally.</p></div>`;
      return;
    }
    if (this.recovery) {
      el.innerHTML = `${note}<form class="panel aform" novalidate data-form="reset"><h3>Choose a new password</h3>
        ${this.field('password', 'New password (at least 8 characters)', 'password', 'new-password', 'minlength="8" maxlength="72" required')}
        ${this.field('confirm', 'Repeat the new password', 'password', 'new-password', 'required')}
        <p class="form-err" role="alert"></p><button class="btn primary" type="submit">Save new password</button></form>`;
      return;
    }
    if (App.auth.user) {
      el.innerHTML = `${note}<div class="panel"><div class="acct-head"><p>Signed in as <b>${esc(App.auth.user.email)}</b></p>
          <button type="button" class="btn" data-act="logout">Sign out</button></div></div>
        <section class="panel"><div class="acct-head"><h3>Saved results</h3><button type="button" class="btn" data-act="delete-runs" ${this.runs && this.runs.length ? '' : 'disabled'}>Delete all saved results</button></div>
          <div id="runsBox">${this.runsHtml()}</div></section>
        <form class="panel aform danger-zone" novalidate data-form="delete"><h3>Delete account</h3>
          <p class="muted">This permanently deletes your account, your email address and every saved result. It cannot be undone.</p>
          ${this.field('password', 'Enter your password to confirm', 'password', 'current-password', 'required')}
          <p class="form-err" role="alert"></p><button class="btn danger" type="submit">Delete my account</button></form>`;
      return;
    }
    if (this.mode === 'check-email') {
      el.innerHTML = `<div class="panel"><h3>Check your email</h3><p>${esc(this.notice)}</p><p><button type="button" class="linklike" data-mode="signin">Back to sign in</button></p></div>`;
      return;
    }
    const tabs = `<div class="tabs acct-tabs" role="tablist"><button type="button" role="tab" data-mode="signin" aria-selected="${this.mode === 'signin'}" class="${this.mode === 'signin' ? 'on' : ''}">Sign in</button><button type="button" role="tab" data-mode="signup" aria-selected="${this.mode === 'signup'}" class="${this.mode === 'signup' ? 'on' : ''}">Create account</button></div>`;
    if (this.mode === 'recover') {
      el.innerHTML = `${note}<form class="panel aform" novalidate data-form="recover"><h3>Reset your password</h3>
        <p class="muted">Enter the email address of your account. If it exists, we will send a link to choose a new password.</p>
        ${this.field('email', 'Email address', 'email', 'email', 'required')}
        <p class="form-err" role="alert"></p><button class="btn primary" type="submit">Send reset link</button>
        <p><button type="button" class="linklike" data-mode="signin">Back to sign in</button></p></form>`;
      return;
    }
    if (this.mode === 'signup') {
      el.innerHTML = `${note}${tabs}<form class="panel aform" novalidate data-form="signup">
        ${this.field('email', 'Email address', 'email', 'email', 'required')}
        ${this.field('password', 'Password (at least 8 characters)', 'password', 'new-password', 'minlength="8" maxlength="72" required')}
        ${this.field('confirm', 'Repeat the password', 'password', 'new-password', 'required')}
        <label class="f chk"><input type="checkbox" name="agree" aria-describedby="err-agree"><span>I agree to the <a href="/terms" target="_blank" rel="noopener">Terms of service</a> and the <a href="/privacy" target="_blank" rel="noopener">Privacy policy</a>.</span></label><span class="ferr" id="err-agree"></span>
        <label class="f chk"><input type="checkbox" name="age" aria-describedby="err-age"><span>I am 18 or older.</span></label><span class="ferr" id="err-age"></span>
        <p class="muted small">Under 18? Please do not create an account. You can use every demonstration without one, and nothing about you is stored.</p>
        <p class="form-err" role="alert"></p><button class="btn primary" type="submit">Create account</button></form>`;
      return;
    }
    el.innerHTML = `${note}${tabs}<form class="panel aform" novalidate data-form="signin">
      ${this.field('email', 'Email address', 'email', 'email', 'required')}
      ${this.field('password', 'Password', 'password', 'current-password', 'required')}
      <p class="form-err" role="alert"></p><button class="btn primary" type="submit">Sign in</button>
      <p><button type="button" class="linklike" data-mode="recover">Forgot your password?</button></p></form>`;
  },
  runsHtml() {
    if (this.loadingRuns || this.runs === null) return `<div aria-busy="true" aria-label="Loading saved results">${'<div class="skel skel-row"></div>'.repeat(3)}</div>`;
    if (!this.runs.length) return `<div class="empty-state"><p><b>No saved results yet.</b></p><p class="muted">Run a demonstration, then press <i>Save this result</i> under its verification list.</p><button type="button" class="btn" data-goto="race">Open the first demonstration</button></div>`;
    const title = id => (App.demos.find(d => d.id === id) || {title: id}).title;
    return `<table class="summary runs"><thead><tr><th>Demonstration</th><th>Result</th><th>Time</th><th>Saved</th><th><span class="sr">Actions</span></th></tr></thead><tbody>${this.runs.map(r => {
      const [cls, text] = BADGE[r.status] || BADGE.FAIL;
      return `<tr><td>${esc(title(r.demo))}<small class="muted block">${esc(r.summary || '')}</small></td><td><span class="badge ${cls}">${text}</span></td><td>${Number(r.duration).toFixed(2)} s</td><td>${esc(new Date(r.created_at).toLocaleString())}</td><td><button type="button" class="linklike" data-del="${r.id}">Delete</button></td></tr>`;
    }).join('')}</tbody></table>`;
  },
  async loadRuns() {
    this.loadingRuns = true; this.render();
    try { const d = await api('/api/account'); this.runs = d.runs; }
    catch (e) { this.runs = null; this.notice = e.message; if (e.status === 401) setUser(null); }
    finally { this.loadingRuns = false; this.render(); }
  },
  async onClick(e) {
    const t = e.target.closest('button'); if (!t) return;
    if (t.dataset.mode) return this.set(t.dataset.mode);
    if (t.dataset.goto) return show(t.dataset.goto);
    if (t.dataset.act === 'logout') {
      t.disabled = true; t.textContent = 'Signing out...';
      try { await post('/api/auth', {action: 'logout'}); } catch (err) { /* the cookies are cleared either way */ }
      setUser(null); this.runs = null; this.set('signin', 'You are signed out.');
    }
    if (t.dataset.act === 'delete-runs') {
      if (!confirm('Delete all of your saved results? This cannot be undone.')) return;
      t.disabled = true;
      try { const d = await post('/api/account', {action: 'delete_runs'}); this.runs = []; this.set('', `Deleted ${d.deleted} saved result${d.deleted === 1 ? '' : 's'}.`); }
      catch (err) { this.set('', err.message); }
    }
    if (t.dataset.del) {
      if (!confirm('Delete this saved result?')) return;
      t.disabled = true;
      try { await post('/api/account', {action: 'delete_run', id: Number(t.dataset.del)}); this.runs = this.runs.filter(r => String(r.id) !== t.dataset.del); this.set('', 'The result was deleted.'); }
      catch (err) { this.set('', err.message); }
    }
  },
  /* Form validation with a clear message next to each field. */
  check(form, rules) {
    let ok = true;
    $$('.ferr', form).forEach(s => { s.textContent = ''; });
    $$('input', form).forEach(i => i.removeAttribute('aria-invalid'));
    for (const [name, test, msg] of rules) {
      const input = form.elements[name];
      if (!test(input)) {
        ok = false; input.setAttribute('aria-invalid', 'true');
        const slot = $('#err-' + name, form); if (slot && !slot.textContent) slot.textContent = msg;
      }
    }
    const first = $('[aria-invalid=true]', form); if (first) first.focus();
    return ok;
  },
  async onSubmit(form) {
    const kind = form.dataset.form, f = form.elements, errBox = $('.form-err', form), btn = $('button[type=submit]', form);
    const EMAIL = i => /^[^@\s]+@[^@\s]+\.[^@\s]{2,}$/.test(i.value.trim());
    const PW = i => i.value.length >= 8 && i.value.length <= 72;
    const rules = {
      signin: [['email', EMAIL, 'Enter a valid email address, like name@example.com.'], ['password', i => i.value.length > 0, 'Enter your password.']],
      signup: [['email', EMAIL, 'Enter a valid email address, like name@example.com.'], ['password', PW, 'Use 8 to 72 characters.'],
        ['confirm', i => i.value === f.password.value && i.value !== '', 'The two passwords do not match.'],
        ['agree', i => i.checked, 'You need to accept the terms to create an account.'], ['age', i => i.checked, 'Accounts are for people aged 18 or older.']],
      recover: [['email', EMAIL, 'Enter a valid email address, like name@example.com.']],
      reset: [['password', PW, 'Use 8 to 72 characters.'], ['confirm', i => i.value === f.password.value && i.value !== '', 'The two passwords do not match.']],
      delete: [['password', i => i.value.length > 0, 'Enter your password to confirm.']],
    }[kind];
    errBox.textContent = '';
    if (!this.check(form, rules)) return;
    if (kind === 'delete' && !confirm('Permanently delete your account and all saved results?')) return;
    const label = btn.textContent; btn.disabled = true;
    btn.textContent = {signin: 'Signing in...', signup: 'Creating account...', recover: 'Sending...', reset: 'Saving...', delete: 'Deleting...'}[kind];
    try {
      if (kind === 'signin') {
        const d = await post('/api/auth', {action: 'login', email: f.email.value.trim(), password: f.password.value});
        setUser(d.user); this.runs = null; this.notice = ''; this.open();
      } else if (kind === 'signup') {
        const d = await post('/api/auth', {action: 'signup', email: f.email.value.trim(), password: f.password.value, agree_terms: f.agree.checked, age_ok: f.age.checked});
        if (d.user) { setUser(d.user); this.runs = []; this.set('', 'Your account is ready.'); }
        else this.set('check-email', `We sent a confirmation link to ${f.email.value.trim()}. Open it on this device to finish creating your account. It may take a minute to arrive; check your spam folder too.`);
      } else if (kind === 'recover') {
        await post('/api/auth', {action: 'recover', email: f.email.value.trim()});
        this.set('check-email', 'If an account exists for that address, a reset link is on its way. The link works once and expires after one hour.');
      } else if (kind === 'reset') {
        const d = await post('/api/auth', {action: 'reset', password: f.password.value, ...this.recovery});
        this.recovery = null; setUser(d.user); this.runs = null; this.notice = 'Your new password is saved and you are signed in.'; this.open();
      } else if (kind === 'delete') {
        await post('/api/account', {action: 'delete_account', password: f.password.value});
        setUser(null); this.runs = null; this.set('signin', 'Your account and all of its data were deleted.');
      }
    } catch (e) {
      errBox.textContent = e.message;
      if (e.status === 401 && kind === 'delete') { /* wrong password: keep the form */ }
    } finally { if (document.body.contains(btn)) { btn.disabled = false; btn.textContent = label; } }
  },
};

function setUser(user) {
  App.auth.user = user;
  const w = $('#whoLine');
  if (w) { w.hidden = !user; w.textContent = user ? `Signed in as ${user.email}` : ''; }
  Object.values(App.views).forEach(renderSaveRow);
}

/* "Save this result" under a finished demonstration. */
function renderSaveRow(v) {
  const box = $('[data-k=save]', v.el);
  if (!box) return;
  if (!App.auth.configured || !v.lastResult || v.lastResult.status === 'CANCELLED') { box.innerHTML = ''; return; }
  if (!App.auth.user) { box.innerHTML = `<p class="muted small">Want to keep this result? <button type="button" class="linklike" data-goto-account>Sign in or create an account</button> (optional).</p>`; return; }
  if (v.saved) { box.innerHTML = `<p class="small saved-ok">Saved to your account.</p>`; return; }
  box.innerHTML = `<button type="button" class="btn" data-save>Save this result</button><span class="small save-msg" role="status"></span>`;
}

async function saveResult(v, btn) {
  const r = v.lastResult; btn.disabled = true; btn.textContent = 'Saving...';
  try {
    await post('/api/account', {action: 'save_run', demo: v.meta.id, status: r.status, duration: r.duration,
      params: v.lastParams || {}, summary: FACTS[v.meta.id] ? FACTS[v.meta.id](r.stats).slice(0, 480) : ''});
    v.saved = true; Account.runs = null; renderSaveRow(v);
  } catch (e) {
    btn.disabled = false; btn.textContent = 'Save this result';
    const m = $('.save-msg', v.el); if (m) m.textContent = e.message;
    if (e.status === 401) setUser(null);
  }
}

/* --------------------- links from emails (confirm / reset) --------------------- */
async function handleAuthLink() {
  const h = location.hash.slice(1);
  if (!/(^|&)(access_token|error_description)=/.test(h)) return false;
  const p = new URLSearchParams(h);
  history.replaceState(null, '', location.pathname + '#account');
  if (p.get('error_description')) { Account.notice = 'This email link has expired or was already used. Please request a new one.'; return true; }
  const tokens = {access_token: p.get('access_token'), refresh_token: p.get('refresh_token'), expires_in: Number(p.get('expires_in')) || 3600};
  if (p.get('type') === 'recovery') { Account.recovery = tokens; return true; }
  try { const d = await post('/api/auth', {action: 'session', ...tokens}); setUser(d.user); Account.notice = 'Your email address is confirmed and you are signed in.'; }
  catch (e) { Account.notice = e.message; }
  return true;
}

/* ------------------------- consent and error reports ------------------------- */
const Consent = {
  get() { try { return JSON.parse(localStorage.getItem('semlab-consent') || 'null'); } catch (e) { return null; } },
  set(errors) {
    try { localStorage.setItem('semlab-consent', JSON.stringify({errors, v: 1, at: new Date().toISOString().slice(0, 10)})); } catch (e) { /* private mode */ }
    $('#consent').hidden = true;
    Intro.maybeStart();
  },
  setup() {
    $('#consentYes').addEventListener('click', () => this.set(true));
    $('#consentNo').addEventListener('click', () => this.set(false));
    $('#cookieSettings').addEventListener('click', () => { $('#consent').hidden = false; $('#consentNo').focus(); });
    if (!this.get()) $('#consent').hidden = false;
  },
};

let reportsSent = 0;
function reportError(message, where, line) {
  const c = Consent.get();
  if (!c || !c.errors || reportsSent >= 5) return;
  reportsSent++;
  fetch('/api/errors', {method: 'POST', keepalive: true, headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({message: String(message).slice(0, 300), where: String(where || '').slice(0, 120), line: String(line || ''), view: location.hash.slice(1, 40)})}).catch(() => {});
}
window.addEventListener('error', e => { let where = ''; try { where = new URL(e.filename).pathname; } catch (x) { /* inline */ } reportError(e.message, where, e.lineno); });
window.addEventListener('unhandledrejection', e => reportError((e.reason && e.reason.message) || e.reason, 'promise', ''));

/* --------------------------------- onboarding --------------------------------- */
const Intro = {
  step: 0,
  steps: [
    ['Welcome to Semaphore Lab', '<p>This site shows a counting semaphore written from scratch in Python, built only from a lock and an event, and uses it to solve four classic synchronization problems.</p><p>Everything you see is produced by the real Python code running on the server.</p>'],
    ['Watch a demonstration', '<p>Pick a problem in the menu, for example <b>Race condition</b>, and press <b>Run</b>. The threads run on the server, then the page replays what they did at the real speed.</p><p>The <b>Verification</b> panel lists every property that was checked.</p>'],
    ['Try it yourself', '<p>In the <b>Playground</b> you call <code>wait()</code> and <code>signal()</code> by hand and watch the queue.</p><p>An account is optional. It only lets you keep results you choose to save.</p>'],
  ],
  done() { try { return localStorage.getItem('semlab-onboarded') === '1'; } catch (e) { return true; } },
  finish() { try { localStorage.setItem('semlab-onboarded', '1'); } catch (e) { /* private mode */ } },
  setup() {
    const dlg = $('#intro');
    $('#introNext').addEventListener('click', () => { if (this.step < this.steps.length - 1) { this.step++; this.render(); } else { this.finish(); dlg.close('done'); } });
    dlg.addEventListener('cancel', () => this.finish());                 // Esc key
    $('form', dlg).addEventListener('submit', () => this.finish());      // Skip introduction
    $('#introBack').addEventListener('click', () => { if (this.step > 0) { this.step--; this.render(); } });
    dlg.addEventListener('close', () => this.finish());
    $('#introAgain').addEventListener('click', () => this.open());
  },
  maybeStart() { if (!this.done() && !$('#intro').open) this.open(); },
  open() { this.step = 0; this.render(); const d = $('#intro'); if (!d.open) d.showModal(); $('#introNext').focus(); },
  render() {
    const [title, body] = this.steps[this.step];
    $('#introStep').textContent = `Step ${this.step + 1} of ${this.steps.length}`;
    $('#introTitle').textContent = title; $('#introBody').innerHTML = body;
    $('#introBack').disabled = this.step === 0;
    $('#introNext').textContent = this.step === this.steps.length - 1 ? 'Start' : 'Next';
  },
};

/* ---------------------------------- theme ---------------------------------- */
function setupTheme() {
  const btn = $('#themeBtn'), order = ['auto', 'light', 'dark'];
  const label = t => ({auto: 'Theme: Auto', light: 'Theme: Light', dark: 'Theme: Dark'})[t];
  let cur = document.documentElement.dataset.theme || 'auto';
  btn.textContent = label(cur);
  btn.addEventListener('click', () => {
    cur = order[(order.indexOf(cur) + 1) % order.length];
    if (cur === 'auto') delete document.documentElement.dataset.theme; else document.documentElement.dataset.theme = cur;
    try { if (cur === 'auto') localStorage.removeItem('semlab-theme'); else localStorage.setItem('semlab-theme', cur); } catch (e) {}
    btn.textContent = label(cur);
  });
}

/* ---------------------------------- boot ---------------------------------- */
async function boot() {
  if (location.protocol === 'file:') return fatal('This page was opened as a file, but it needs the Python backend to run the semaphores.');
  App.auth = {configured: false, user: null};
  let auth;
  try { [App.demos, auth] = await Promise.all([api('/api/catalog'), api('/api/auth').catch(() => ({configured: false, user: null}))]); }
  catch (e) { return fatal(e.message); }
  App.auth.configured = !!auth.configured;
  $('#bootSkel').remove();
  $('#stations').innerHTML = NAV.map(n => `<li class="${n.gap ? 'gap' : ''}"><button class="station" data-id="${n.id}">${esc(n.label)}</button></li>`).join('');
  $('#stations').addEventListener('click', e => { const b = e.target.closest('.station'); if (b) show(b.dataset.id); });
  setupTheme();
  buildOverview();
  App.demos.forEach(buildDemoView);
  Playground.build(); Account.build();
  setUser(auth.user || null);
  const fromEmail = await handleAuthLink();
  window.addEventListener('popstate', async () => {
    if (await handleAuthLink()) { Account.render(); show('account', true); return; }   // email link opened in this tab
    show(location.hash.slice(1), true);
  });
  show(fromEmail ? 'account' : (location.hash.slice(1) || 'overview'), true);
  App.ready = true;
  Consent.setup(); Intro.setup();
  if (Consent.get()) Intro.maybeStart();
}
boot();
