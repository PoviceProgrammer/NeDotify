// NeDotify - Custom Lyrics Editor & Preview Modal
import { renderIcons, showToast, escapeHtml } from './utils.js';
import { getCurrentTrack } from './player.js';

let modalInitialized = false;
let isPreviewMode = false;

export function openLyricsCustomModal() {
    const modal = document.getElementById('modal-custom-lyrics');
    if (!modal) return;

    modal.classList.remove('hidden');
    renderIcons(modal);

    const textarea = document.getElementById('textarea-custom-lyrics');
    const previewBox = document.getElementById('custom-lyrics-preview-box');
    const btnPreview = document.getElementById('btn-custom-lyrics-preview-toggle');

    isPreviewMode = false;
    if (previewBox) previewBox.classList.add('hidden');
    if (textarea) {
        textarea.classList.remove('hidden');

        // Prepopulate with current lyrics if available
        const currentData = window.NeDotify?.getCurrentLyricsData?.();
        if (currentData) {
            textarea.value = currentData.syncedLyrics || currentData.plainLyrics || '';
        } else {
            textarea.value = '';
        }

        setTimeout(() => {
            textarea.focus();
        }, 80);
    }

    if (btnPreview) {
        btnPreview.textContent = 'Предпросмотр';
    }
}

export function closeLyricsCustomModal() {
    const modal = document.getElementById('modal-custom-lyrics');
    if (modal) {
        modal.classList.add('hidden');
    }
}

function togglePreview() {
    const textarea = document.getElementById('textarea-custom-lyrics');
    const previewBox = document.getElementById('custom-lyrics-preview-box');
    const btnPreview = document.getElementById('btn-custom-lyrics-preview-toggle');

    if (!textarea || !previewBox) return;

    isPreviewMode = !isPreviewMode;

    if (isPreviewMode) {
        const text = textarea.value.trim();
        if (!text) {
            previewBox.innerHTML = '<div style="color:var(--text-sec); text-align:center; padding:30px 0;">Текст не введён</div>';
        } else {
            const lines = text.split(/\r?\n/);
            const html = lines.map(line => {
                const trimmed = line.trim();
                const match = trimmed.match(/^(\[\d{1,3}:\d{2}(?:[.:]\d+)?\])(.*)$/);
                if (match) {
                    const tag = match[1];
                    const lyric = match[2].trim() || '♪';
                    return `<div class="cl-line"><span class="cl-timestamp">${escapeHtml(tag)}</span><span>${escapeHtml(lyric)}</span></div>`;
                } else {
                    return `<div class="cl-line"><span>${escapeHtml(trimmed || ' ')}</span></div>`;
                }
            }).join('');
            previewBox.innerHTML = html;
        }

        textarea.classList.add('hidden');
        previewBox.classList.remove('hidden');
        if (btnPreview) btnPreview.textContent = 'Редактировать';
    } else {
        previewBox.classList.add('hidden');
        textarea.classList.remove('hidden');
        if (btnPreview) btnPreview.textContent = 'Предпросмотр';
        textarea.focus();
    }
}

function saveCustomLyrics() {
    const textarea = document.getElementById('textarea-custom-lyrics');
    const track = getCurrentTrack();

    if (!track) {
        showToast('Трек не выбран', 'warning');
        return;
    }

    const text = textarea ? textarea.value.trim() : '';
    if (!text) {
        showToast('Введите текст песни перед сохранением', 'warning');
        return;
    }

    const isSynced = /\[\d{1,3}:\d{2}(?:[.:]\d+)?\]/.test(text);

    if (!window.pywebview?.api?.save_custom_lyrics) {
        showToast('API сохранения текста недоступно', 'error');
        return;
    }

    window.pywebview.api.save_custom_lyrics(track, text, isSynced)
        .then(res => {
            if (res && res.success) {
                showToast('Пользовательский текст успешно сохранён', 'success');
                closeLyricsCustomModal();
                if (window.NeDotify?.reloadCurrentTrackLyrics) {
                    window.NeDotify.reloadCurrentTrackLyrics(true);
                }
            } else {
                showToast(res?.error || 'Не удалось сохранить текст', 'error');
            }
        })
        .catch(err => {
            console.error('Failed to save custom lyrics:', err);
            showToast(`Ошибка сохранения: ${err.message || err}`, 'error');
        });
}

function deleteCustomLyrics() {
    const track = getCurrentTrack();
    if (!track) {
        showToast('Трек не выбран', 'warning');
        return;
    }

    if (!window.pywebview?.api?.delete_custom_lyrics) {
        showToast('API удаления текста недоступно', 'error');
        return;
    }

    window.pywebview.api.delete_custom_lyrics(track)
        .then(res => {
            if (res && res.success) {
                showToast('Текст трека удалён, восстанавливаем автопоиск', 'info');
                closeLyricsCustomModal();
                if (window.NeDotify?.reloadCurrentTrackLyrics) {
                    window.NeDotify.reloadCurrentTrackLyrics(true);
                }
            } else {
                showToast(res?.error || 'Не удалось удалить текст', 'error');
            }
        })
        .catch(err => {
            console.error('Failed to delete custom lyrics:', err);
            showToast(`Ошибка удаления: ${err.message || err}`, 'error');
        });
}

export function initLyricsCustomModal() {
    if (modalInitialized) return;
    modalInitialized = true;

    const modal = document.getElementById('modal-custom-lyrics');
    if (!modal) return;

    const closeBtn = document.getElementById('btn-close-custom-lyrics');
    const cancelBtn = document.getElementById('btn-custom-lyrics-cancel');
    const previewBtn = document.getElementById('btn-custom-lyrics-preview-toggle');
    const deleteBtn = document.getElementById('btn-custom-lyrics-delete');
    const saveBtn = document.getElementById('btn-custom-lyrics-save');

    if (closeBtn) closeBtn.addEventListener('click', () => closeLyricsCustomModal());
    if (cancelBtn) cancelBtn.addEventListener('click', () => closeLyricsCustomModal());
    if (previewBtn) previewBtn.addEventListener('click', () => togglePreview());
    if (saveBtn) saveBtn.addEventListener('click', () => saveCustomLyrics());
    if (deleteBtn) deleteBtn.addEventListener('click', () => deleteCustomLyrics());

    // Close on backdrop click
    modal.addEventListener('click', (e) => {
        if (e.target === modal) {
            closeLyricsCustomModal();
        }
    });

    // Close on Escape
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && !modal.classList.contains('hidden')) {
            closeLyricsCustomModal();
        }
    });
}
