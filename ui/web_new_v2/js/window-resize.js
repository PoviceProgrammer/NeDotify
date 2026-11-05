import { showToast } from './utils.js';

let initialized=false;
export function initWindowResize() {
    if(initialized)return;initialized=true;
    // Compositor-owned gestures work on Wayland, where arbitrary window.move()
    // calls are forbidden. Remove pywebview's programmatic drag selector first
    // so its document listener cannot compete with the native gesture.
    document.querySelectorAll('.pywebview-drag-region').forEach(region => {
        region.classList.remove('pywebview-drag-region');
        region.classList.add('linux-window-drag-region');
        region.addEventListener('pointerdown', async event => {
            if (event.button !== 0 || !event.isPrimary || event.detail > 1 || event.target.closest('button, input, select, textarea, a, [role="button"]')) return;
            const drag = window.pywebview?.api?.begin_window_drag;
            if (typeof drag !== 'function') return;
            event.preventDefault();
            event.stopPropagation();
            try {
                const result = await drag();
                if (result?.success === false) throw new Error('Native dragging unavailable');
            } catch { showToast('Не удалось переместить окно', 'error'); }
        });
        region.addEventListener('dblclick', event => {
            if (event.button !== 0) return;
            event.preventDefault();
            window.pywebview?.api?.maximize?.();
        });
    });
    const layer=document.createElement('div');layer.id='window-resize-handles';layer.setAttribute('aria-hidden','true');
    for(const direction of ['n','s','w','e','nw','ne','sw','se']){
        const handle=document.createElement('div');handle.className=`window-resize-handle resize-${direction}`;handle.dataset.resizeDirection=direction;
        handle.addEventListener('pointerdown',async event=>{
            if(event.button!==0 || !event.isPrimary || document.body.classList.contains('mini-player-active'))return;
            const resize=window.pywebview?.api?.begin_window_resize;if(typeof resize!=='function')return;
            event.preventDefault();event.stopPropagation();
            // The compositor owns the sizing loop; do not hold DOM capture.
            if(handle.hasPointerCapture(event.pointerId))handle.releasePointerCapture(event.pointerId);
            document.body.classList.add('window-resizing');
            try {
                const result = await resize(direction);
                if (result?.success === false) throw new Error('Native resizing unavailable');
            } catch {showToast('Не удалось изменить размер окна','error');}
            finally {document.body.classList.remove('window-resizing');}
        });
        layer.append(handle);
    }
    document.body.append(layer);
}
