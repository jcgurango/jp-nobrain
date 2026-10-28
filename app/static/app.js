/* jp-nobrain frontend: hash-routed single page app, no build step. */
const $ = (sel, el = document) => el.querySelector(sel);
const app = $('#app');
const player = $('#player');
const TIER_COLORS = { listening: 'var(--listening)', reading: 'var(--reading)', produce: 'var(--produce)', mutate: 'var(--mutate)' };
const TIERS = ['listening', 'reading', 'produce', 'mutate'];

const api = {
  get: (p) => fetch(p).then(r => r.json()),
  post: (p, body) => fetch(p, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body || {}) }).then(r => r.json()),
};
function esc(s) { return String(s ?? '').replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c])); }
function toast(msg, ms = 2200) { const t = $('#toast'); t.textContent = msg; t.classList.add('show'); clearTimeout(t._h); t._h = setTimeout(() => t.classList.remove('show'), ms); }
function ruby(tokens, target) {
  // tokens: [[text, reading|null], ...]. Wrap target substring in <mark> when it falls inside plain text.
  return tokens.map(([t, r]) => {
    let txt = esc(t);
    if (target && t.includes(target)) txt = txt.replace(esc(target), `<mark>${esc(target)}</mark>`);
    return r ? `<ruby>${txt}<rt>${esc(r)}</rt></ruby>` : txt;
  }).join('');
}
function kanjiMarked(text, target) { const e = esc(text); return target && text.includes(target) ? e.replace(esc(target), `<mark>${esc(target)}</mark>`) : e; }
function play(src) { if (!src) return Promise.resolve(); player.src = '/' + src; player.currentTime = 0; return player.play().catch(() => {}); }
function days(d) { if (!d) return '–'; const diff = (new Date(d) - Date.now()) / 864e5; if (diff < 0) return 'due'; if (diff < 1) return 'today'; return Math.round(diff) + 'd'; }

// ------------------------------------------------------------------ home
async function home() {
  const o = await api.get('/api/overview');
  const pct = Math.min(100, Math.round(100 * o.today.reviews / o.today.cap));
  app.innerHTML = `
    <h1>Today</h1>
    <div class="panel">
      <div class="row space"><div><b>${o.today.reviews}</b> <span class="muted">/ ${o.today.cap} reviews</span></div>
        <div class="muted">${o.new.allowed} new cards available · ${o.new.introduced_today} introduced today · load ${Math.round(o.new.load * 100)}%</div></div>
      <div class="bar"><div style="width:${pct}%"></div></div>
      <div class="row" style="margin-top:12px">
        <a class="btn primary big" href="#/review/all">Study everything due</a>
        <a class="btn big" href="#/shadow">Shadow mode</a>
      </div>
    </div>
    <h2>Buckets</h2>
    <div class="grid">
      ${TIERS.map(t => { const c = o.tiers[t]; return `
        <a class="panel tier" href="#/review/${t}" style="--c:${TIER_COLORS[t]}">
          <div class="name">${t}</div>
          <div class="big">${c.due}</div>
          <div class="sub">due now · ${c.later_today} later today<br>${c.active} cards in tier${c.new ? ` · ${c.new} waiting` : ''}</div>
        </a>`; }).join('')}
    </div>
    <h2>Deck</h2>
    <div class="panel">
      <dl class="kv">
        <dt>Introduced</dt><dd>${o.deck.introduced} / ${o.deck.total}</dd>
        <dt>Known in at least one tier (shadow pool)</dt><dd>${o.deck.known}</dd>
        <dt>Previously known (short-circuited)</dt><dd>${o.deck.previously_known}</dd>
        <dt>Graduated</dt><dd>${o.deck.graduated}</dd>
      </dl>
      <h2>Up next in the deck</h2>
      ${o.new.next.map(n => `<div class="row space" style="padding:4px 0"><span class="jp small" style="font-size:20px;margin:0">${esc(n.kanji)}</span><span class="muted">${esc(n.gloss)} <span class="badge" style="--c:${n.type === 'grammar' ? 'var(--mutate)' : 'var(--muted)'}">${n.type === 'grammar' ? 'grammar' : n.deck}</span></span></div>`).join('')}
    </div>`;
}

// ------------------------------------------------------------------ review
const GRADE_BUTTONS = {
  listening: [['missed', 'Missed', 'bad'], ['replay', 'After a replay', 'mid'], ['instant', 'Instant', 'good']],
  reading: [['missed', 'Missed', 'bad'], ['slow', 'Got it, slowly', 'mid'], ['good', 'Read & understood', 'good'], ['instant', 'Instant', 'star']],
  produce: [['missed', 'Missed', 'bad'], ['partial', 'Partly', 'mid'], ['good', 'Got it', 'good']],
  mutate: [['missed', 'Missed', 'bad'], ['shaky', 'Shaky', 'mid'], ['good', 'Got it', 'good']],
};
let R = null; // current review state

async function review(tier) {
  R = { tier, revealed: false, replays: 0, item: null, ignoreCap: R && R.tier === tier ? R.ignoreCap : false, exclude: null, lastEvents: '' };
  await nextCard();
}
async function nextCard() {
  const q = `/api/next?tier=${R.tier}${R.ignoreCap ? '&ignore_cap=1' : ''}${R.exclude ? '&exclude=' + encodeURIComponent(R.exclude) : ''}`;
  const res = await api.get(q);
  R.exclude = null; R.revealed = false; R.replays = 0; R.item = res.item; R.reason = res.reason; R.done = res.done; R.cap = res.cap;
  renderReview();
}
function renderReview() {
  const it = R.item;
  const headline = `<div class="row space" style="margin-bottom:8px"><h1 style="margin:0">${R.tier === 'all' ? 'Study' : R.tier[0].toUpperCase() + R.tier.slice(1)}</h1>
     <span class="muted">${R.done} / ${R.cap} today ${R.lastEvents ? '· ' + esc(R.lastEvents) : ''}</span></div>`;
  if (!it) {
    const capMsg = R.reason === 'cap'
      ? `<p>You hit today's cap of ${R.cap} reviews. Good session.</p><button class="btn" id="more">Keep going anyway</button>`
      : `<p>Nothing due${R.tier !== 'all' ? ' in this bucket' : ''} right now.</p>${R.tier === 'all' || R.tier === 'listening' ? '<button class="btn" id="more">Pull in a new card anyway</button>' : ''}`;
    app.innerHTML = `${headline}<div class="panel center">${capMsg} <a class="btn" href="#/">Home</a></div>`;
    const m = $('#more'); if (m) m.onclick = () => { R.ignoreCap = true; nextCard(); };
    return;
  }
  const c = it.card, tier = it.tier, color = TIER_COLORS[tier];
  const ex = c.extra || {};
  const srcLine = c.deck === 'jlab' ? `JLAB · ${esc(ex.source || '')}` : `Kaishi · ${esc(ex.word || '')} ${esc(ex.word_meaning || '')}`;
  const tags = [`<span class="badge" style="--c:${color}">${tier}</span>`,
    it.is_new ? `<span class="badge" style="--c:var(--accent)">new card</span>` : '',
    c.type === 'grammar' ? `<span class="badge" style="--c:var(--mutate)">grammar point</span>` : '',
    it.meta && it.meta.previously_known ? `<span class="badge">previously known</span>` : '',
    it.meta && it.meta.graduated ? `<span class="badge">graduated</span>` : ''].join(' ');
  let front = '', back = '';
  if (tier === 'listening') {
    front = `<div class="center"><button class="audio-btn" id="replay" title="Replay (R)">▶</button><div class="hint" style="margin-top:10px">Listen and understand. <span class="kbd">R</span> replay · <span class="kbd">space</span> reveal</div>
             ${it.first_review ? '<div class="hint">First time hearing this: an <b>Instant</b> without replay marks it as previously known.</div>' : ''}</div>`;
    back = `<div class="jp" style="--c:${color}">${ruby(c.tokens, c.target)}</div><div class="gloss">${esc(c.gloss)}</div>${explanation(c, it)}${screenshot(c)}`;
  } else if (tier === 'reading') {
    front = `<div class="jp" style="--c:${color}">${kanjiMarked(c.kanji, c.target)}</div><div class="hint">Read it. <span class="kbd">space</span> to reveal furigana and meaning.</div>`;
    back = `<div class="jp" style="--c:${color}">${ruby(c.tokens, c.target)}</div><div class="gloss">${esc(c.gloss)}</div>${explanation(c, it)}`;
  } else if (tier === 'produce') {
    front = `<div class="gloss" style="font-size:26px">${esc(c.gloss)}</div>
             ${c.target || ex.word ? `<details><summary>Hint: target word</summary><div class="jp small">${esc(ex.word || c.target)}</div></details>` : ''}
             <div class="hint">Say it in Japanese, then <span class="kbd">space</span> to check.</div>`;
    back = `<div class="jp" style="--c:${color}">${ruby(c.tokens, c.target)}</div><div class="row"><button class="btn" id="replay">▶ play</button></div>${explanation(c, it, true)}`;
  } else if (tier === 'mutate') {
    const m = it.mutation;
    front = `<div class="jp" style="--c:${color}">${esc(c.kanji)}</div>
             <div class="prompt">${esc(m.instruction)}</div><div class="hint">${esc(m.hint)}</div>
             <div class="hint" style="margin-top:8px">Say your version out loud, then <span class="kbd">space</span>.</div>`;
    back = `<div class="jp small" style="--c:${color}">${ruby(c.tokens, c.target)}</div><div class="gloss">${esc(c.gloss)}</div>
            <div class="row"><button class="btn" id="replay">▶ play original</button></div>${explanation(c, it, true)}`;
  }
  let buttons = GRADE_BUTTONS[tier];
  if (tier === 'reading' && !it.first_review) buttons = buttons.filter(b => b[0] !== 'instant');
  app.innerHTML = `${headline}
    <div class="panel card">
      <div class="meta"><div>${tags}</div><div>${srcLine} · #${c.position + 1}</div></div>
      <div id="front">${front}</div>
      <div id="back" style="display:none">${back}</div>
      <div id="controls" style="margin-top:18px">
        ${R.revealed ? gradeButtons(buttons, it) : `<div class="row space"><button class="btn primary big" id="reveal">Reveal <span class="kbd" style="color:inherit;border-color:currentColor">space</span></button>
          <span><button class="btn" id="undo" title="Undo last review (U)">↶ Undo</button> <button class="btn" id="skip" title="Skip for now (S)">Skip</button></span></div>`}
      </div>
    </div>`;
  $('#reveal') && ($('#reveal').onclick = reveal);
  $('#undo') && ($('#undo').onclick = undo);
  $('#skip') && ($('#skip').onclick = () => { R.exclude = c.id; nextCard(); });
  const rp = $('#replay'); if (rp) rp.onclick = () => { if (!R.revealed) R.replays++; play(c.audio); updateInstant(); };
  document.querySelectorAll('.grade').forEach(b => b.onclick = () => grade(b.dataset.g));
  if (tier === 'listening' && !R.revealed) play(c.audio);
  if (R.revealed && (tier === 'produce' || tier === 'mutate' || tier === 'listening')) { /* keep */ }
}
function gradeButtons(buttons, it) {
  const keys = ['1', '2', '3', '4'];
  return `<div class="grades">${buttons.map((b, i) => `<button class="grade ${b[2]}" data-g="${b[0]}" ${b[0] === 'instant' && it.tier === 'listening' && R.replays > 0 ? 'disabled title="You replayed before revealing"' : ''}>
      ${b[1]}${b[0] === 'instant' && it.first_review ? ' ✦' : ''}<span class="k">${keys[i]}</span></button>`).join('')}</div>
    <div class="row space" style="margin-top:10px"><span class="events">${it.first_review && (it.tier === 'listening' || it.tier === 'reading') ? '✦ first review: Instant short-circuits upward' : ''}</span>
    <span><button class="btn" id="undo">↶ Undo</button></span></div>`;
}
function updateInstant() { const b = document.querySelector('.grade[data-g=instant]'); if (b && R.item.tier === 'listening') b.disabled = R.replays > 0; }
function explanation(c, it, dim = false) {
  const ex = c.extra || {};
  let html = '';
  const text = c.explanation || '';
  if (c.type === 'grammar') {
    html += `<div class="explain">${esc(text)}</div>`;
    const intro = ex.section_intro;
    if (intro && intro.length) html += `<details><summary>Section intro: ${esc(intro[intro.length - 1].title)}</summary><div class="explain dim">${esc(intro.map(i => i.text).join('\n\n'))}</div></details>`;
    if (ex.explanation_full && ex.explanation_full !== text) html += `<details><summary>Full card notes</summary><div class="explain dim">${esc(ex.explanation_full)}</div></details>`;
  } else if (c.deck === 'kaishi') {
    html += `<div class="explain"><b>${esc(ex.word)}</b>（${esc(ex.word_reading)}） ${esc(ex.word_meaning)}${ex.explanation && ex.explanation !== ex.word_meaning ? '\n' + esc(ex.explanation.replace(ex.word_meaning + '\n', '')) : ''}</div>`;
  } else {
    html += text.length > 220 || dim ? `<details><summary>Notes</summary><div class="explain dim">${esc(text)}</div></details>` : `<div class="explain dim">${esc(text)}</div>`;
  }
  if (ex.explanation_front) html += `<div class="explain dim">${esc(ex.explanation_front)}</div>`;
  return html;
}
function screenshot(c) { return c.image && c.deck === 'jlab' ? `<img class="screenshot" src="/${c.image}" alt="">` : ''; }
function reveal() {
  if (!R.item || R.revealed) return;
  R.revealed = true;
  $('#front').style.display = 'none'; $('#back').style.display = '';
  let buttons = GRADE_BUTTONS[R.item.tier];
  if (R.item.tier === 'reading' && !R.item.first_review) buttons = buttons.filter(b => b[0] !== 'instant');
  $('#controls').innerHTML = gradeButtons(buttons, R.item);
  document.querySelectorAll('.grade').forEach(b => b.onclick = () => grade(b.dataset.g));
  $('#undo').onclick = undo;
  const rp = $('#replay'); if (rp) rp.onclick = () => play(R.item.card.audio);
  if (R.item.tier !== 'reading') play(R.item.card.audio);
}
async function grade(g) {
  if (!R.item || !R.revealed) return;
  const res = await api.post('/api/review', { card_id: R.item.card.id, tier: R.item.tier, grade: g });
  if (res.error) { toast(res.error); return; }
  const ev = res.events.filter(e => !e.startsWith('implied')).map(e => ({
    short_circuit: 'marked previously known ✦', reading_reopened: 'reading re-opened',
    graduated: 'graduated 🎓', 'unlocked:reading': 'reading unlocked', 'unlocked:produce': 'produce unlocked', 'unlocked:mutate': 'mutate unlocked' }[e] || e));
  const implied = res.events.filter(e => e.startsWith('implied')).map(e => e.split(':')[1]);
  const sched = res.scheduled_days < 1 ? `${Math.round(res.scheduled_days * 1440)} min` : `${Math.round(res.scheduled_days)} d`;
  R.lastEvents = [sched, ...ev, implied.length ? `credited ${implied.join(', ')}` : ''].filter(Boolean).join(' · ');
  if (ev.length) toast(ev.join(' · '));
  await nextCard();
}
async function undo() {
  const r = await api.post('/api/undo');
  toast(r.undone ? 'Undid last review' : 'Nothing to undo');
  R.lastEvents = ''; await nextCard();
}
document.addEventListener('keydown', (e) => {
  if (!location.hash.startsWith('#/review') || !R) return;
  if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;
  if (e.code === 'Space') { e.preventDefault(); if (!R.revealed) reveal(); else if (R.item) play(R.item.card.audio); return; }
  if (e.key === 'r' || e.key === 'R') { if (R.item) { if (!R.revealed) R.replays++; play(R.item.card.audio); updateInstant(); } return; }
  if (e.key === 'u' || e.key === 'U') { undo(); return; }
  if (e.key === 's' || e.key === 'S') { if (R.item) { R.exclude = R.item.card.id; nextCard(); } return; }
  if (R.revealed && /^[1-4]$/.test(e.key)) { const b = document.querySelectorAll('.grade')[+e.key - 1]; if (b && !b.disabled) b.click(); }
});

// ------------------------------------------------------------------ shadow mode
let SH = null;
async function shadow() {
  const cards = await api.get('/api/shadow');
  SH = { cards, i: 0, playing: false, repeats: +(localStorage.getItem('sh_rep') || 2), gap: +(localStorage.getItem('sh_gap') || 2), show: localStorage.getItem('sh_show') !== '0', count: 0 };
  app.innerHTML = `<h1>Shadow mode</h1>
    <div class="panel">
      <p class="muted">${cards.length} sentences you know in at least one tier, shuffled. Not graded. Listen and repeat along.</p>
      ${cards.length ? `
      <div class="row">
        <button class="btn primary big" id="sh-toggle">▶ Start</button>
        <button class="btn" id="sh-prev">⟵</button><button class="btn" id="sh-next">⟶</button>
        <label>Repeats <select id="sh-rep">${[1, 2, 3, 4].map(n => `<option ${n === SH.repeats ? 'selected' : ''}>${n}</option>`).join('')}</select></label>
        <label>Gap <select id="sh-gap">${[1, 2, 3, 4, 6].map(n => `<option ${n === SH.gap ? 'selected' : ''}>${n}</option>`).join('')}</select> s</label>
        <label><input type="checkbox" id="sh-show" ${SH.show ? 'checked' : ''}> show text</label>
      </div>
      <div class="shadow-text" id="sh-text" style="margin-top:16px"></div>
      <div class="muted" id="sh-pos"></div>` : '<p>Nothing known yet. Do a few listening reviews first.</p>'}
    </div>`;
  if (!cards.length) return;
  $('#sh-toggle').onclick = () => SH.playing ? shStop() : shStart();
  $('#sh-prev').onclick = () => { SH.i = (SH.i - 1 + cards.length) % cards.length; SH.count = 0; shShow(); if (SH.playing) shPlay(); };
  $('#sh-next').onclick = () => { SH.i = (SH.i + 1) % cards.length; SH.count = 0; shShow(); if (SH.playing) shPlay(); };
  $('#sh-rep').onchange = e => { SH.repeats = +e.target.value; localStorage.setItem('sh_rep', SH.repeats); };
  $('#sh-gap').onchange = e => { SH.gap = +e.target.value; localStorage.setItem('sh_gap', SH.gap); };
  $('#sh-show').onchange = e => { SH.show = e.target.checked; localStorage.setItem('sh_show', SH.show ? '1' : '0'); shShow(); };
  player.onended = () => { if (!SH || !SH.playing || !location.hash.startsWith('#/shadow')) return; SH.count++;
    SH._t = setTimeout(() => { if (!SH.playing) return; if (SH.count >= SH.repeats) { SH.i = (SH.i + 1) % SH.cards.length; SH.count = 0; shShow(); } shPlay(); }, SH.gap * 1000); };
  shShow();
}
function shShow() { const c = SH.cards[SH.i]; $('#sh-text').innerHTML = SH.show ? `<div class="jp">${ruby(c.tokens)}</div><div class="gloss muted">${esc(c.gloss)}</div>` : '<div class="jp muted">…</div>'; $('#sh-pos').textContent = `${SH.i + 1} / ${SH.cards.length}`; }
function shPlay() { play(SH.cards[SH.i].audio); }
function shStart() { SH.playing = true; $('#sh-toggle').textContent = '❚❚ Pause'; shPlay(); }
function shStop() { SH.playing = false; clearTimeout(SH._t); player.pause(); $('#sh-toggle').textContent = '▶ Start'; }

// ------------------------------------------------------------------ browse
async function browse(offset = 0, filter = 'all') {
  const limit = 60;
  const d = await api.get(`/api/browse?offset=${offset}&limit=${limit}&filter=${filter}`);
  app.innerHTML = `<div class="row space"><h1 style="margin:0">Deck</h1>
      <span>${['all', 'new', 'introduced', 'graduated'].map(f => `<a class="btn ${f === filter ? 'primary' : ''}" href="#/browse/0/${f}">${f}</a>`).join(' ')}</span></div>
    <p class="muted">${d.total} cards · showing ${offset + 1}–${Math.min(offset + limit, d.total)}</p>
    <div class="panel" style="padding:6px 12px"><table><thead><tr><th>#</th><th>Sentence</th><th>Gloss</th><th>Tiers</th></tr></thead><tbody>
    ${d.rows.map(r => `<tr><td class="muted">${r.position + 1}</td>
      <td><a href="#/card/${encodeURIComponent(r.id)}" style="text-decoration:none">${esc(r.kanji)}</a> ${r.type === 'grammar' ? '<span class="badge" style="--c:var(--mutate)">G</span>' : ''}${r.deck === 'kaishi' ? '<span class="badge" style="--c:var(--listening)">K</span>' : ''}${r.previously_known ? '<span class="badge">✦</span>' : ''}</td>
      <td class="muted">${esc(r.gloss)}</td>
      <td>${TIERS.map(t => { const s = r.tiers[t]; const cls = !s ? '' : s.state === 'inactive' ? 'inactive' : (s.passes ? 'on' : ''); return `<span class="dot ${cls}" style="--c:${TIER_COLORS[t]}" title="${t}: ${s ? s.state + ' · ' + days(s.due) : 'locked'}"></span>`; }).join('')}${r.graduated ? ' 🎓' : ''}</td></tr>`).join('')}
    </tbody></table></div>
    <div class="row space" style="margin-top:12px">
      <a class="btn" href="#/browse/${Math.max(0, offset - limit)}/${filter}" ${offset === 0 ? 'style="visibility:hidden"' : ''}>← Prev</a>
      <a class="btn" href="#/browse/${offset + limit}/${filter}" ${offset + limit >= d.total ? 'style="visibility:hidden"' : ''}>Next →</a></div>`;
}
async function cardPage(id) {
  const c = await api.get('/api/card/' + encodeURIComponent(id));
  app.innerHTML = `<a href="#/browse" class="muted">← Deck</a>
    <div class="panel card" style="margin-top:10px">
      <div class="meta"><div>${c.type === 'grammar' ? '<span class="badge" style="--c:var(--mutate)">grammar point</span>' : ''} <span class="badge">${c.deck}</span></div><div>#${c.position + 1}</div></div>
      <div class="jp">${ruby(c.tokens, c.target)}</div><div class="gloss">${esc(c.gloss)}</div>
      <div class="row"><button class="btn" id="replay">▶ play</button></div>
      ${explanation(c, {})}${screenshot(c)}
      <h2>Progress</h2>
      <table><thead><tr><th>Tier</th><th>State</th><th>Stability</th><th>Due</th><th>Reps / passes / lapses</th></tr></thead><tbody>
      ${TIERS.map(t => { const s = c.tiers[t]; return `<tr><td><span class="badge" style="--c:${TIER_COLORS[t]}">${t}</span></td>${s ? `<td>${s.state}</td><td>${s.stability.toFixed(1)} d</td><td>${days(s.due)}</td><td>${s.reps} / ${s.passes} / ${s.lapses}</td>` : '<td class="muted" colspan="4">locked</td>'}</tr>`; }).join('')}
      </tbody></table>
      ${c.meta ? `<p class="muted">Introduced ${c.meta.introduced_at.slice(0, 10)}${c.meta.previously_known ? ' · previously known' : ''}${c.meta.graduated ? ' · graduated' : ''}</p>` : '<p class="muted">Not introduced yet.</p>'}
    </div>`;
  $('#replay').onclick = () => play(c.audio);
}

// ------------------------------------------------------------------ stats
async function stats() {
  const s = await api.get('/api/stats');
  const days = s.days.slice().reverse().slice(-30);
  const max = Math.max(1, ...days.map(d => d.reviews));
  app.innerHTML = `<h1>Stats</h1>
    <div class="panel"><h2 style="margin-top:0">Reviews per day (last 30 active days)</h2>
      <div class="spark">${days.map(d => `<div style="height:${Math.round(100 * d.reviews / max)}%" title="${d.day}: ${d.reviews} reviews, ${d.fails} missed"></div>`).join('')}</div>
      <table style="margin-top:14px"><thead><tr><th>Day</th><th>Reviews</th><th>Missed</th><th>Cards</th></tr></thead><tbody>
      ${s.days.slice(0, 10).map(d => `<tr><td>${d.day}</td><td>${d.reviews}</td><td>${d.fails}</td><td>${d.cards}</td></tr>`).join('')}</tbody></table></div>
    <h2>Per tier</h2>
    <div class="panel"><table><thead><tr><th>Tier</th><th>Reviews</th><th>Missed</th><th>New</th><th>Learning</th><th>Review</th><th>Inactive</th></tr></thead><tbody>
      ${TIERS.map(t => { const st = s.states[t] || {}; return `<tr><td><span class="badge" style="--c:${TIER_COLORS[t]}">${t}</span></td><td>${s.per_tier[t].reviews || 0}</td><td>${s.per_tier[t].fails || 0}</td><td>${st.new || 0}</td><td>${(st.learning || 0) + (st.relearning || 0)}</td><td>${st.review || 0}</td><td>${st.inactive || 0}</td></tr>`; }).join('')}
    </tbody></table></div>
    <h2>Upcoming</h2>
    <div class="panel"><table><thead><tr><th>Day</th><th>Reviews due</th></tr></thead><tbody>${s.upcoming.map(u => `<tr><td>${u.day}</td><td>${u.n}</td></tr>`).join('') || '<tr><td colspan=2 class="muted">nothing scheduled</td></tr>'}</tbody></table></div>`;
}

// ------------------------------------------------------------------ settings
const SETTING_HELP = {
  daily_review_cap: ['Daily review cap', 'Total graded reviews per day across all tiers. ~180 is about an hour.'],
  new_cards_per_day: ['New cards per day', 'Maximum deck intake. Throttled automatically as the review load approaches the cap.'],
  desired_retention: ['Desired retention', 'FSRS target recall probability at review time (0.8–0.95).'],
  implied_credit: ['Implied credit', 'Fraction of a Good review granted to lower tiers when a higher tier passes.'],
  graduate_min_interval: ['Graduation interval (days)', 'Mutate interval needed before a card graduates.'],
  graduate_min_passes: ['Graduation passes', 'Mutate passes needed before a card graduates.'],
  graduated_listening_mult: ['Graduated listening multiplier', 'Interval multiplier for listening reviews of graduated cards.'],
  graduated_listening_min_days: ['Graduated listening minimum (days)', 'Shortest listening interval for graduated cards.'],
  short_circuit_fail_limit: ['Short-circuit fail limit', 'Produce failures that re-open Reading for a previously-known card.'],
};
async function settings() {
  const s = await api.get('/api/settings');
  app.innerHTML = `<h1>Settings</h1><div class="panel">
    ${Object.keys(SETTING_HELP).map(k => `<label class="set"><span>${SETTING_HELP[k][0]}<small>${SETTING_HELP[k][1]}</small></span>
      <input type="number" step="${Number.isInteger(s[k]) ? 1 : 0.05}" name="${k}" value="${s[k]}"></label>`).join('')}
    <div class="row" style="margin-top:14px"><button class="btn primary" id="save">Save</button></div></div>
    <p class="muted" style="margin-top:14px">Progress lives in <code>progress.sqlite</code> next to the app. Back it up by copying the file.</p>`;
  $('#save').onclick = async () => {
    const body = {}; document.querySelectorAll('input[name]').forEach(i => body[i.name] = Number.isInteger(s[i.name]) ? parseInt(i.value) : parseFloat(i.value));
    await api.post('/api/settings', body); toast('Saved');
  };
}

// ------------------------------------------------------------------ router
async function route() {
  const h = location.hash || '#/';
  const parts = h.slice(2).split('/');
  if (SH) { shStop(); SH = null; }
  if (!h.startsWith('#/review')) { R = null; player.pause(); }
  document.querySelectorAll('nav a').forEach(a => a.style.color = h.startsWith(a.getAttribute('href')) ? 'var(--ink)' : '');
  try {
    if (parts[0] === '') return home();
    if (parts[0] === 'review') return review(parts[1] || 'all');
    if (parts[0] === 'shadow') return shadow();
    if (parts[0] === 'browse') return browse(+(parts[1] || 0), parts[2] || 'all');
    if (parts[0] === 'card') return cardPage(decodeURIComponent(parts[1]));
    if (parts[0] === 'stats') return stats();
    if (parts[0] === 'settings') return settings();
    home();
  } catch (e) { app.innerHTML = `<div class="panel">Error: ${esc(e.message)}</div>`; }
}
window.addEventListener('hashchange', route);
route();
