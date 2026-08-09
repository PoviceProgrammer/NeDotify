
// ==========================================
// SETTINGS LOGIC
// ==========================================

document.addEventListener('DOMContentLoaded', () => {
    // 1. Settings Navigation
    const navBtns = document.querySelectorAll('.settings-nav-btn');
    const panels = document.querySelectorAll('.settings-panel');
    
    navBtns.forEach(btn => {
        btn.addEventListener('click', () => {
            // Remove active from all
            navBtns.forEach(b => {
                b.classList.remove('active', 'text-foreground', 'bg-primary/10', 'border-primary/20', 'shadow-[0_0_15px_rgba(var(--primary),0.1)]');
                b.classList.add('text-muted-foreground');
                const icon = b.querySelector('i');
                if(icon) icon.classList.remove('text-primary');
            });
            // Add active to clicked
            btn.classList.add('active', 'text-foreground', 'bg-primary/10', 'border-primary/20', 'shadow-[0_0_15px_rgba(var(--primary),0.1)]');
            btn.classList.remove('text-muted-foreground');
            const icon = btn.querySelector('i');
            if(icon) icon.classList.add('text-primary');
            
            // Show corresponding panel
            const targetId = btn.getAttribute('data-target');
            panels.forEach(p => p.classList.add('hidden'));
            const targetPanel = document.getElementById(targetId);
            if (targetPanel) targetPanel.classList.remove('hidden');
        });
    });

    // Helper to handle card single selection
    function setupCardSelection(selector, activeClassStr, inactiveClassStr, settingKey) {
        const btns = document.querySelectorAll(selector);
        btns.forEach(btn => {
            btn.addEventListener('click', () => {
                btns.forEach(b => {
                    b.classList.remove('active', ...activeClassStr.split(' '));
                    b.classList.add(...inactiveClassStr.split(' '));
                });
                btn.classList.remove(...inactiveClassStr.split(' '));
                btn.classList.add('active', ...activeClassStr.split(' '));
                
                // Save setting
                if (window.pywebview && window.pywebview.api) {
                    const val = btn.getAttribute('data-' + settingKey);
                    window.pywebview.api.save_setting(settingKey, val, 'ui');
                }
            });
        });
    }

    // Language cards
    setupCardSelection('.settings-lang-btn', 'border-primary/40 bg-primary/5', 'border-border bg-card/30', 'lang');
    // Platform buttons
    setupCardSelection('.settings-plat-btn', 'bg-red-500/20 text-red-500', 'text-muted-foreground hover:bg-accent', 'plat');
    // Blur cards
    setupCardSelection('.settings-blur-btn', 'border-primary/40 bg-primary/5', 'border-border bg-card/30', 'blur');
    // Player alignment
    setupCardSelection('.settings-align-btn', 'border-primary/40 bg-primary/5', 'border-border bg-card/30', 'align');
    // Player style
    setupCardSelection('.settings-style-btn', 'border-primary/40 bg-primary/5', 'border-border bg-card/30', 'style');
    // Slider type
    setupCardSelection('.settings-slider-btn', 'border-primary/40 bg-primary/5', 'border-border bg-card/30', 'slider');

    // Toggle switch helper
    function setupToggle(id, settingKey) {
        const btn = document.getElementById(id);
        if(!btn) return;
        let isOn = btn.classList.contains('bg-primary');
        btn.addEventListener('click', () => {
            isOn = !isOn;
            const thumb = btn.querySelector('div');
            if(isOn) {
                btn.classList.remove('bg-muted');
                btn.classList.add('bg-primary', 'shadow-[0_0_10px_rgba(var(--primary),0.3)]');
                thumb.style.transform = 'translateX(0)';
            } else {
                btn.classList.remove('bg-primary', 'shadow-[0_0_10px_rgba(var(--primary),0.3)]');
                btn.classList.add('bg-muted');
                thumb.style.transform = 'translateX(-20px)';
            }
            if (window.pywebview && window.pywebview.api) {
                window.pywebview.api.save_setting(settingKey, isOn, 'ui');
            }
        });
    }

    setupToggle('toggleSimplifyGraphics', 'simplify_graphics');
    setupToggle('toggleNativeTransp', 'native_transparency');

    // Multi-select for resources
    const resBtns = document.querySelectorAll('.settings-resource-btn');
    resBtns.forEach(btn => {
        btn.addEventListener('click', () => {
            const isActive = btn.classList.contains('active');
            if (isActive) {
                btn.classList.remove('active', 'border-primary/40', 'bg-primary/5');
                btn.classList.add('border-border', 'bg-card/30');
            } else {
                btn.classList.remove('border-border', 'bg-card/30');
                btn.classList.add('active', 'border-primary/40', 'bg-primary/5');
            }
            // Save state
            if (window.pywebview && window.pywebview.api) {
                const activeRes = Array.from(document.querySelectorAll('.settings-resource-btn.active')).map(b => b.getAttribute('data-res'));
                window.pywebview.api.save_setting('active_resources', activeRes, 'ui');
            }
        });
    });

    // Themes
    const themes = [
        { id: 'light', name: 'Light', colors: ['#ffffff', '#e5e7eb'] },
        { id: 'sky', name: 'Sky', colors: ['#38bdf8', '#0284c7'] },
        { id: 'mint', name: 'Mint', colors: ['#34d399', '#059669'] },
        { id: 'violet', name: 'Violet', colors: ['#a78bfa', '#7c3aed'] },
        { id: 'blossom', name: 'Blossom', colors: ['#f472b6', '#db2777'] },
        { id: 'sand', name: 'Sand', colors: ['#fbbf24', '#d97706'] },
        { id: 'aqua', name: 'Aqua', colors: ['#2dd4bf', '#0d9488'] },
        { id: 'amoled', name: 'AMOLED', colors: ['#000000', '#111111'] },
        { id: 'dark', name: 'Dark', colors: ['#1f2937', '#111827'] },
        { id: 'midnight', name: 'Midnight', colors: ['#1e1b4b', '#312e81'] },
        { id: 'emerald', name: 'Emerald', colors: ['#10b981', '#047857'] },
        { id: 'sunset', name: 'Sunset', colors: ['#f97316', '#ec4899'] },
        { id: 'ocean', name: 'Ocean', colors: ['#0ea5e9', '#0369a1'] },
        { id: 'lavender', name: 'Lavender', colors: ['#c084fc', '#9333ea'] },
        { id: 'rose', name: 'Rose', colors: ['#fb7185', '#e11d48'] },
        { id: 'amber', name: 'Amber', colors: ['#f59e0b', '#b45309'] },
        { id: 'slate', name: 'Slate', colors: ['#64748b', '#334155'] }
    ];

    const popup = document.getElementById('themeDropdownPopup');
    if(popup) {
        let themeHtml = '';
        themes.forEach(t => {
            const isActive = t.id === 'sunset' ? 'active border-primary bg-primary/10' : 'border-border bg-accent/30 hover:bg-accent';
            const checkIcon = t.id === 'sunset' ? `<i data-lucide="check" class="absolute top-1 right-1 size-3 text-primary"></i>` : '';
            themeHtml += `
            <button class="theme-option relative p-3 rounded-xl border transition flex flex-col items-center gap-2 ${isActive}" data-theme="${t.id}" data-name="${t.name}" data-color1="${t.colors[0]}" data-color2="${t.colors[1]}">
                ${checkIcon}
                <div class="flex"><div class="size-3 rounded-full shadow-sm -mr-1" style="background-color: ${t.colors[0]}"></div><div class="size-3 rounded-full shadow-sm" style="background-color: ${t.colors[1]}"></div></div>
                <span class="text-[10px] font-bold">${t.name}</span>
            </button>
            `;
        });
        popup.innerHTML = themeHtml;
        lucide.createIcons();

        const themeBtns = document.querySelectorAll('.theme-option');
        themeBtns.forEach(btn => {
            btn.addEventListener('click', () => {
                themeBtns.forEach(b => {
                    b.classList.remove('active', 'border-primary', 'bg-primary/10');
                    b.classList.add('border-border', 'bg-accent/30', 'hover:bg-accent');
                    const check = b.querySelector('i[data-lucide="check"]');
                    if(check) check.remove();
                });
                btn.classList.remove('border-border', 'bg-accent/30', 'hover:bg-accent');
                btn.classList.add('active', 'border-primary', 'bg-primary/10');
                btn.insertAdjacentHTML('afterbegin', `<i data-lucide="check" class="absolute top-1 right-1 size-3 text-primary"></i>`);
                lucide.createIcons();
                
                // Update dropdown button
                document.getElementById('themeDropdownBtnText').innerText = btn.getAttribute('data-name');
                const colors = document.getElementById('themeDropdownBtnColors');
                colors.innerHTML = `
                    <div class="size-4 rounded-full bg-black/50 -mr-1 shadow-sm"></div>
                    <div class="size-4 rounded-full shadow-sm -mr-1" style="background-color: ${btn.getAttribute('data-color1')}"></div>
                    <div class="size-4 rounded-full shadow-sm z-10" style="background-color: ${btn.getAttribute('data-color2')}"></div>
                `;
                
                popup.classList.add('hidden');
                
                if (window.pywebview && window.pywebview.api) {
                    window.pywebview.api.save_setting('theme', btn.getAttribute('data-theme'), 'ui');
                }
            });
        });
    }

    // Sliders
    const opacitySlider = document.getElementById('opacitySlider');
    const opacityLabel = document.getElementById('opacityLabel');
    if (opacitySlider) {
        opacitySlider.addEventListener('input', (e) => {
            opacityLabel.innerText = `${e.target.value}%`;
            document.documentElement.style.setProperty('--bg-opacity', e.target.value / 100);
        });
        opacitySlider.addEventListener('change', (e) => {
            if (window.pywebview && window.pywebview.api) {
                window.pywebview.api.save_setting('opacity', e.target.value, 'ui');
            }
        });
    }

    const glassSlider = document.getElementById('glassSlider');
    const glassLabel = document.getElementById('glassLabel');
    if (glassSlider) {
        glassSlider.addEventListener('input', (e) => {
            glassLabel.innerText = `${e.target.value}px`;
            document.documentElement.style.setProperty('--glass-blur', `${e.target.value}px`);
        });
        glassSlider.addEventListener('change', (e) => {
            if (window.pywebview && window.pywebview.api) {
                window.pywebview.api.save_setting('glass_strength', e.target.value, 'ui');
            }
        });
    }
});

// Update storage UI from Python
function updateStorageUI(data) {
    if (!data) return;
    
    // total: size in MB
    // tracks: {count, size}
    // covers: {count, size}
    
    if(data.total !== undefined) {
        document.getElementById('storageTotalLabel').innerText = `${data.total.toFixed(1)} MB`;
        // update circle progress
        const circle = document.querySelector('#settings-storage-panel circle.text-primary');
        if(circle) {
            // max 1GB for full circle
            let percentage = Math.min(data.total / 1024, 1);
            const circumference = 282.7; // 2 * pi * 45
            circle.style.strokeDashoffset = circumference - (percentage * circumference);
        }
    }
    
    if(data.tracks) {
        document.getElementById('storageTracksLabel').innerText = `${data.tracks.count} элементов • ${data.tracks.size}`;
    }
    if(data.covers) {
        document.getElementById('storageCoversLabel').innerText = `${data.covers.count} элементов • ${data.covers.size}`;
    }
}
