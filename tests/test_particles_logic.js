import assert from 'node:assert';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const projectRoot = path.resolve(__dirname, '..');

// 1. Verify base.css particles styling
const cssContent = fs.readFileSync(path.join(projectRoot, 'ui/web_new_v2/css/components/base.css'), 'utf-8');
const bgMatch = cssContent.match(/#particles-bg\s*\{([^}]+)\}/);
assert(bgMatch, 'Could not find #particles-bg rule in base.css');
const bgCss = bgMatch[1];
assert(bgCss.includes('position: fixed;'), 'Expected position: fixed');
assert(bgCss.includes('inset: 0;'), 'Expected inset: 0');
assert(bgCss.includes('pointer-events: none !important;'), 'Expected pointer-events: none !important');
assert(bgCss.includes('z-index: 20;'), 'Expected z-index: 20');
assert(bgCss.includes('filter: none;'), 'Expected filter: none');
assert(bgCss.includes('-webkit-filter: none;'), 'Expected -webkit-filter: none');
assert(!bgCss.includes('filter: blur'), 'Expected no filter: blur in #particles-bg');

// 2. Verify particles.js logic
const jsContent = fs.readFileSync(path.join(projectRoot, 'ui/web_new_v2/js/particles.js'), 'utf-8');
assert(!jsContent.includes('desynchronized: true'), 'particles.js should not have desynchronized: true');
assert(jsContent.includes("canvas.getContext('2d', { alpha: true })"), 'particles.js should use { alpha: true }');
assert(jsContent.includes('"Noto Color Emoji"'), 'particles.js should include Noto Color Emoji font fallback');
assert(jsContent.includes("if (resolvedShape === 'circle') resolvedShape = 'dot';"), 'particles.js should alias circle to dot');
assert(jsContent.includes("if (p.shape === 'dot' || p.shape === 'circle')"), 'drawParticle should support circle alias');
assert(jsContent.includes('function onResize()'), 'onResize should be defined at module scope');
assert(jsContent.includes('function onMiniPlayerToggled()'), 'onMiniPlayerToggled should be defined at module scope');
assert(jsContent.includes('function onMouseMove('), 'onMouseMove should be defined at module scope');
assert(jsContent.includes('function onMouseLeave()'), 'onMouseLeave should be defined at module scope');

// 3. Verify main.js startup sync
const mainContent = fs.readFileSync(path.join(projectRoot, 'ui/web_new_v2/js/main.js'), 'utf-8');
assert(mainContent.includes("const togglePart = document.getElementById('toggle-particles');"), 'main.js should look up toggle-particles');
assert(mainContent.includes("if (togglePart) togglePart.classList.toggle('on', particlesEnabled);"), 'main.js should toggle class on startup');

console.log('All JS and CSS particles checks PASSED successfully!');
