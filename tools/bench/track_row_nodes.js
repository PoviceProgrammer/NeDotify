// Exact DOM-node accounting for ONE library/search track row.
//
// Method (all reproducible, nothing estimated):
//   1. Read the row template literal out of ui/web_new_v2/js/utils.js
//      (the `item.innerHTML = \`...\`` assignment in createTrackElement).
//   2. Substitute concrete representative values for every ${...} hole,
//      using the same helper outputs the runtime uses:
//        - getCoverUrl()          -> a proxy cover URL
//        - getSourceIcon(source)  -> the `youtube` variant
//        - formatArtistNames()    -> single artist + a 2-artist variant
//        - formatTime()           -> "3:45"
//        - escapeHtml()           -> identity for plain text
//   3. Parse the resulting HTML with a tag scanner and count ELEMENT nodes.
//   4. Apply the lucide expansion: read the real ICONS map out of the shipped
//      ui/web_new_v2/js/lucide.min.js and replace every <i data-lucide="X">
//      with 1 + (#shape elements in ICONS[X]) nodes.
//
// READ-ONLY.  Prints JSON to stdout; also writes
// tools/bench/results/track_row_nodes.json.
'use strict';
const fs = require('fs');
const path = require('path');

const REPO = path.join(__dirname, '..', '..');
const UTILS = path.join(REPO, 'ui', 'web_new_v2', 'js', 'utils.js');
const LUCIDE = path.join(REPO, 'ui', 'web_new_v2', 'js', 'lucide.min.js');

// ---------------------------------------------------------------- 1. template
const utilsSrc = fs.readFileSync(UTILS, 'utf8');
const marker = 'item.innerHTML = `';
const start = utilsSrc.indexOf(marker);
if (start === -1) throw new Error('track-row template not found in utils.js');
const bodyStart = start + marker.length;
const bodyEnd = utilsSrc.indexOf('`;', bodyStart);
const template = utilsSrc.slice(bodyStart, bodyEnd);
const templateLine = utilsSrc.slice(0, start).split('\n').length;

// template start line, for the report
const templateStartLine = templateLine;
const templateEndLine = templateLine + template.split('\n').length - 1;

// ------------------------------------------------------- 2. placeholder values
// Same strings the runtime helpers produce (utils.js:230-277, 577-586).
const SRC_ICON = '<i data-lucide="youtube" style="width:12px;height:12px"></i>';
const ARTIST_SINGLE = '<span class="clickable-artist" data-artist="Daft Punk">Daft Punk</span>';
const ARTIST_TWO =
  '<span class="clickable-artist" data-artist="Daft Punk">Daft Punk</span>, ' +
  '<span class="clickable-artist" data-artist="Pharrell Williams">Pharrell Williams</span>';

const VARIANTS = {
  minimal: { // no cover, no source badge, downloaded -> check icon
    grad: 'linear-gradient(135deg, #f53d3d 0%, #ff803b 100%)',
    coverSrc: '',
    srcBadgeInner: '',
    title: 'Get Lucky',
    artistHtml: ARTIST_SINGLE,
    downloaded: true,
    source: 'youtube',
  },
  typical_library_row: { // local/proxied cover, youtube badge, download icon
    grad: 'linear-gradient(135deg, #f53d3d 0%, #ff803b 100%)',
    coverSrc: 'http://127.0.0.1:58642/api/cover?path=%5C.tracks%5Ca.jpg&k=abc',
    srcBadgeInner: SRC_ICON,
    title: 'Get Lucky',
    artistHtml: ARTIST_SINGLE,
    downloaded: false,
    source: 'youtube',
  },
  multi_artist_row: {
    grad: 'linear-gradient(135deg, #f53d3d 0%, #ff803b 100%)',
    coverSrc: 'http://127.0.0.1:58642/api/cover?path=%5C.tracks%5Ca.jpg&k=abc',
    srcBadgeInner: SRC_ICON,
    title: 'Get Lucky',
    artistHtml: ARTIST_TWO,
    downloaded: false,
    source: 'youtube',
  },
};

const ICON_CHOICE = (v) => (v.downloaded ? 'check' : 'download');

function materialise(v) {
  let h = template;
  // 1. inner holes first
  h = h
    .replace(/\$\{escapeHtml\(coverSrc\)\}/g, v.coverSrc)
    .replace(/\$\{escapeHtml\(track\.source\)\}/g, v.source)
    .replace(/\$\{getSourceIcon\(track\.source\)\}/g, v.srcBadgeInner || '')
    .replace(/\$\{escapeHtml\(track\.title \|\| 'Unknown'\)\}/g, v.title)
    .replace(/\$\{formatArtistNames\(track\.artist \|\| 'Unknown'\)\}/g, v.artistHtml)
    .replace(/\$\{track\.is_downloaded \|\| track\.source === 'local' \? 'check' : 'download'\}/g, ICON_CHOICE(v))
    .replace(
      /\$\{track\.is_downloaded \|\| track\.source === 'local' \? 'Скачан' : 'Скачать'\}/g,
      'Скачать'
    )
    .replace(/\$\{formatTime\(track\.duration\)\}/g, '3:45')
    .replace(/\$\{grad\}/g, v.grad);
  // 2. ternaries whose value is markup
  h = h.replace(/\$\{coverSrc \? `([\s\S]*?)` : ''\}/g, (_m, inner) => (v.coverSrc ? inner : ''));
  h = h.replace(
    /\$\{track\.source && !isHiddenSource\(track\.source\) \? `([\s\S]*?)` : ''\}/g,
    (_m, inner) => (v.srcBadgeInner ? inner : '')
  );
  // 3. class/attr-only ternaries (no nodes added)
  h = h
    .replace(/\$\{track\.is_downloaded \|\| track\.source === 'local' \? 'downloaded' : ''\}/g, '')
    .replace(/\$\{isFav \? 'liked' : ''\}/g, '')
    .replace(/\$\{isFav \? 'fill:currentColor' : ''\}/g, '');
  return h;
}

// The template uses a couple of shapes the naive replace above will not catch;
// report any leftover ${...} so the number can never be silently wrong.
function leftoverHoles(html) {
  return [...html.matchAll(/\$\{[^}]*\}/g)].map((m) => m[0]);
}

// ------------------------------------------------------------ 3. node counting
const VOID = new Set(['area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'param', 'source', 'track', 'wbr']);

function countElements(html) {
  let count = 0;
  const tags = [];
  const icons = [];
  // leading "/" marks a closing tag; attrs group captures the rest of the tag
  const re = /<(\/?)([a-zA-Z][\w:-]*)((?:"[^"]*"|'[^']*'|[^>"'])*)>/g;
  let m;
  while ((m = re.exec(html)) !== null) {
    if (m[1] === '/') continue; // closing tag -> not a node
    const tag = m[2].toLowerCase();
    const attrs = m[3] || '';
    if (VOID.has(tag) === false || true) count += 1; // void elements are still nodes
    tags.push(tag);
    const lc = /data-lucide="([^"]+)"/.exec(attrs);
    if (lc) icons.push(lc[1]);
  }
  return { count, tags, icons };
}

// ------------------------------------------------------- 4. lucide ICONS map
function loadLucideIconShapeCounts() {
  const src = fs.readFileSync(LUCIDE, 'utf8');
  // The shipped bundle ends with `window.lucide = { createIcons, icons: ICONS }`
  // and ICONS is a plain object literal of `name: '<path .../><circle .../>'`.
  const startObj = src.indexOf('const ICONS = {');
  if (startObj === -1) throw new Error('ICONS literal not found in lucide.min.js');
  let i = src.indexOf('{', startObj);
  let depth = 0;
  let end = -1;
  for (let k = i; k < src.length; k++) {
    const ch = src[k];
    if (ch === "'" || ch === '"' || ch === '`') {
      const q = ch;
      k++;
      while (k < src.length && src[k] !== q) {
        if (src[k] === '\\') k++;
        k++;
      }
      continue;
    }
    if (ch === '{') depth++;
    else if (ch === '}') {
      depth--;
      if (depth === 0) { end = k; break; }
    }
  }
  const objSrc = src.slice(i, end + 1);
  const sandbox = {};
  // eslint-disable-next-line no-new-func
  const ICONS = new Function('return (' + objSrc + ');')();
  const shapes = {};
  for (const name of Object.keys(ICONS)) {
    const tags = String(ICONS[name]).match(/<[a-zA-Z][\w-]*/g) || [];
    shapes[name] = { shape_elements: tags.length, dom_nodes: 1 + tags.length };
  }
  return shapes;
}

const ICON_SHAPES = loadLucideIconShapeCounts();

const out = {};
for (const [name, v] of Object.entries(VARIANTS)) {
  const html = materialise(v);
  const holes = leftoverHoles(html);
  const before = countElements(html);
  // the row root (div.track-item) is the element created by createElement,
  // then its innerHTML children are parsed into it -> +1 for the root
  const authored = before.count + 1;
  // lucide pass
  let lucideDelta = 0;
  const iconReport = {};
  for (const icon of before.icons) {
    const s = ICON_SHAPES[icon];
    if (!s) { iconReport[icon] = 'NOT_IN_BUNDLE'; continue; }
    lucideDelta += s.dom_nodes - 1; // the <i> is replaced by the <svg>+shapes
    iconReport[icon] = s.dom_nodes;
  }
  out[name] = {
    leftover_template_holes: holes,
    elements_authored_html: authored,
    tag_histogram: before.tags.reduce((acc, t) => ((acc[t] = (acc[t] || 0) + 1), acc), {}),
    data_lucide_icons_in_row: iconReport,
    lucide_added_nodes: lucideDelta,
    dom_nodes_after_render: authored + lucideDelta,
  };
}

const LIBRARY_TRACKS = 2000;
const per = out.typical_library_row.dom_nodes_after_render;

const payload = {
  schema: 'nedotify.track-row-nodes.v1',
  generated_by: 'tools/bench/track_row_nodes.js',
  method:
    'template literal extracted from ui/web_new_v2/js/utils.js (createTrackElement), ' +
    'substituted with runtime-equivalent helper output, parsed with a tag scanner, ' +
    'then expanded by the real ICONS map read out of ui/web_new_v2/js/lucide.min.js. ' +
    'No rendering engine involved; counts are exact for this template.',
  template_source: {
    file: 'ui/web_new_v2/js/utils.js',
    lines: `${templateStartLine}-${templateEndLine}`,
    function: 'createTrackElement',
  },
  variants: out,
  library_scenarios: Object.fromEntries(
    Object.entries(out).map(([k, v]) => [
      k,
      {
        nodes_per_row: v.dom_nodes_after_render,
        nodes_for_2000_tracks: v.dom_nodes_after_render * LIBRARY_TRACKS,
      },
    ])
  ),
  lucide_icons_used_across_app: Object.keys(ICON_SHAPES).length,
};

fs.mkdirSync(path.join(REPO, 'tools', 'bench', 'results'), { recursive: true });
fs.writeFileSync(
  path.join(REPO, 'tools', 'bench', 'results', 'track_row_nodes.json'),
  JSON.stringify(payload, null, 2) + '\n',
  'utf8'
);
process.stdout.write(JSON.stringify(payload, null, 2) + '\n');