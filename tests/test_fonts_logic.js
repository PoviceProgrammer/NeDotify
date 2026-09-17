// Test Milestone 2 Font Logic (applyFontFamily, highlightActiveFontCard, renderFontCards, FONTS_LIST)
import assert from 'node:assert';

// Create a minimal mock DOM environment for testing
class MockClassList {
    constructor() {
        this.set = new Set();
    }
    add(c) { this.set.add(c); }
    remove(c) { this.set.delete(c); }
    toggle(c, force) {
        if (force === undefined) {
            if (this.set.has(c)) { this.set.delete(c); return false; }
            else { this.set.add(c); return true; }
        }
        if (force) { this.set.add(c); return true; }
        else { this.set.delete(c); return false; }
    }
    contains(c) { return this.set.has(c); }
    has(c) { return this.set.has(c); }
}

class MockElement {
    constructor(tagName, id = '') {
        this.tagName = tagName;
        this.id = id;
        this.classList = new MockClassList();
        this.dataset = {};
        this.children = [];
        this.style = {
            properties: {},
            setProperty(k, v) { this.properties[k] = v; },
            getPropertyValue(k) { return this.properties[k] || ''; }
        };
        this.listeners = {};
        this._innerHTML = '';
    }

    get innerHTML() {
        return this._innerHTML || '';
    }
    set innerHTML(val) {
        this._innerHTML = val;
        if (val === '') {
            this.children = [];
        }
    }

    get className() {
        return Array.from(this.classList.set).join(' ');
    }
    set className(val) {
        this.classList.set.clear();
        if (val) {
            val.split(/\s+/).filter(Boolean).forEach(c => this.classList.add(c));
        }
    }

    appendChild(child) {
        this.children.push(child);
        return child;
    }

    querySelectorAll(selector) {
        const res = [];
        const check = (el) => {
            if (selector === '.font-card' && el.classList.has('font-card')) {
                res.push(el);
            }
            if (selector === '.theme-card' && el.classList.has('theme-card')) {
                res.push(el);
            }
            for (const c of el.children) {
                check(c);
            }
        };
        check(this);
        return res;
    }

    addEventListener(event, fn) {
        if (!this.listeners[event]) this.listeners[event] = [];
        this.listeners[event].push(fn);
    }

    click() {
        if (this.listeners['click']) {
            this.listeners['click'].forEach(fn => fn({ target: this }));
        }
    }
}

const docElement = new MockElement('html');
const fontCardsGrid = new MockElement('div', 'font-cards-grid');

const elementsById = {
    'font-cards-grid': fontCardsGrid
};

global.document = {
    documentElement: docElement,
    getElementById(id) {
        return elementsById[id] || null;
    },
    createElement(tag) {
        return new MockElement(tag);
    },
    querySelectorAll() {
        return [];
    },
    addEventListener() {}
};

global.getComputedStyle = function(el) {
    return {
        getPropertyValue(prop) {
            return el.style.getPropertyValue(prop);
        }
    };
};

global.localStorage = {
    data: {},
    getItem(k) { return this.data[k] || null; },
    setItem(k, v) { this.data[k] = v; }
};

global.Audio = class {
    constructor() {}
    addEventListener() {}
    removeEventListener() {}
    load() {}
    play() { return Promise.resolve(); }
    pause() {}
};

try {
    Object.defineProperty(globalThis, 'navigator', {
        value: {
            userAgent: 'Mozilla/5.0 (X11; Linux x86_64)',
            mediaDevices: { enumerateDevices: () => Promise.resolve([]) }
        },
        configurable: true
    });
} catch(e) {}

global.window = {
    settings: {},
    addEventListener() {},
    dispatchEvent() {}
};
global.window.window = global.window;

// Import settings module
const settingsModule = await import('../ui/web_new_v2/js/settings.js');
const { FONTS_LIST, applyFontFamily, highlightActiveFontCard, renderFontCards } = settingsModule;

console.log('Testing FONTS_LIST contents...');
assert(Array.isArray(FONTS_LIST), 'FONTS_LIST should be an array');
assert(FONTS_LIST.length >= 20, 'FONTS_LIST should have multiple font options');

const defaultFont = FONTS_LIST.find(f => f.id === 'default');
assert(defaultFont, 'Default font entry must exist');
assert(defaultFont.family.includes('Inter'), 'Default font must include Inter');

const ubuntuFont = FONTS_LIST.find(f => f.id === 'ubuntu');
assert(ubuntuFont, 'Ubuntu font entry must exist');
assert(ubuntuFont.family.includes('Ubuntu'), 'Ubuntu family must include Ubuntu');

const cantarellFont = FONTS_LIST.find(f => f.id === 'cantarell');
assert(cantarellFont, 'Cantarell font entry must exist');

const liberationFont = FONTS_LIST.find(f => f.id === 'liberation');
assert(liberationFont, 'Liberation font entry must exist');

console.log('Testing applyFontFamily token propagation...');
// 1. Apply default
applyFontFamily('default', 'default', false);
assert.strictEqual(docElement.style.getPropertyValue('--font-family'), defaultFont.family);
assert.strictEqual(docElement.style.getPropertyValue('--font-body'), defaultFont.family);
assert.strictEqual(docElement.style.getPropertyValue('--font-display'), defaultFont.family);

// 2. Apply Ubuntu font
applyFontFamily(ubuntuFont.family, 'ubuntu', false);
assert.strictEqual(docElement.style.getPropertyValue('--font-family'), ubuntuFont.family);
assert.strictEqual(docElement.style.getPropertyValue('--font-body'), ubuntuFont.family);
assert.strictEqual(docElement.style.getPropertyValue('--font-display'), ubuntuFont.family);

// 3. Render font cards and test active state
console.log('Testing renderFontCards and active card tracking...');
renderFontCards('system');
const cards = fontCardsGrid.children;
assert(cards.length > 0, 'fontCardsGrid should have children cards');

const activeCards = cards.filter(c => c.classList.has('active'));
assert.strictEqual(activeCards.length, 1, 'Exactly one card should be active in system category');
assert.strictEqual(activeCards[0].dataset.fontId, 'ubuntu', 'The active card should be ubuntu');

// 4. Test category switching preserves active ID
console.log('Testing category switching...');
renderFontCards('mono');
const monoCards = fontCardsGrid.children;
const activeMonoCards = monoCards.filter(c => c.classList.has('active'));
assert.strictEqual(activeMonoCards.length, 0, 'No card should be active in mono when ubuntu is selected');

// 5. Select a mono card (Consolas)
const consolasCard = monoCards.find(c => c.dataset.fontId === 'consolas');
assert(consolasCard, 'Consolas card must exist in mono');
consolasCard.click();

assert(docElement.style.getPropertyValue('--font-family').includes('Consolas'), 'CSS variable should be Consolas');
assert(consolasCard.classList.has('active'), 'Consolas card should be marked active');

// 6. Return to system category - no system card should be active now
renderFontCards('system');
const systemCards = fontCardsGrid.children;
const activeSysCards = systemCards.filter(c => c.classList.has('active'));
assert.strictEqual(activeSysCards.length, 0, 'No card in system should be active when Consolas is selected');

// 7. Return to mono category - Consolas should be active
renderFontCards('mono');
const monoCardsAgain = fontCardsGrid.children;
const activeMonoAgain = monoCardsAgain.filter(c => c.classList.has('active'));
assert.strictEqual(activeMonoAgain.length, 1, 'Consolas should still be active when returning to mono');
assert.strictEqual(activeMonoAgain[0].dataset.fontId, 'consolas');

console.log('All JS font logic tests passed successfully!');
