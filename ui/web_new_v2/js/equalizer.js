// NeDotify - Equalizer Module
import { setEq } from './player.js';
import { showToast } from './utils.js';

let eqPreamp = 0;
let eqBands = [0, 0, 0, 0, 0, 0, 0, 0, 0, 0];
let currentEqMode = 3; // 3, 6, or 10 bands
let saveTimeout = null;
let initialized = false;
let editRevision = 0;
let committedEq = { preamp: 0, bands: [...eqBands], mode: currentEqMode };

const PRESETS = {
    flat: [0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
    bass_boost: [6, 5, 3, 1, 0, 0, 0, 0, 0, 0],
    treble_boost: [0, 0, 0, 0, 0, 1, 3, 5, 6, 7],
    vocal: [-2, -1, 1, 3, 4, 4, 3, 1, 0, -1],
    rock: [4, 3, 2, 0, -1, -1, 1, 3, 4, 5],
    pop: [-1, 1, 3, 4, 4, 3, 1, 0, 1, 2],
    jazz: [3, 2, 1, 2, -1, -1, 0, 1, 2, 3]
};

const PRESET_LABELS = {
    flat: 'Пресет: Сброс (Flat)',
    bass_boost: 'Пресет: Усиление баса',
    treble_boost: 'Пресет: Усиление высоких',
    vocal: 'Пресет: Вокал',
    rock: 'Пресет: Рок',
    pop: 'Пресет: Поп',
    jazz: 'Пресет: Джаз'
};

const BAND_CONFIGS = {
    3: [
        { label: 'Низкие', bands: [0, 1, 2] },
        { label: 'Средние', bands: [3, 4, 5, 6] },
        { label: 'Высокие', bands: [7, 8, 9] }
    ],
    6: [
        { label: '60 Hz', bands: [0, 1] },
        { label: '150 Hz', bands: [2] },
        { label: '400 Hz', bands: [3, 4] },
        { label: '1.2 kHz', bands: [5, 6] },
        { label: '4 kHz', bands: [7, 8] },
        { label: '15 kHz', bands: [9] }
    ],
    10: [
        { label: '32Hz', bands: [0] },
        { label: '64Hz', bands: [1] },
        { label: '125Hz', bands: [2] },
        { label: '250Hz', bands: [3] },
        { label: '500Hz', bands: [4] },
        { label: '1kHz', bands: [5] },
        { label: '2kHz', bands: [6] },
        { label: '4kHz', bands: [7] },
        { label: '8kHz', bands: [8] },
        { label: '16kHz', bands: [9] }
    ]
};

export async function initEqualizer() {
    const container = document.getElementById('eq-bands-container');
    if (!container || initialized) return;
    initialized = true;

    // Render Band Sliders according to currentEqMode
    renderBandSliders();

    // Mode Selector Buttons (3 / 6 / 10 bands)
    const modeGroup = document.getElementById('eq-mode-btn-group');
    if (modeGroup) {
        modeGroup.querySelectorAll('.eq-mode-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                modeGroup.querySelectorAll('.eq-mode-btn').forEach(b => {
                    b.classList.remove('active');
                    b.style.background = 'transparent';
                    b.style.color = 'var(--text-sec)';
                });
                btn.classList.add('active');
                btn.style.background = 'var(--primary)';
                btn.style.color = '#fff';
                
                currentEqMode = parseInt(btn.dataset.mode) || 3;
                renderBandSliders();
                updateEqUI();
                applyEq();
            });
        });
    }

    // Custom Glass Dropdown Setup
    const dropdownBtn = document.getElementById('eq-dropdown-btn');
    const dropdownMenu = document.getElementById('eq-dropdown-menu');
    const currentTextSpan = document.getElementById('eq-preset-current-text');

    if (dropdownBtn && dropdownMenu) {
        dropdownBtn.setAttribute('aria-controls', dropdownMenu.id);
        dropdownBtn.setAttribute('aria-expanded','false');
        dropdownMenu.setAttribute('role','listbox');
        dropdownMenu.setAttribute('aria-label','Пресет эквалайзера');
        const closeDropdown = () => {
            dropdownMenu.classList.add('hidden');
            dropdownBtn.setAttribute('aria-expanded','false');
        };
        dropdownBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            dropdownMenu.classList.toggle('hidden');
            dropdownBtn.setAttribute('aria-expanded',String(!dropdownMenu.classList.contains('hidden')));
        });
        dropdownBtn.addEventListener('keydown', event => {
            if (event.key !== 'ArrowDown') return;
            event.preventDefault();event.stopPropagation();
            dropdownMenu.classList.remove('hidden');dropdownBtn.setAttribute('aria-expanded','true');
            dropdownMenu.querySelector('.custom-glass-dropdown-item.active, .custom-glass-dropdown-item')?.focus();
        });

        document.addEventListener('click', (e) => {
            if (!e.target.closest('#eq-custom-preset-dropdown')) {
                closeDropdown();
            }
        });

        dropdownMenu.querySelectorAll('.custom-glass-dropdown-item').forEach(item => {
            item.setAttribute('role','option');item.tabIndex=0;
            item.addEventListener('keydown', event => {
                if (['Enter',' ','ArrowDown','ArrowUp','Escape'].includes(event.key)) {
                    event.preventDefault();event.stopPropagation();
                    const items=[...dropdownMenu.querySelectorAll('.custom-glass-dropdown-item')];
                    const index=items.indexOf(item);
                    if(event.key==='Enter' || event.key===' ') { item.click();dropdownBtn.focus(); }
                    else if(event.key==='Escape') { closeDropdown();dropdownBtn.focus(); }
                    else items[(index+(event.key==='ArrowDown'?1:-1)+items.length)%items.length].focus();
                }
            });
            item.addEventListener('click', () => {
                const presetKey = item.dataset.value;
                dropdownMenu.querySelectorAll('.custom-glass-dropdown-item').forEach(i => i.classList.remove('active'));
                item.classList.add('active');
                
                if (currentTextSpan) currentTextSpan.textContent = PRESET_LABELS[presetKey] || item.textContent;
                closeDropdown();

                if (PRESETS[presetKey]) {
                    eqBands = [...PRESETS[presetKey]];
                    updateEqUI();
                    applyEq();
                }
            });
        });
    }



    // Preamp Slider
    const preampSlider = document.getElementById('eq-preamp');
    if (preampSlider) {
        preampSlider.addEventListener('input', (e) => {
            eqPreamp = parseFloat(e.target.value);
            updateEqUI();
            applyEq();
        });
    }

    // Reset Button
    const resetBtn = document.getElementById('btn-eq-reset');
    if (resetBtn) {
        resetBtn.addEventListener('click', () => {
            eqPreamp = 0;
            eqBands = [0, 0, 0, 0, 0, 0, 0, 0, 0, 0];
            if (currentTextSpan) currentTextSpan.textContent = PRESET_LABELS['flat'];
            if (dropdownMenu) {
                dropdownMenu.querySelectorAll('.custom-glass-dropdown-item').forEach(i => {
                    i.classList.toggle('active', i.dataset.value === 'flat');
                });
            }
            updateEqUI();
            applyEq();
        });
    }

    // Restore cached state
    try {
        const cachedEq = localStorage.getItem('nedotify_equalizer');
        if (cachedEq) {
            const data = JSON.parse(cachedEq);
            restoreEq(data);
            committedEq = { preamp: eqPreamp, bands: [...eqBands], mode: currentEqMode };
            renderBandSliders();
            updateEqUI();
            setEq(eqPreamp, eqBands);
        }
    } catch(e) {}

    if (BAND_CONFIGS[window.settings?.equalizer?.mode]) {
        currentEqMode = Number(window.settings.equalizer.mode);
        renderBandSliders();
    }
    updateEqUI();

    try {
        if (window.pywebview?.api) {
            const revision = editRevision;
            const eqData = await window.pywebview.api.get_equalizer();
            if (eqData && revision === editRevision) {
                restoreEq(eqData);
                committedEq = { preamp: eqPreamp, bands: [...eqBands], mode: currentEqMode };
                renderBandSliders();
                updateEqUI();
                setEq(eqPreamp, eqBands);
            }
        }
    } catch (e) {
        console.error("Failed to fetch equalizer data:", e);
    }
}

function renderBandSliders() {
    const container = document.getElementById('eq-bands-container');
    if (!container) return;

    container.innerHTML = '';
    const config = BAND_CONFIGS[currentEqMode] || BAND_CONFIGS[3];

    config.forEach((group, groupIdx) => {
        const col = document.createElement('div');
        col.className = 'eq-band-col';
        col.style.display = 'flex';
        col.style.flexDirection = 'column';
        col.style.alignItems = 'center';
        col.style.gap = '6px';
        col.style.flex = '1';
        
        const valLabel = document.createElement('span');
        valLabel.className = 'eq-val-label';
        valLabel.id = `eq-val-group-${groupIdx}`;
        valLabel.style.fontSize = '10px';
        valLabel.style.color = 'var(--text-sec)';
        valLabel.textContent = '0 dB';

        const slider = document.createElement('input');
        slider.type = 'range';
        slider.min = -20;
        slider.max = 20;
        slider.step = 0.1;
        slider.value = 0;
        slider.className = 'eq-band-slider eq-slider';
        slider.dataset.group = groupIdx;
        slider.setAttribute('aria-label',`Эквалайзер: ${group.label}, dB`);
        
        slider.style.writingMode = 'vertical-lr';
        slider.style.direction = 'rtl';
        slider.style.height = '85px';
        slider.style.width = '20px';
        slider.style.cursor = 'pointer';
        
        const label = document.createElement('span');
        label.className = 'eq-label';
        label.style.fontSize = currentEqMode === 10 ? '9px' : '11px';
        label.style.fontWeight = '500';
        label.style.textAlign = 'center';
        label.textContent = group.label;

        col.appendChild(valLabel);
        col.appendChild(slider);
        col.appendChild(label);
        container.appendChild(col);

        slider.addEventListener('input', (e) => {
            const val = parseFloat(e.target.value);
            group.bands.forEach(idx => {
                eqBands[idx] = val;
            });
            valLabel.textContent = formatDbVal(val);
            syncPresetSelection();
            applyEq();
        });
    });
}

function formatDbVal(val) {
    const num = parseFloat(val) || 0;
    return `${num > 0 ? '+' : ''}${num.toFixed(1)} dB`;
}

function updateEqUI() {
    const preampSlider = document.getElementById('eq-preamp');
    if (preampSlider) {
        preampSlider.value = eqPreamp;
        preampSlider.style.setProperty('--value-percent',`${(eqPreamp+20)/40*100}%`);
        document.getElementById('eq-val-preamp').textContent = formatDbVal(eqPreamp);
    }

    const config = BAND_CONFIGS[currentEqMode] || BAND_CONFIGS[3];
    const sliders = document.querySelectorAll('.eq-band-slider');

    sliders.forEach(s => {
        const groupIdx = parseInt(s.dataset.group);
        if (!isNaN(groupIdx) && config[groupIdx]) {
            const group = config[groupIdx];
            let sum = 0;
            group.bands.forEach(idx => { sum += eqBands[idx]; });
            const avg = sum / group.bands.length;
            s.value = avg;
            const valLabel = document.getElementById(`eq-val-group-${groupIdx}`);
            if (valLabel) valLabel.textContent = formatDbVal(avg);
        }
    });
    document.querySelectorAll('.eq-mode-btn').forEach(button => {
        const active=Number(button.dataset.mode)===currentEqMode;
        button.classList.toggle('active',active);button.setAttribute('aria-pressed',String(active));
        button.style.background=active?'var(--primary)':'transparent';
        button.style.color=active?'var(--primary-fg)':'var(--text-sec)';
    });
    syncPresetSelection();
}

function restoreEq(data) {
    const gain = value => Math.max(-20,Math.min(20,Number(value)||0));
    eqPreamp=gain(data.preamp);
    eqBands=Array.from({length:10},(_,index)=>gain(data.bands?.[index]));
    if(BAND_CONFIGS[data.mode])currentEqMode=Number(data.mode);
    publishEqState();
}

function syncPresetSelection() {
    const preset=Object.keys(PRESETS).find(key=>PRESETS[key].every((value,index)=>Math.abs(value-eqBands[index])<.01));
    const label=document.getElementById('eq-preset-current-text');
    if(label)label.textContent=PRESET_LABELS[preset] || 'Пресет: Пользовательский';
    document.querySelectorAll('.custom-glass-dropdown-item').forEach(item=>{
        const active=item.dataset.value===preset;
        item.classList.toggle('active',active);item.setAttribute('aria-selected',String(active));
    });
}

function publishEqState() {
    if(window.settings)window.settings.equalizer={preamp:eqPreamp,bands:[...eqBands],mode:currentEqMode};
    window.dispatchEvent(new CustomEvent('nedotify:equalizer_changed'));
}

function applyEq() {
    editRevision++;
    setEq(eqPreamp, eqBands);
    publishEqState();

    if (saveTimeout) clearTimeout(saveTimeout);
    saveTimeout = setTimeout(() => {
        const revision = editRevision;
        const next = { preamp: eqPreamp, bands: [...eqBands], mode: currentEqMode };
        const rollback = () => {
            if (revision !== editRevision) return;
            restoreEq(committedEq);
            renderBandSliders(); updateEqUI(); setEq(eqPreamp, eqBands);
            showToast('Не удалось сохранить эквалайзер','error');
        };
        try {
            const api = window.pywebview?.api;
            if (!api?.set_equalizer) throw new Error('Bridge unavailable');
            Promise.resolve(api.set_equalizer(next.preamp, next.bands, next.mode)).then(result => {
                if (result === false || result?.success === false) throw new Error('Setting rejected');
                committedEq = next;
                try { localStorage.setItem('nedotify_equalizer', JSON.stringify(next)); } catch {}
            }).catch(rollback);
        } catch { rollback(); }
    }, 200);
}

// Shared edits from the compact audio panel use this same persisted EQ state.
export function setEqualizerState(data) {
    restoreEq({...window.settings?.equalizer,...data});
    renderBandSliders();updateEqUI();applyEq();
}
