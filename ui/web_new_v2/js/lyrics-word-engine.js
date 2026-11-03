// Shared by both Windows appearances. Only source-provided intervals are used.
export function normalizedTimedLines(data) {
    if (!data || !['word', 'syllable', 'line'].includes(data.syncType) || !Array.isArray(data.lines) || data.lines.length > 10000) return [];
    const lines = [];
    let previousStart = -1, count = 0;
    const rawLines = [...data.lines].sort((a, b) => (a?.startMs ?? 0) - (b?.startMs ?? 0));
    for (const line of rawLines) {
        let {startMs, endMs} = line || {};
        if (!Number.isFinite(startMs) || !Number.isFinite(endMs) || startMs < 0 || endMs < 0 || endMs > 86400000 || !Array.isArray(line.words)) return [];
        if (endMs < startMs) endMs = startMs;
        if (startMs < previousStart) startMs = previousStart;
        let wordStart = startMs;
        const words = [];
        for (const word of line.words) {
            if (++count > 100000 || typeof word?.text !== 'string' || !Number.isFinite(word.startMs) || !Number.isFinite(word.endMs) || word.startMs < 0 || word.endMs < 0) return [];
            const wStart = Math.max(wordStart, Math.max(startMs, Math.min(endMs, word.startMs)));
            const wEnd = Math.max(wStart, Math.min(endMs, word.endMs));
            words.push({...word, startMs: wStart, endMs: wEnd});
            wordStart = wStart;
        }
        previousStart = startMs;
        lines.push({timeMs: startMs, startMs, endMs, words, text: words.map(word => word.text).join('') || '♪'});
    }
    return lines;
}

export function wordProgress(word, positionMs, animation = 'standard') {
    if (positionMs < word.startMs) return 0;
    if (word.endMs <= word.startMs || positionMs >= word.endMs) return 1;
    if (animation === 'off' || animation === 'reduced') return 1;
    return Math.max(0, Math.min(1, (positionMs - word.startMs) / (word.endMs - word.startMs)));
}

// DOM references are built once per render. A steady frame touches only the
// active row(s); a seek also resets the previously active rows immediately.
export class WordPainter {
    constructor(lines) {
        this.lines = lines;
        this.previous = new Set();
        this.previousIndex = null;
        let end = 0;
        this.prefixEnd = lines.map(line => (end = Math.max(end, line.endMs)));
    }

    indexAt(positionMs) {
        let lo = 0, hi = this.lines.length;
        while (lo < hi) {
            const mid = (lo + hi) >> 1;
            if (this.lines[mid].startMs <= positionMs) lo = mid + 1;
            else hi = mid;
        }
        return lo - 1;
    }

    activeLines(positionMs) {
        const result = new Set();
        for (let i = this.indexAt(positionMs); i >= 0 && this.prefixEnd[i] >= positionMs; i--) {
            if (this.lines[i].endMs >= positionMs) result.add(i);
        }
        return result;
    }

    paint(rows, positionMs, animation = 'standard', force = false) {
        const active = this.activeLines(positionMs);
        const currentIndex = this.indexAt(positionMs);
        const changed = new Set(force ? this.lines.map((_, i) => i) : [...this.previous, ...active]);
        // Repaint crossed rows once at a discontinuity. Their inline fill can
        // otherwise survive a backwards seek after the .past class is removed.
        if (this.previousIndex !== null && this.previousIndex !== currentIndex) {
            for (let i = Math.max(0, Math.min(this.previousIndex, currentIndex)); i <= Math.max(this.previousIndex, currentIndex); i++) changed.add(i);
        }
        for (const index of changed) {
            const line = this.lines[index];
            for (const row of rows) {
                const elements = row[index] || [];
                for (let i = 0; i < elements.length; i++) {
                    const el = elements[i];
                    const progress = wordProgress(line.words[i], positionMs, animation);
                    const fill = `${(progress * 100).toFixed(2)}%`;
                    const state = positionMs < line.words[i].startMs ? 'upcoming' : (positionMs < line.words[i].endMs ? 'active' : 'past');
                    if (el._lyricsFill !== fill) { el.style.setProperty('--lyric-word-fill', fill); el._lyricsFill = fill; }
                    if (el.dataset.wordState !== state) el.dataset.wordState = state;
                }
            }
        }
        this.previous = active;
        this.previousIndex = currentIndex;
    }
}
