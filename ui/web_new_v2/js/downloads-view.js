let downloadHost = null;
let downloadRows = new Map();
let downloadItems = [];
let refreshTimer = null;
let refreshPromise = null;
let refreshAgain = false;
let visibleLimit = 80;
import { openSetupPanel } from './setup-panel.js';

const statusLabels = {
    queued: 'В очереди', resolving: 'Поиск аудио', processing: 'Сохранение и теги',
    pending: 'В очереди', downloading: 'Скачивается', paused: 'На паузе',
    completed: 'Готово', failed: 'Ошибка', cancelled: 'Отменено'
};

function formatBytes(value) {
    const bytes = Math.max(0, Number(value) || 0);
    return bytes >= 1048576 ? `${(bytes / 1048576).toFixed(1)} МБ` : `${Math.round(bytes / 1024)} КБ`;
}

function notify(message) {
    window.dispatchEvent(new CustomEvent('nedotify:toast', {detail: {msg: message, type: 'warning'}}));
}

function createDownloadRow(item) {
    const row = document.createElement('li');
    row.className = 'download-manager-row';
    row.innerHTML = '<div class="download-manager-track"><strong></strong><span></span><small></small></div>' +
        '<div class="download-manager-state"><span></span><progress max="100"></progress></div>' +
        '<div class="download-manager-actions"><button type="button" class="download-manager-action"></button><button type="button" data-action="cancel">Отменить</button></div>';
    row.dataset.trackId = String(item.track_id);
    downloadRows.set(String(item.track_id), row);
    return row;
}

function updateDownloadRow(row, item) {
    const title = item.title || `Трек ${item.track_id}`;
    row.dataset.status = item.status;
    row.querySelector('strong').textContent = title;
    row.querySelector('.download-manager-track > span').textContent = item.artist || item.source || '';
    const error = row.querySelector('small');
    error.textContent = item.status === 'failed' ? item.user_error?.message || 'Не удалось скачать трек. Повторите загрузку.' : item.warning || '';
    error.hidden = !error.textContent;
    const progress = row.querySelector('progress');
    progress.setAttribute('aria-label', `Загрузка: ${title}`);
    if (Number.isFinite(item.percent)) progress.value = item.percent;
    else progress.removeAttribute('value');
    progress.hidden = !['downloading', 'paused', 'pending'].includes(item.status);
    const bytes = item.downloaded_bytes > 0 ? ` · ${formatBytes(item.downloaded_bytes)}` : '';
    const total = item.total_bytes > 0 ? ` / ${formatBytes(item.total_bytes)}` : '';
    const speed = item.bytes_per_second > 0 ? ` · ${formatBytes(item.bytes_per_second)}/с` : '';
    row.querySelector('.download-manager-state > span').textContent = `${statusLabels[item.stage || item.status] || item.status}${bytes}${total}${speed}`;
    const action = row.querySelector('button');
    const pausable = ['pending', 'downloading'].includes(item.status);
    const retryable = ['failed','cancelled'].includes(item.status);
    const repairable = retryable && item.user_error?.action === 'setup';
    action.hidden = !pausable && item.status !== 'paused' && !retryable;
    action.dataset.action = repairable ? 'setup' : retryable ? 'retry' : pausable ? 'pause' : 'resume';
    action.textContent = repairable ? 'Компоненты' : retryable ? 'Повторить' : pausable ? 'Пауза' : 'Продолжить';
    action.setAttribute('aria-label', `${pausable ? 'Приостановить' : 'Продолжить'} загрузку: ${title}`);
    const cancel = row.querySelector('[data-action="cancel"]');
    cancel.hidden = !pausable && item.status !== 'paused';
    cancel.setAttribute('aria-label', `Отменить загрузку: ${title}`);
}

function renderDownloads() {
    if (!downloadHost) return;
    const list = downloadHost.querySelector('.download-manager-list');
    const visible = downloadItems.slice(0, visibleLimit);
    const retained = new Set(visible.map(item => String(item.track_id)));
    for (const [trackId, row] of downloadRows) {
        if (!retained.has(trackId)) {
            row.remove();
            downloadRows.delete(trackId);
        }
    }
    visible.forEach((item, index) => {
        const row = downloadRows.get(String(item.track_id)) || createDownloadRow(item);
        updateDownloadRow(row, item);
        if (list.children[index] !== row) list.insertBefore(row, list.children[index] || null);
    });
    const active = downloadItems.filter(item => ['pending', 'downloading'].includes(item.status)).length;
    const paused = downloadItems.filter(item => item.status === 'paused').length;
    const failed = downloadItems.filter(item => item.status === 'failed').length;
    downloadHost.querySelector('.download-manager-count').textContent = active ? `${active} в очереди` : paused ? `${paused} на паузе` : failed ? `${failed} с ошибкой` : '';
    downloadHost.querySelector('[data-action="pause-all"]').disabled = !active;
    downloadHost.querySelector('[data-action="resume-all"]').disabled = !paused;
    downloadHost.querySelector('[data-action="retry-failed"]').disabled = !failed;
    const more = downloadHost.querySelector('[data-action="more"]');
    more.hidden = downloadItems.length <= visibleLimit;
    more.textContent = `Показать ещё (${Math.max(0, downloadItems.length - visibleLimit)})`;
    const message = downloadHost.querySelector('.download-manager-message');
    message.textContent = downloadItems.length ? '' : 'Здесь появятся загрузки. Поставьте треки на скачивание из меню трека.';
    message.hidden = !!downloadItems.length;
}

async function refreshDownloads() {
    if (!downloadHost) return;
    if (refreshPromise) {
        refreshAgain = true;
        return refreshPromise;
    }
    const method = window.pywebview?.api?.get_downloads;
    if (!method) return;
    refreshPromise = (async () => {
        try {
            const rows = await window.pywebview.api.get_downloads();
            if (!Array.isArray(rows)) throw new Error('Unexpected download list');
            downloadItems = rows;
            renderDownloads();
        } catch (error) {
            const message = downloadHost?.querySelector('.download-manager-message');
            if (message) {
                message.hidden = false;
                message.textContent = 'Не удалось прочитать очередь. Нажмите «Обновить».';
            }
        }
    })();
    try {
        await refreshPromise;
    } finally {
        refreshPromise = null;
        if (refreshAgain) {
            refreshAgain = false;
            scheduleRefresh();
        }
    }
}

function scheduleRefresh() {
    if (!downloadHost || refreshTimer !== null) return;
    refreshTimer = setTimeout(() => {
        refreshTimer = null;
        refreshDownloads();
    }, 180);
}

async function runDownloadAction(event) {
    const button = event.target.closest('button[data-action]');
    if (!button || button.disabled) return;
    const action = button.dataset.action;
    if (action === 'more') {
        visibleLimit += 80;
        renderDownloads();
        return;
    }
    if (action === 'refresh') {
        await refreshDownloads();
        return;
    }
    if (action === 'setup') { await openSetupPanel(); return; }
    const methods = {cancel:'cancel_download', retry:'retry_download', pause: 'pause_download', 'pause-all': 'pause_download', resume: 'resume_download', 'resume-all': 'resume_download', 'retry-failed': 'retry_failed_downloads'};
    const method = methods[action];
    if (!window.pywebview?.api?.[method]) return;
    const trackId = button.closest('[data-track-id]')?.dataset.trackId;
    button.disabled = true;
    try {
        const result = await window.pywebview.api[method](...(trackId ? [trackId] : []));
        if (result?.success === false) notify(result.message || 'Не удалось изменить загрузку. Попробуйте ещё раз.');
        await refreshDownloads();
    } catch (error) {
        notify('Не удалось изменить загрузку. Попробуйте ещё раз.');
    } finally {
        button.disabled = false;
    }
}

export function initDownloadManagerView(host) {
    if (!host) return;
    if (downloadHost === host) {
        scheduleRefresh();
        return;
    }
    if (downloadHost) downloadHost.removeEventListener('click', runDownloadAction);
    downloadHost = host;
    downloadRows = new Map();
    host.classList.add('download-manager');
    host.innerHTML = '<details><summary><span>Загрузки</span><span class="download-manager-count"></span></summary>' +
        '<div class="download-manager-toolbar"><button type="button" data-action="pause-all">Пауза всех</button>' +
        '<button type="button" data-action="resume-all">Продолжить все</button>' +
        '<button type="button" data-action="retry-failed">Повторить ошибки</button>' +
        '<button type="button" data-action="setup">Качество и компоненты</button>' +
        '<button type="button" data-action="refresh">Обновить</button></div>' +
        '<p class="download-manager-message" role="status">Загрузка очереди…</p>' +
        '<ul class="download-manager-list" aria-label="Очередь загрузок"></ul>' +
        '<button type="button" data-action="more" hidden></button></details>';
    host.addEventListener('click', runDownloadAction);
    scheduleRefresh();
}

export function handleDownloadManagerEvent(name, payload) {
    if (!downloadHost) return;
    if (name === 'download_progress' && payload?.track_id !== undefined) {
        const item = downloadItems.find(track => String(track.track_id) === String(payload.track_id));
        if (item) {
            Object.assign(item, payload);
            const row = downloadRows.get(String(payload.track_id));
            if (row) updateDownloadRow(row, item);
            return;
        }
    }
    scheduleRefresh();
}
