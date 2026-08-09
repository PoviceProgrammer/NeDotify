// NeDotify - Equalizer Module
import { renderIcons } from './utils.js?v=19';
import { setEq } from './player.js?v=19';

let eqPreamp = 0;
let eqBands = [0, 0, 0, 0, 0, 0, 0, 0, 0, 0];
const freqs = ['31', '62', '125', '250', '500', '1k', '2k', '4k', '8k', '16k'];

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
        
        const slider = document.createElement('input');
        slider.type = 'range';
        slider.min = -20;
        slider.max = 20;
        slider.step = 0.1;
        slider.value = 0;
        slider.className = 'eq-band-slider eq-slider';
        slider.dataset.index = band.index;
        slider.style.appearance = 'slider-vertical'; // Webkit vertical support
        
        const label = document.createElement('span');
        label.className = 'eq-label';
        label.textContent = band.label;

        col.appendChild(slider);
        col.appendChild(label);
        container.appendChild(col);

        slider.addEventListener('input', (e) => {
            const val = parseFloat(e.target.value);
            band.bands.forEach(idx => {
                eqBands[idx] = val;
            });
            applyEq();
        });
    });

    const preampSlider = document.getElementById('eq-preamp');
    if (preampSlider) {
        preampSlider.addEventListener('input', (e) => {
            eqPreamp = parseFloat(e.target.value);
            document.getElementById('eq-val-preamp').textContent = `${eqPreamp.toFixed(1)} dB`;
            applyEq();
        });
    }

    const resetBtn = document.getElementById('btn-eq-reset');
    if (resetBtn) {
        resetBtn.addEventListener('click', () => {
            eqPreamp = 0;
            eqBands = [0, 0, 0, 0, 0, 0, 0, 0, 0, 0];
            updateEqUI();
            applyEq();
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

function updateEqUI() {
    const preampSlider = document.getElementById('eq-preamp');
    if (preampSlider) {
        preampSlider.value = eqPreamp;
        document.getElementById('eq-val-preamp').textContent = `${eqPreamp.toFixed(1)} dB`;
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
            b.value = sum / group.length;
        }
    });
}

function applyEq() {
    setEq(eqPreamp, eqBands);
    try {
        localStorage.setItem('nedotify_equalizer', JSON.stringify({ preamp: eqPreamp, bands: eqBands }));
    } catch(e) {}
    
    // Also save to backend for persistence
    if (window.pywebview?.api) {
        window.pywebview.api.set_equalizer(eqPreamp, eqBands).catch(() => {});
    }
}

// Initialization is handled by main.js



