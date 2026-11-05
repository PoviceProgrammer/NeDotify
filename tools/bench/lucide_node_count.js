// Measure how many DOM nodes lucide.createIcons() produces for the icons used
// by the track-row template (ui/web_new_v2/js/utils.js:338-368) and elsewhere.
//
// Method: load the SHIPPED bundle (ui/web_new_v2/js/lucide.min.js) into a small
// DOM shim that is just complete enough for the bundle, run the real
// createIcons() over a stub tree holding every icon we care about, and count the
// resulting nodes.  Nothing is estimated; the counts come from the shipped code.
//
// READ-ONLY.  Prints JSON to stdout.
'use strict';
const fs = require('fs');
const path = require('path');

const ICONS = [
  'play', 'heart', 'plus', 'more-horizontal', 'download', 'check',
  'trash-2', 'loader-2', 'grip-vertical', 'music', 'x', 'list-music',
];

// ---------------- minimal DOM shim ----------------
class El {
  constructor(tag, ns) {
    this.tagName = tag;
    this.namespaceURI = ns || null;
    this.attributes = {};
    this.children = [];
    this.parentNode = null;
    this.classList = mkClassList('');
    this.style = {};
    this._text = '';
  }
  setAttribute(k, v) {
    this.attributes[k] = String(v);
    if (k === 'class') this.classList = mkClassList(String(v));
  }
  getAttribute(k) { return k in this.attributes ? this.attributes[k] : null; }
  removeAttribute(k) { delete this.attributes[k]; }
  hasAttribute(k) { return k in this.attributes; }
  appendChild(c) { c.parentNode = this; this.children.push(c); return c; }
  removeChild(c) { const i = this.children.indexOf(c); if (i >= 0) this.children.splice(i, 1); return c; }
  replaceChild(n, o) { const i = this.children.indexOf(o); if (i >= 0) { this.children.splice(i, 1, n); n.parentNode = this; } return o; }
  insertBefore(n, ref) { const i = this.children.indexOf(ref); if (i >= 0) { this.children.splice(i, 0, n); n.parentNode = this; } else this.appendChild(n); return ref; }
  addEventListener() {}
  get textContent() { return this._text; }
  set textContent(v) { this._text = v; this.children = []; }
  get innerHTML() { return this._html || ''; }
  set innerHTML(v) { this._html = v; this.children = []; parseInto(this, v); }
  querySelectorAll(sel) { return matchAll(this, sel); }
  querySelector(sel) { return matchAll(this, sel)[0] || null; }
  get totalNodes() { return 1 + this.children.reduce((a, c) => a + c.totalNodes, 0); }
}

function mkClassList(v) {
  const s = new Set(String(v || '').split(/\s+/).filter(Boolean));
  return { _s: s, add: (c) => s.add(c), remove: (c) => s.delete(c), contains: (c) => s.has(c), toggle() {} };
}

// Minimal HTML fragment parser: enough for lucide's `svg.innerHTML = '<path .../>...'`
function parseInto(root, html) {
  const stack = [root];
  const re = /<!--[\s\S]*?-->|<!\[CDATA\[[\s\S]*?\]\]>|<\/?([a-zA-Z][\w:-]*)((?:\s+[^>]*?)?)\/?>|<\?[\s\S]*?\?>|<!DOCTYPE[^>]*>|([^<]+)/g;
  let m;
  while ((m = re.exec(html)) !== null) {
    if (m[3] !== undefined) continue; // text
    if (m[1] === undefined) continue; // comment / doctype / cdata
    const tag = m[1];
    const attrs = m[2] || '';
    const selfClose = /\/>\s*$/.test(m[0]) || VOID_TAGS.has(tag.toLowerCase());
    if (attrs.trimStart().startsWith('/')) {
      if (stack.length > 1) stack.pop();
      continue;
    }
    const el = new El(tag.toLowerCase());
    for (const a of attrs.matchAll(/([a-zA-Z_:][-\w:.]*)\s*=\s*("([^"]*)"|'([^']*)'|([^\s"'>]+))/g)) {
      el.setAttribute(a[1], a[3] !== undefined ? a[3] : a[4] !== undefined ? a[4] : a[5]);
    }
    stack[stack.length - 1].appendChild(el);
    if (!selfClose) stack.push(el);
  }
}

const VOID_TAGS = new Set(['area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'param', 'source', 'track', 'wbr']);

function matchAll(root, sel) {
  const out = [];
  const sels = sel.split(',').map((s) => s.trim());
  (function walk(el) {
    for (const c of el.children) {
      if (sels.some((s) => matchesOne(c, s))) out.push(c);
      walk(c);
    }
  })(root);
  return out;
}

function matchesOne(el, sel) {
  const m = sel.match(/^([a-zA-Z][\w-]*)?((?:\.[\w-]+|\[[^\]]+\])*)$/);
  if (!m) return false;
  if (m[1] && el.tagName.toLowerCase() !== m[1].toLowerCase()) return false;
  const toks = m[2] || '';
  const re = /\.([\w-]+)|\[([\w-]+)(?:=["']?([^\]"']*)["']?)?\]/g;
  let t;
  while ((t = re.exec(toks))) {
    if (t[1]) { if (!el.classList.contains(t[1])) return false; }
    else if (t[2]) { if (!(t[2] in el.attributes)) return false; if (t[3] !== undefined && el.attributes[t[2]] !== t[3]) return false; }
  }
  return true;
}

const docEl = new El('html');
docEl.style = { setProperty() {}, removeProperty() {}, getPropertyValue: () => '' };
docEl.clientWidth = 1920;
docEl.clientHeight = 1080;
docEl.offsetWidth = 1920;
docEl.offsetHeight = 1080;
docEl.getBoundingClientRect = () => ({ width: 1920, height: 1080, top: 0, left: 0, right: 1920, bottom: 1080, x: 0, y: 0 });
const documentShim = {
  createElement: (t) => new El(t),
  createElementNS: (ns, t) => new El(t, ns),
  querySelectorAll: (sel) => matchAll(docEl, sel),
  querySelector: (sel) => matchAll(docEl, sel)[0] || null,
  documentElement: docEl,
  body: Object.assign(new El('body'), { getBoundingClientRect: docEl.getBoundingClientRect }),
  head: new El('head'),
  documentURI: 'file:///index.html',
  readyState: 'complete',
};
const win = {
  document: documentShim,
  matchMedia: () => ({ matches: false, addEventListener() {}, addListener() {} }),
  getComputedStyle: () => ({ getPropertyValue: () => '', fontSize: '16px' }),
  devicePixelRatio: 1,
  innerWidth: 1920,
  innerHeight: 1080,
};

// ---------------- load the shipped lucide bundle ----------------
const lucidePath = path.join(__dirname, '..', '..', 'ui', 'web_new_v2', 'js', 'lucide.min.js');
const src = fs.readFileSync(lucidePath, 'utf8');
const mod = { exports: {} };
const run = new Function('module', 'exports', 'window', 'document', 'navigator', 'self', src);
run(mod, mod.exports, win, documentShim, { userAgent: 'node' }, win);
const lucide = (mod.exports && Object.keys(mod.exports).length && mod.exports) || win.lucide;

// ---------------- stub tree with every icon ----------------
const stub = new El('root');
const slots = {};
for (const name of ICONS) {
  const i = new El('i');
  i.setAttribute('data-lucide', name);
  slots[name] = i;
  stub.appendChild(i);
}
docEl.appendChild(stub);

let err = null;
try {
  lucide.createIcons({ icons: lucide.icons || {} });
} catch (e) { err = String((e && e.message) || e); }

const icons = {};
const iconStrings = (lucide && lucide.icons) || {};
for (const name of ICONS) {
  // (a) exact count read straight out of the shipped ICONS map (authoritative)
  const raw = iconStrings[name] || '';
  const tags = raw.match(/<[a-zA-Z][\w-]*/g) || [];
  const el = stub.children.find((c) => c.getAttribute('data-lucide') === name)
    || stub.children[ICONS.indexOf(name)];
  icons[name] = {
    // <svg> + N shape elements = 1 + N nodes per icon in the live DOM
    dom_nodes_per_icon: 1 + tags.length,
    shape_elements: tags,
    rendered_root_tag: el ? el.tagName : null,
    rendered_total_nodes: el ? el.totalNodes : null,
    rendered_child_tags: el ? el.children.map((c) => c.tagName) : null,
  };
}

process.stdout.write(JSON.stringify({
  source: 'ui/web_new_v2/js/lucide.min.js',
  method: 'shipped bundle executed in a DOM shim; createIcons() run; real nodes counted',
  lucide_present: !!lucide,
  createIcons_error: err,
  total_icons_in_bundle: lucide && lucide.icons ? Object.keys(lucide.icons).length : null,
  icons: icons,
}, null, 2) + '\n');