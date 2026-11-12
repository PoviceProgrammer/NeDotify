/**
 * NeDotify Application Updater (Frontend Module)
 * Connects to pywebview bridge and fallback GitHub API to check for new releases
 * and display a Riff-style connected top notification banner.
 */

let currentAppVersion = '2.5.7';
let latestUpdateInfo = null;
let isCheckingUpdates = false;

function formatRelativeTime(dateString) {
    if (!dateString) return '';
    try {
        const d = new Date(dateString);
        if (isNaN(d.getTime())) return '';
        const now = new Date();
        const diffDays = Math.floor((now - d) / (1000 * 60 * 60 * 24));
        if (diffDays <= 0) return 'Сегодня';
        if (diffDays === 1) return 'Вчера';
        if (diffDays < 30) return `${diffDays} дн. назад`;
        return d.toLocaleDateString('ru-RU', { day: 'numeric', month: 'short', year: 'numeric' });
    } catch (_) {
        return '';
    }
}

function parseReleaseNotes(markdown) {
    if (!markdown) return 'Исправления ошибок и улучшения стабильности.';
    // Clean up markdown headers and backticks for clean readable text
    return markdown
        .replace(/^#{1,6}\s+/gm, '')
        .replace(/\*\*(.*?)\*\*/g, '$1')
        .replace(/`(.*?)`/g, '$1')
        .trim();
}

export function hideUpdateBanner() {
    const banner = document.getElementById('update-banner');
    if (!banner || banner.classList.contains('hidden')) return;
    banner.classList.add('leaving');
    setTimeout(() => {
        banner.classList.add('hidden');
        banner.classList.remove('leaving');
    }, 200);
}

export function showUpdateBanner(info) {
    if (!info || !info.latest_version) return;
    latestUpdateInfo = info;

    const banner = document.getElementById('update-banner');
    const verEl = document.getElementById('update-banner-version');
    if (!banner) return;

    if (verEl) {
        const v = String(info.latest_version).replace(/^v/i, '');
        verEl.textContent = 'v' + v;
    }

    banner.classList.remove('hidden', 'leaving');
}

export function showUpdateModal(info) {
    const modal = document.getElementById('update-modal');
    if (!modal) return;
    info = info || latestUpdateInfo;
    if (!info) return;

    const badge = document.getElementById('update-modal-badge');
    const timeEl = document.getElementById('update-modal-time');
    const notesEl = document.getElementById('update-modal-notes');

    if (badge) {
        const v = String(info.latest_version || '').replace(/^v/i, '');
        badge.textContent = 'v' + (v || currentAppVersion);
    }
    if (timeEl) {
        timeEl.textContent = formatRelativeTime(info.published_at);
    }
    if (notesEl) {
        notesEl.textContent = parseReleaseNotes(info.release_notes);
    }

    if (typeof modal.showModal === 'function') {
        modal.showModal();
    } else {
        modal.setAttribute('open', '');
    }
}

export function closeUpdateModal() {
    const modal = document.getElementById('update-modal');
    if (!modal) return;
    if (typeof modal.close === 'function') {
        modal.close();
    } else {
        modal.removeAttribute('open');
    }
}

async function openReleaseTarget(url) {
    if (window.pywebview?.api?.open_release_page) {
        try {
            await window.pywebview.api.open_release_page(url);
            return;
        } catch (_) {}
    }
    if (url) {
        window.open(url, '_blank');
    }
}

export async function checkForUpdates(manual = false) {
    if (isCheckingUpdates) return;
    isCheckingUpdates = true;

    const btn = document.getElementById('btn-check-app-updates');
    const statusText = document.getElementById('app-update-status-text');
    const originalBtnText = btn ? btn.textContent : '';

    if (btn) {
        btn.disabled = true;
        btn.textContent = 'Проверка…';
    }
    if (statusText && manual) {
        statusText.textContent = 'Проверяем наличие обновлений на GitHub…';
    }

    try {
        let result = null;

        if (window.pywebview?.api?.check_for_updates) {
            result = await window.pywebview.api.check_for_updates(manual);
        } else {
            // Direct renderer fallback if bridge unavailable
            const res = await fetch('https://api.github.com/repos/PoviceProgrammer/NeDotify/releases/latest', {
                headers: { 'User-Agent': 'NeDotify-Desktop (Windows)' }
            });
            if (res.ok) {
                const data = await res.json();
                const latestTag = String(data.tag_name || '').replace(/^v/i, '');
                const currParts = currentAppVersion.split('.').map(n => parseInt(n, 10) || 0);
                const latestParts = latestTag.split('.').map(n => parseInt(n, 10) || 0);
                let newer = false;
                for (let i = 0; i < Math.max(currParts.length, latestParts.length); i++) {
                    const c = currParts[i] || 0;
                    const l = latestParts[i] || 0;
                    if (l > c) { newer = true; break; }
                    if (l < c) { break; }
                }
                let downloadUrl = '';
                if (Array.isArray(data.assets)) {
                    const exe = data.assets.find(a => (a.name || '').toLowerCase().endsWith('.exe'));
                    if (exe) downloadUrl = exe.browser_download_url;
                }
                result = {
                    current_version: currentAppVersion,
                    latest_version: latestTag,
                    update_available: newer,
                    release_notes: data.body || '',
                    release_url: data.html_url || '',
                    published_at: data.published_at || '',
                    download_url: downloadUrl,
                    error: ''
                };
            } else {
                result = { error: `HTTP ${res.status}` };
            }
        }

        if (result && !result.error && result.update_available) {
            latestUpdateInfo = result;
            if (statusText) {
                statusText.textContent = `Доступна новая версия v${String(result.latest_version).replace(/^v/i, '')}!`;
                statusText.style.color = 'var(--primary)';
            }
            const ignored = localStorage.getItem('nedotify_ignored_update') || '';
            const cleanLatest = String(result.latest_version).replace(/^v/i, '');
            if (manual || cleanLatest !== ignored) {
                showUpdateBanner(result);
            }
        } else if (result && !result.error) {
            if (statusText) {
                statusText.textContent = `У вас установлена последняя версия (v${currentAppVersion})`;
                statusText.style.color = '';
            }
            if (manual && window.NeDotifyToast?.show) {
                window.NeDotifyToast.show('У вас установлена последняя версия NeDotify!', 'success');
            }
        } else {
            const err = result?.error || 'Не удалось связаться с сервером обновлений';
            if (statusText) {
                statusText.textContent = err;
                statusText.style.color = 'var(--error)';
            }
            if (manual && window.NeDotifyToast?.show) {
                window.NeDotifyToast.show(err, 'error');
            }
        }
    } catch (e) {
        if (statusText) {
            statusText.textContent = 'Ошибка при проверке обновлений';
        }
        if (manual && window.NeDotifyToast?.show) {
            window.NeDotifyToast.show('Не удалось проверить обновления', 'error');
        }
    } finally {
        isCheckingUpdates = false;
        if (btn) {
            btn.disabled = false;
            btn.textContent = originalBtnText || 'Проверить обновления';
        }
    }
}

export function initUpdater() {
    // 1. Fetch current version from bridge if possible
    if (window.pywebview?.api?.get_app_version) {
        window.pywebview.api.get_app_version().then(ver => {
            if (ver) {
                currentAppVersion = String(ver).replace(/^v/i, '');
                const badge = document.getElementById('app-version-badge');
                if (badge) badge.textContent = 'v' + currentAppVersion;
            }
        }).catch(() => {});
    }

    // 2. Wire update banner actions
    const banner = document.getElementById('update-banner');
    const btnAction = document.getElementById('update-banner-action-btn');
    const btnDetails = document.getElementById('update-banner-details-btn');
    const btnClose = document.getElementById('update-banner-close-btn');

    if (btnAction) {
        btnAction.addEventListener('click', (e) => {
            e.stopPropagation();
            const target = latestUpdateInfo?.download_url || latestUpdateInfo?.release_url;
            openReleaseTarget(target);
        });
    }

    if (btnDetails) {
        btnDetails.addEventListener('click', (e) => {
            e.stopPropagation();
            showUpdateModal();
        });
    }

    if (btnClose) {
        btnClose.addEventListener('click', (e) => {
            e.stopPropagation();
            if (latestUpdateInfo?.latest_version) {
                localStorage.setItem('nedotify_ignored_update', String(latestUpdateInfo.latest_version).replace(/^v/i, ''));
            }
            hideUpdateBanner();
        });
    }

    if (banner) {
        banner.addEventListener('click', (e) => {
            if (e.target.closest('button')) return;
            showUpdateModal();
        });
    }

    // 3. Wire update modal actions
    const modal = document.getElementById('update-modal');
    const modalClose = document.getElementById('update-modal-close');
    const modalDownload = document.getElementById('update-modal-download-btn');
    const modalWeb = document.getElementById('update-modal-web-btn');
    const modalIgnore = document.getElementById('update-modal-ignore-btn');

    if (modalClose) {
        modalClose.addEventListener('click', closeUpdateModal);
    }
    if (modalDownload) {
        modalDownload.addEventListener('click', () => {
            const target = latestUpdateInfo?.download_url || latestUpdateInfo?.release_url;
            openReleaseTarget(target);
        });
    }
    if (modalWeb) {
        modalWeb.addEventListener('click', () => {
            openReleaseTarget(latestUpdateInfo?.release_url || 'https://github.com/PoviceProgrammer/NeDotify/releases');
        });
    }
    if (modalIgnore) {
        modalIgnore.addEventListener('click', () => {
            if (latestUpdateInfo?.latest_version) {
                localStorage.setItem('nedotify_ignored_update', String(latestUpdateInfo.latest_version).replace(/^v/i, ''));
            }
            hideUpdateBanner();
            closeUpdateModal();
        });
    }

    // 4. Wire settings controls
    const btnCheck = document.getElementById('btn-check-app-updates');
    if (btnCheck) {
        btnCheck.addEventListener('click', () => checkForUpdates(true));
    }

    const btnRepo = document.getElementById('btn-open-github-repo');
    if (btnRepo) {
        btnRepo.addEventListener('click', () => {
            openReleaseTarget('https://github.com/PoviceProgrammer/NeDotify');
        });
    }

    // 5. Listen for backend events
    window.addEventListener('nedotify:update_available', (e) => {
        const info = e.detail;
        if (!info || !info.update_available) return;
        latestUpdateInfo = info;
        const cleanLatest = String(info.latest_version || '').replace(/^v/i, '');
        const ignored = localStorage.getItem('nedotify_ignored_update') || '';
        if (cleanLatest && cleanLatest === ignored) {
            return;
        }
        showUpdateBanner(info);
    });
}
