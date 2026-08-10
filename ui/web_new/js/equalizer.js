// NeDotify - Equalizer Module
import { renderIcons } from './utils.js?v=19';
import { setEq } from './player.js?v=19';

let eqPreamp = 0;
let eqBands = [0, 0, 0, 0, 0, 0, 0, 0, 0, 0];
let saveTimeout = null;

const PRESETS = {
    flat: [0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
    bass_boost: [6, 5, 3, 1, 0, 0, 0, 0, 0, 0],
    treble_boost: [0, 0, 0, 0, 0, 1, 3, 5, 6, 7],
    vocal: [-2, -1, 1, 3, 4, 4, 3, 1, 0, -1],
    rock: [4, 3, 2, 0, -1, -1, 1, 3, 4, 5],
    pop: [-1, 1, 3, 4, 4, 3, 1, 0, 1, 2],
    jazz: [3, 2, 1, 2, -1, -1, 0, 1, 2, 3]
};

export async function initEqualizer() {
    const container = document.getElementById('eq-bands-container');
    if (!container) return;

    const threeBands = [
        { label: 'Низкие', bands: [0, 1, 2], index: 0 },
        { label: 'Средние', bands: [3, 4, 5, 6], index: 1 },
        { label: 'Высокие', bands: [7, 8, 9], index: 2 }
    ];

    // Generate sliders
    container.innerHTML = '';
    threeBands.forEach((band) => {
        const col = document.createElement('div');
        col.className = 'eq-band-col';
        col.style.display = 'flex';
        col.style.flexDirection = 'column';
        col.style.alignItems = 'center';
        col.style.gap = '6px';
        
        const valLabel = document.createElement('span');
        valLabel.className = 'eq-val-label';
        valLabel.id = `eq-val-group-${band.index}`;
        valLabel.style.fontSize = '11px';
        valLabel.style.color = 'var(--text-sec)';
        valLabel.textContent = '0 dB';

        const slider = document.createElement('input');
        slider.type = 'range';
        slider.min = -20;
        slider.max = 20;
        slider.step = 0.1;
        slider.value = 0;
        slider.className = 'eq-band-slider eq-slider';
        slider.dataset.index = band.index;
        
        // Standard Chromium / WebView2 Vertical Slider CSS
        slider.style.writingMode = 'vertical-lr';
        slider.style.direction = 'rtl';
        slider.style.appearance = 'slider-vertical';
        slider.style.webkitAppearance = 'slider-vertical';
        slider.style.height = '90px';
        slider.style.width = '24px';
        slider.style.cursor = 'pointer';
        
        const label = document.createElement('span');
        label.className = 'eq-label';
        label.style.fontSize = '12px';
        label.style.fontWeight = '500';
        label.textContent = band.label;

        col.appendChild(valLabel);
        col.appendChild(slider);
        col.appendChild(label);
        container.appendChild(col);

        slider.addEventListener('input', (e) => {
            const val = parseFloat(e.target.value);
            band.bands.forEach(idx => {
                eqBands[idx] = val;
            });
            valLabel.textContent = formatDbVal(val);
            applyEq();
        });
    });

    const preampSlider = document.getElementById('eq-preamp');
    if (preampSlider) {
        preampSlider.addEventListener('input', (e) => {
            eqPreamp = parseFloat(e.target.value);
            document.getElementById('eq-val-preamp').textContent = formatDbVal(eqPreamp);
            applyEq();
        });
    }

    const resetBtn = document.getElementById('btn-eq-reset');
    if (resetBtn) {
        resetBtn.addEventListener('click', () => {
            eqPreamp = 0;
            eqBands = [0, 0, 0, 0, 0, 0, 0, 0, 0, 0];
            const presetSelect = document.getElementById('eq-preset-select');
            if (presetSelect) presetSelect.value = 'flat';
            updateEqUI();
            applyEq();
        });
    }

    const presetSelect = document.getElementById('eq-preset-select');
    if (presetSelect) {
        presetSelect.addEventListener('change', (e) => {
            const presetKey = e.target.value;
            if (PRESETS[presetKey]) {
                eqBands = [...PRESETS[presetKey]];
                updateEqUI();
                applyEq();
            }
        });
    }

    // Fetch initial state from local cache first, then backend
    try {
        const cachedEq = localStorage.getItem('nedotify_equalizer');
        if (cachedEq) {
            const data = JSON.parse(cachedEq);
            eqPreamp = data.preamp || 0;
            eqBands = data.bands || [0, 0, 0, 0, 0, 0, 0, 0, 0, 0];
            updateEqUI();
            setEq(eqPreamp, eqBands);
        }
    } catch(e) {}

    try {
        if (window.pywebview?.api) {
            const eqData = await window.pywebview.api.get_equalizer();
            if (eqData) {
                eqPreamp = eqData.preamp || 0;
                eqBands = eqData.bands || [0, 0, 0, 0, 0, 0, 0, 0, 0, 0];
                updateEqUI();
                setEq(eqPreamp, eqBands);
            }
        }
    } catch (e) {
        console.error("Failed to fetch initial equalizer data:", e);
    }
}

function formatDbVal(val) {
    const num = parseFloat(val) || 0;
    return `${num > 0 ? '+' : ''}${num.toFixed(1)} dB`;
}

function updateEqUI() {
    const preampSlider = document.getElementById('eq-preamp');
    if (preampSlider) {
        preampSlider.value = eqPreamp;
        document.getElementById('eq-val-preamp').textContent = formatDbVal(eqPreamp);
    }
    const bands = document.querySelectorAll('.eq-band-slider');
    const threeBandsMapping = [
        [0, 1, 2],       // 0: Low
        [3, 4, 5, 6],    // 1: Mid
        [7, 8, 9]        // 2: High
    ];
    bands.forEach(b => {
        const idx = parseInt(b.dataset.index);
        if (!isNaN(idx) && idx >= 0 && idx < 3) {
            const group = threeBandsMapping[idx];
            let sum = 0;
            group.forEach(gIdx => { sum += eqBands[gIdx]; });
            const avg = sum / group.length;
            b.value = avg;
            const valLabel = document.getElementById(`eq-val-group-${idx}`);
            if (valLabel) valLabel.textContent = formatDbVal(avg);
        }
    });
}

function applyEq() {
    // 1. Instant AudioNode update
    setEq(eqPreamp, eqBands);

    // 2. Debounced save to avoid IPC & I/O spam
    if (saveTimeout) clearTimeout(saveTimeout);
    saveTimeout = setTimeout(() => {
        try {
            localStorage.setItem('nedotify_equalizer', JSON.stringify({ preamp: eqPreamp, bands: eqBands }));
        } catch(e) {}
        
        if (window.pywebview?.api?.set_equalizer) {
            window.pywebview.api.set_equalizer(eqPreamp, eqBands).catch(() => {});
        }
    }, 200);
}



