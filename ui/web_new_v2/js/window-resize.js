import { showToast } from './utils.js';

let initialized=false;
export function initWindowResize() {
    if(initialized)return;initialized=true;
    const layer=document.createElement('div');layer.id='window-resize-handles';layer.setAttribute('aria-hidden','true');
    for(const direction of ['n','s','w','e','nw','ne','sw','se']){
        const handle=document.createElement('div');handle.className=`window-resize-handle resize-${direction}`;handle.dataset.resizeDirection=direction;
        handle.addEventListener('pointerdown',async event=>{
            if(event.button!==0 || !event.isPrimary || document.body.classList.contains('mini-player-active'))return;
            const resize=window.pywebview?.api?.begin_window_resize;if(typeof resize!=='function')return;
            event.preventDefault();event.stopPropagation();
            // Do not hold DOM pointer capture: Windows owns the sizing loop.
            if(handle.hasPointerCapture(event.pointerId))handle.releasePointerCapture(event.pointerId);
            document.body.classList.add('window-resizing');
            try {await resize(direction);}catch {showToast('Не удалось изменить размер окна','error');}
            finally {document.body.classList.remove('window-resizing');}
        });
        layer.append(handle);
    }
    document.body.append(layer);
}
