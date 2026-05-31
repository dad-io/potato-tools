/* HUD wallpaper renderer.
   Polls /data and paints each HMI generically from its channel/note schema,
   so adding an HMI on the Python side needs no change here. Channels are
   reconciled by key (smooth bars); the panel rebuilds only when the set of
   channel keys changes - e.g. when a model loads and the footprint row appears. */

const POLL_MS = 2000;
const wall = document.getElementById('wall');
const panels = {};        // hmiId -> { root, kpis, channels, chById, keysig, stream, meta }

const el = (tag, cls, txt) => {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (txt != null) e.textContent = txt;
  return e;
};
const pad2 = n => String(n).padStart(2, '0');
const clock = () => { const d = new Date(); return `${pad2(d.getHours())}:${pad2(d.getMinutes())}:${pad2(d.getSeconds())}`; };

function buildPanel(hmi) {
  const root = el('div', 'hmi');
  root.id = 'hmi-' + hmi.id;

  const head = el('div', 'hmi-head');
  const brand = el('div', 'hmi-brand');
  brand.appendChild(el('div', 'hmi-mark'));
  const title = el('div', 'hmi-title');
  title.appendChild(el('div', 't', hmi.title));
  title.appendChild(el('div', 's', hmi.subtitle || ''));
  brand.appendChild(title);
  head.appendChild(brand);

  const right = el('div', 'hmi-kpis');
  const kpis = el('div', 'hmi-kpis');
  right.appendChild(kpis);
  const live = el('div', 'live');
  live.appendChild(el('span', 'dot'));
  live.appendChild(el('span', 'l', 'LIVE'));
  right.appendChild(live);
  head.appendChild(right);
  root.appendChild(head);

  const channels = el('div', 'channels');
  root.appendChild(channels);

  const stream = el('div', 'stream');
  const sh = el('div', 'stream-head');
  const h = el('div', 'h');
  h.appendChild(el('span', 'd'));
  h.appendChild(el('span', null, 'Diagnostic Stream'));
  sh.appendChild(h);
  const meta = el('div', 'm', '—');
  sh.appendChild(meta);
  stream.appendChild(sh);
  const body = el('div', 'stream-body');
  stream.appendChild(body);
  root.appendChild(stream);

  panels[hmi.id] = { root, kpis, channels, chById: {}, keysig: '', stream: body, meta };
  return root;
}

function buildChannels(p, hmi) {
  p.channels.innerHTML = '';
  p.chById = {};
  hmi.channels.forEach((c, i) => {
    const row = el('div', 'ch');
    row.dataset.sev = c.sev;

    const id = el('div', 'ch-id');
    id.appendChild(el('span', 'n', 'C-' + pad2(i + 1)));
    id.appendChild(el('span', 'd'));
    row.appendChild(id);

    const meta = el('div', 'ch-meta');
    const ml = el('div', 'l', c.label);
    const ms = el('div', 's', c.sub);
    meta.appendChild(ml); meta.appendChild(ms);
    row.appendChild(meta);

    const read = el('div', 'ch-read');
    const rrow = el('div', 'row');
    const v = el('div', 'v');
    v.innerHTML = `${c.value}<span class="u">${c.unit || ''}</span>`;
    const ro = el('div', 'ro', c.readout);
    rrow.appendChild(v); rrow.appendChild(ro);
    const bar = el('div', 'ch-bar');
    const fill = el('i');
    fill.style.width = c.fill + '%';
    bar.appendChild(fill);
    read.appendChild(rrow); read.appendChild(bar);
    row.appendChild(read);

    const st = el('div', 'ch-st', c.status);
    row.appendChild(st);

    p.channels.appendChild(row);
    p.chById[c.key] = { row, v, ro, fill, st, sub: ms, label: ml };
  });
}

function updateChannels(p, hmi) {
  hmi.channels.forEach(c => {
    const o = p.chById[c.key];
    if (!o) return;
    o.row.dataset.sev = c.sev;
    o.v.innerHTML = `${c.value}<span class="u">${c.unit || ''}</span>`;
    o.ro.textContent = c.readout;
    o.label.textContent = c.label;
    o.sub.textContent = c.sub;
    o.st.textContent = c.status;
    o.fill.style.width = c.fill + '%';
  });
}

function renderPanel(hmi) {
  let p = panels[hmi.id];
  if (!p) { wall.appendChild(buildPanel(hmi)); p = panels[hmi.id]; }

  p.root.dataset.stateSev = hmi.state_sev || '';

  // KPI strip
  p.kpis.innerHTML = '';
  Object.entries(hmi.header || {}).forEach(([k, val]) => {
    const kpi = el('div', 'kpi');
    kpi.appendChild(el('div', 'k', k));
    kpi.appendChild(el('div', 'v', val));
    p.kpis.appendChild(kpi);
  });

  // channels: rebuild only if the key set changed
  const sig = hmi.channels.map(c => c.key).join(',');
  if (sig !== p.keysig) { buildChannels(p, hmi); p.keysig = sig; }
  else updateChannels(p, hmi);

  // diagnostic stream
  const ts = clock();
  p.stream.innerHTML = '';
  hmi.notes.forEach(n => {
    const line = el('div', 'line ' + n.sev);
    line.appendChild(el('span', 'ts', ts));
    line.appendChild(el('span', 'sv', n.sev));
    line.appendChild(el('span', 'mg', n.text));
    p.stream.appendChild(line);
  });
  const alerts = hmi.notes.filter(n => n.sev === 'alert').length;
  const warns = hmi.notes.filter(n => n.sev === 'warn').length;
  p.meta.textContent = `${ts} · ${alerts}A ${warns}W`;
}

async function tick() {
  try {
    const r = await fetch('/data', { cache: 'no-store' });
    const data = await r.json();
    const boot = document.getElementById('boot');
    if (boot) boot.remove();
    data.hmis.forEach(renderPanel);
  } catch (e) {
    /* backend not up yet; keep last frame */
  }
}

tick();
setInterval(tick, POLL_MS);
