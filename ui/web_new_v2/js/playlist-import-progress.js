const imports = new Map();
let hideImportProgress;
const stageOrder = { extracting: 0, saved: 1, checking: 2, done: 3 };

function showImportProgress(update) {
    const importProgress = document.getElementById('playlist-import-progress');
    const job = imports.get(update.job_id);
    if (!job || !importProgress || !(update.stage in stageOrder)) return;
    const order = stageOrder[update.stage];
    if (order < job.order || (order === job.order && (update.checked ?? update.extracted ?? 0) < job.count)) return;
    job.order = order;
    job.count = update.checked ?? update.extracted ?? 0;
    if (update.extracted != null) job.extracted = update.extracted;
    clearTimeout(hideImportProgress);
    importProgress.hidden = false;
    importProgress.textContent = order < 2
        ? `Импорт плейлиста · извлечено ${job.extracted}`
        : order === 2
            ? `Проверка треков · ${update.checked} из ${update.total} · доступно ${update.available}`
            : update.total
                ? `Импорт завершён · доступно ${update.available} · недоступно ${update.unavailable} · без подтверждения ${update.unknown}`
                : `Импорт завершён · извлечено ${job.extracted}`;
    if (update.stage === 'done') {
        imports.delete(update.job_id);
        hideImportProgress = setTimeout(() => { importProgress.hidden = true; }, 6000);
    }
}

window.addEventListener('nedotify:playlist_import_progress', ({detail}) => showImportProgress(detail || {}));

export async function importPlaylist(url, name) {
    const jobId = crypto.randomUUID();
    imports.set(jobId, {order: 0, count: 0, extracted: 0});
    showImportProgress({job_id: jobId, stage: 'extracting', extracted: 0});
    let result;
    try {
        result = await window.pywebview.api.import_external_playlist(url, name, jobId);
        return result;
    } finally {
        if (!result?.success) {
            imports.delete(jobId);
            const banner = document.getElementById('playlist-import-progress');
            if (banner) banner.hidden = true;
        }
    }
}
