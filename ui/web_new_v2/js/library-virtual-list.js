// Keep track objects and their logical indices outside the DOM. Spacers stand
// in for off-screen rows; the existing row factory still owns every action.
export function createLibraryVirtualList(container, tracks, { createRow, renderIcons }) {
    let parent = container.parentElement;
    while (parent && parent !== document.body && !/(auto|scroll)/.test(getComputedStyle(parent).overflowY)) parent = parent.parentElement;
    const scrollport = parent && parent !== document.body ? parent : document.scrollingElement;
    const mounted = new Map();
    const overscan = 8;
    let rowHeight = 52, gap = 0, listOffset = null;
    let frame = 0, disposed = false, needsMeasurement = true, focusTarget = null, draggedIndex = null;
    let observedRow = null;
    let signature = '';
    const oldAnchor = container.style.overflowAnchor;
    container.style.overflowAnchor = 'none';
    container.replaceChildren();

    const offset = () => {
        if (!scrollport) return 0;
        const top = scrollport === document.scrollingElement ? 0 : scrollport.getBoundingClientRect().top + scrollport.clientTop;
        return container.getBoundingClientRect().top - top + scrollport.scrollTop;
    };
    const rowFor = target => {
        const row = target?.closest?.('.lib-table-row');
        return row?.parentElement === container ? row : null;
    };
    const schedule = (measure = false) => {
        if (disposed) return;
        needsMeasurement ||= measure;
        if (!frame) frame = requestAnimationFrame(() => { frame = 0; update(); });
    };
    const resized = () => schedule(true);
    const resizeObserver = typeof ResizeObserver === 'function' ? new ResizeObserver(resized) : null;
    const mutationObserver = typeof MutationObserver === 'function' ? new MutationObserver(resized) : null;

    function reconcile(indices) {
        const nextSignature = `${tracks.length}:${rowHeight}:${gap}:${indices.join(',')}`;
        if (nextSignature === signature) return;
        signature = nextSignature;
        const wanted = new Set(indices);
        for (const [index, row] of mounted) {
            if (!wanted.has(index)) { row.remove(); mounted.delete(index); }
        }
        // Never detach retained rows: moving a focused button through a
        // DocumentFragment would blur it even if it returned in the same frame.
        container.querySelectorAll('.lib-virtual-spacer').forEach(spacer => spacer.remove());
        let cursor = container.firstChild, previous = -1;
        const inserted = [];
        const spacer = count => {
            if (!count) return;
            const node = document.createElement('div');
            node.className = 'lib-virtual-spacer';
            node.setAttribute('aria-hidden', 'true');
            // The flex container supplies a gap on both sides, just as it
            // would between real rows. Subtract the spacer's final inner gap.
            node.style.height = `${count * (rowHeight + gap) - gap}px`;
            container.insertBefore(node, cursor);
        };
        for (const index of indices) {
            spacer(index - previous - 1);
            let row = mounted.get(index);
            if (!row) {
                row = createRow(tracks[index], index, tracks);
                // Only a bounded visible window is mounted. Do not add the
                // browser's lazy-loading delay when recycling these covers.
                row.querySelectorAll('img').forEach(image => { image.loading = 'eager'; });
                row._trackIndex = index;
                mounted.set(index, row);
                container.insertBefore(row, cursor);
                inserted.push(row);
            } else {
                // Surviving rows already have their logical order.
                cursor = row.nextSibling;
            }
            previous = index;
        }
        spacer(tracks.length - previous - 1);
        inserted.forEach(row => renderIcons(row));
        const sample = mounted.values().next().value || null;
        if (sample !== observedRow) {
            if (observedRow) resizeObserver?.unobserve(observedRow);
            observedRow = sample;
            if (observedRow) resizeObserver?.observe(observedRow);
        }
    }

    function update() {
        if (disposed || !tracks.length) return;
        // The active page may be hidden behind another page or mini player.
        // Keep its geometry until ResizeObserver reports a visible scrollport.
        if (mounted.size && scrollport && !scrollport.clientHeight) return;
        const nextOffset = offset();
        let restoreScroll = null;
        const sample = mounted.values().next().value;
        if (needsMeasurement) {
            // Entrance transforms scale the painted rectangle without changing
            // layout. Measuring that rectangle would shrink every spacer and
            // stay stale after the animation (ResizeObserver sees no resize).
            const height = sample?.offsetHeight || sample?.getBoundingClientRect().height;
            const nextHeight = height > 0 ? height : rowHeight;
            const nextGap = Math.max(0, parseFloat(getComputedStyle(container).rowGap) || 0);
            if (listOffset !== null && scrollport && scrollport.scrollTop > listOffset) {
                const local = scrollport.scrollTop - listOffset;
                const index = Math.min(tracks.length - 1, Math.floor(local / (rowHeight + gap)));
                const within = local - index * (rowHeight + gap);
                // Preserve the row and pixel at the top when fonts, DPI, theme
                // or responsive hero geometry change above the list.
                restoreScroll = nextOffset + index * (nextHeight + nextGap) + Math.min(within, nextHeight + nextGap);
            }
            rowHeight = nextHeight;
            gap = nextGap;
            needsMeasurement = false;
        }
        listOffset = nextOffset;
        const local = (restoreScroll ?? scrollport?.scrollTop ?? 0) - nextOffset;
        const viewport = scrollport?.clientHeight || 600;
        const start = Math.min(tracks.length - 1, Math.max(0, Math.floor(local / (rowHeight + gap)) - overscan));
        const end = Math.min(tracks.length, Math.max(start + 1, Math.ceil((local + viewport) / (rowHeight + gap)) + overscan));
        const indices = new Set();
        // Small playlists cost little to retain and must never expose a recycled
        // blank window during compositor scrolling. Large collections stay bounded.
        const retainAll = tracks.length <= 100;
        for (let index = retainAll ? 0 : start; index < (retainAll ? tracks.length : end); index++) indices.add(index);
        for (const pinned of [rowFor(document.activeElement)?._trackIndex, draggedIndex, focusTarget]) {
            if (Number.isInteger(pinned) && pinned >= 0 && pinned < tracks.length) indices.add(pinned);
        }
        reconcile([...indices].sort((a, b) => a - b));
        // New spacer dimensions must exist before restoring a position near
        // the end; assigning earlier would clamp against the old scrollHeight.
        if (restoreScroll !== null && Math.abs(scrollport.scrollTop - restoreScroll) > 0.1) scrollport.scrollTop = restoreScroll;
        // The first real row gives us the effective CSS height, including any
        // user styling. One correction happens synchronously before first paint.
        if (sample || !observedRow) return;
        const actual = observedRow.offsetHeight || observedRow.getBoundingClientRect().height;
        if (actual > 0 && Math.abs(actual - rowHeight) > 0.1) { needsMeasurement = true; update(); }
    }

    function focusRow(index, last) {
        focusTarget = index;
        update();
        const row = mounted.get(index);
        const controls = focusable(row);
        (last ? controls.at(-1) || row : row)?.focus();
        focusTarget = null;
        schedule();
    }
    function focusable(row) {
        return row ? [row, ...row.querySelectorAll('button,a[href],input,select,textarea,[tabindex]')].filter(node => node.tabIndex >= 0 && !node.disabled && node.getClientRects().length) : [];
    }
    const keydown = event => {
        if (event.key !== 'Tab' || event.ctrlKey || event.metaKey || event.altKey) return;
        const row = rowFor(event.target);
        if (!row) return;
        const index = row._trackIndex, controls = focusable(row);
        if (!event.shiftKey && event.target === controls.at(-1) && index + 1 < tracks.length) {
            event.preventDefault(); focusRow(index + 1, false);
        } else if (event.shiftKey && event.target === controls[0] && index > 0) {
            event.preventDefault(); focusRow(index - 1, true);
        }
    };
    const onScroll = () => {
        // A scrollbar jump can expose an entirely unmounted range. Reconcile
        // within this event instead of showing spacers until the next RAF.
        if (frame) { cancelAnimationFrame(frame); frame = 0; }
        update();
    };
    const onFocus = () => schedule();
    const dragStart = event => { draggedIndex = rowFor(event.target)?._trackIndex ?? null; };
    const dragEnd = () => { draggedIndex = null; schedule(); };
    scrollport?.addEventListener('scroll', onScroll, { passive: true });
    container.addEventListener('keydown', keydown);
    container.addEventListener('focusin', onFocus);
    container.addEventListener('focusout', onFocus);
    container.addEventListener('dragstart', dragStart);
    document.addEventListener('dragend', dragEnd);
    document.addEventListener('drop', dragEnd);
    window.addEventListener('resize', resized);
    document.fonts?.addEventListener('loadingdone', resized);
    resizeObserver?.observe(container);
    if (scrollport) resizeObserver?.observe(scrollport);
    mutationObserver?.observe(document.documentElement, { attributes: true });
    mutationObserver?.observe(document.body, { attributes: true });
    update();

    return {
        // Track arrays grow only when the explicit "show more" request returns.
        renderNext: () => { update(); return tracks.length; },
        destroy() {
            disposed = true;
            if (frame) cancelAnimationFrame(frame);
            scrollport?.removeEventListener('scroll', onScroll);
            container.removeEventListener('keydown', keydown);
            container.removeEventListener('focusin', onFocus);
            container.removeEventListener('focusout', onFocus);
            container.removeEventListener('dragstart', dragStart);
            document.removeEventListener('dragend', dragEnd);
            document.removeEventListener('drop', dragEnd);
            window.removeEventListener('resize', resized);
            document.fonts?.removeEventListener('loadingdone', resized);
            resizeObserver?.disconnect(); mutationObserver?.disconnect();
            container.style.overflowAnchor = oldAnchor;
        },
    };
}
