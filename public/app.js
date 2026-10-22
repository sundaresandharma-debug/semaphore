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

const STATUS_TEXT = {done: 'done', aborted: 'stopped', waiting: 'waiting', thinking: 'thinking', hungry: 'hungry',
  eating: 'eating', deadlocked: 'deadlocked'};
/* =========================== demo renderers =========================== */
const RENDER = {};

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
  {id: 'dining_philosophers', label: 'Dining philosophers'},
  {id: 'playground', label: 'Playground', gap: true},
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
        <div class="seg" role="group" aria-label="Replay speed">${[0.25, 0.5, 1, 2, 4].map(s => `<button type="button" data-speed="${s}" aria-pressed="${s === 1}">${s}×</button>`).join('')}</div>
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
  q('verify').innerHTML = `<h3>Verification (${r.duration.toFixed(2)} s)</h3><ul>${items}</ul><dl class="stats">${stats}</dl>${r.notes.map(n => `<p class="muted">${esc(n)}</p>`).join('')}`;
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
  dining_philosophers: '<circle cx="12" cy="12.5" r="5"/><circle cx="12" cy="3" r="2"/><circle cx="21" cy="9.5" r="2"/><circle cx="17.5" cy="21" r="2"/><circle cx="6.5" cy="21" r="2"/><circle cx="3" cy="9.5" r="2"/>',
};
const icon = id => `<svg class="ico" viewBox="0 0 24 24" width="22" height="22" aria-hidden="true">${ICON[id] || ''}</svg>`;
const FACTS = s => `Meals eaten: ${s.meals_eaten.join(', ')} (each needed ${s.meals_required}). Fork conflicts: ${s.fork_violations}.`;

// The overview runs the Dining Philosophers twice. Without the room semaphore, the pause between
// the two forks makes all five philosophers hold their left fork at once, so the table deadlocks.
const VERSIONS = [
  {id: 'room', title: 'With the room semaphore', params: {use_room: true}, expect: 'PASS',
   short: 'At most four philosophers at the table, so deadlock is impossible.'},
  {id: 'noroom', title: 'Without the room semaphore', params: {use_room: false, pick_time: 0.1, watchdog: 1}, expect: 'DEADLOCK',
   short: 'All five can pick up their left fork at once, so the table can deadlock.'},
];

function buildOverview() {
  const sec = document.createElement('section');
  sec.className = 'view'; sec.id = 'view-overview';
  const rows = VERSIONS.map(v => `<tr data-row="${v.id}"><td><button class="dname linklike" data-open="dining_philosophers">${icon('dining_philosophers')}${esc(v.title)}</button></td><td><span class="badge" data-k="b">Not run</span></td><td data-k="t">-</td><td data-k="f" class="muted">${esc(v.short)}</td></tr>`).join('');
  sec.innerHTML = `<header class="vhead"><h2>Semaphores, built from scratch</h2>
    <p class="lede">A semaphore is a counter that decides how many threads may enter a piece of code at once. This project builds one in Python from just a lock and an event, then uses it to solve the Dining Philosophers problem: five philosophers, five forks, and no deadlock.</p></header>
    <div class="hero-actions"><button class="btn primary big" id="runAll">Run both versions</button></div>
    <p class="hint">This runs the demonstration twice with quick settings: with the room semaphore it should pass, and without it the watchdog should detect a deadlock. Open Dining philosophers for the slower, animated version.</p>
    <table class="summary"><thead><tr><th>Version</th><th>Result</th><th>Time</th><th>What was verified</th></tr></thead><tbody>${rows}</tbody></table>
    <p class="overall" id="overall" aria-live="polite"></p>
    <aside class="howto"><h3>The Dining Philosophers problem</h3>
      <p>Five philosophers sit at a round table with one fork between each pair. To eat, a philosopher needs both the left and the right fork. If all five pick up their left fork at the same moment, each waits forever for the right one: a <b>deadlock</b>. Here every fork is a binary semaphore, and a counting semaphore called the <b>room</b> lets at most four philosophers sit down, so at least one can always eat.</p></aside>
    <aside class="howto"><h3>How this site works</h3>
      <p>Every button runs the project's real Python code on the server: the custom <code>Semaphore</code> class and real threads. A run finishes on the server while the semaphores are sampled every 0.1 s. The page then animates those samples at the speed the threads actually ran. Nothing in the animation is simulated in the browser.</p></aside>
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
  let expected = 0;
  try {
    for (const v of VERSIONS) {
      rowSet(v.id, 'running', 'Running', '-', 'Running...');
      const r = await runToEnd({demo: 'dining_philosophers', params: v.params});
      const [cls, text] = BADGE[r.status] || BADGE.FAIL;
      const note = r.status === 'DEADLOCK' ? ' The watchdog detected the deadlock and stopped the run.' : '';
      rowSet(v.id, cls, text, r.duration.toFixed(2) + ' s', FACTS(r.stats) + note);
      if (r.status === v.expect) expected++;
    }
  } catch (e) { $('#overall').textContent = 'Error: ' + e.message; btns.forEach(b => b.disabled = false); return; }
  btns.forEach(b => b.disabled = false);
  $('#overall').textContent = expected === VERSIONS.length
    ? 'Both versions behaved as expected: no deadlock with the room semaphore, deadlock detected without it.'
    : 'A version did not give the expected result.';
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

/* --------------------------------- onboarding --------------------------------- */
const Intro = {
  step: 0,
  steps: [
    ['Welcome to Semaphore Lab', '<p>This site shows a counting semaphore written from scratch in Python, built only from a lock and an event, and uses it to solve the Dining Philosophers problem.</p><p>Everything you see is produced by the real Python code running on the server.</p>'],
    ['Watch a demonstration', '<p>Open <b>Dining philosophers</b> in the menu and press <b>Run</b>. The threads run on the server, then the page replays what they did at the real speed.</p><p>The <b>Verification</b> panel lists every property that was checked.</p>'],
    ['Try it yourself', '<p>In the <b>Playground</b> you call <code>wait()</code> and <code>signal()</code> by hand and watch the queue.</p>'],
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
  try { App.demos = await api('/api/catalog'); }
  catch (e) { return fatal(e.message); }
  $('#bootSkel').remove();
  $('#stations').innerHTML = NAV.map(n => `<li class="${n.gap ? 'gap' : ''}"><button class="station" data-id="${n.id}">${esc(n.label)}</button></li>`).join('');
  $('#stations').addEventListener('click', e => { const b = e.target.closest('.station'); if (b) show(b.dataset.id); });
  setupTheme();
  buildOverview();
  App.demos.forEach(buildDemoView);
  Playground.build();
  window.addEventListener('popstate', () => show(location.hash.slice(1), true));
  show(location.hash.slice(1) || 'overview', true);
  App.ready = true;
  Intro.setup();
  Intro.maybeStart();
}
boot();
