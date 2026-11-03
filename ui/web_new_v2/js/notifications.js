// Notification queue adapted from Riff (MIT), rootscripts 2026.
// See licenses/RIFF_LICENSE.txt. Shared by early boot and ES modules.
(() => {
 if(window.NeDotifyToast)return;
 const queue=[];let active=null;
 function show(message,type='info',options={}){
  message=String(message||'').trim();if(!message)return;
  if(!['info','success','warning','error'].includes(type))type='info';
  if(type==='error'&&options.details)message='Не удалось выполнить действие';
  if(window.settings?.general?.show_notifications===false&&!['error','warning'].includes(type))return;
  const key=type+'|'+message+'|'+(options.details||'');
  if(active?.key===key||queue.some(item=>item.key===key))return;
  if(queue.length>=10)queue.shift();queue.push({message,type,options,key});next();
 }
 function next(){
  if(active||!queue.length)return;
  const container=document.getElementById('toast-container');if(!container)return;
  const modal=[...document.querySelectorAll('dialog:modal')].at(-1);
  const defaultHost=document.getElementById('notification-stack')||document.body;
  const host=modal||defaultHost;
  if(container.parentElement!==host)host.append(container);
  if(modal)modal.addEventListener('close',()=>{if(container.parentElement===modal)defaultHost.append(container);},{once:true});
  const item=queue.shift();active=item;
  const toast=document.createElement('div');toast.className='toast '+item.type;
  toast.dataset.message=item.message;toast.dataset.type=item.type;
  const icon=document.createElement('span');icon.className='toast-icon';icon.setAttribute('aria-hidden','true');
  const paths={success:'<path d="m5 12 5 5L20 7"/>',error:'<path d="M12 5v9m0 4v1"/>',warning:'<path d="m12 3 10 18H2Z M12 9v4m0 4h.01"/>',info:'<circle cx="12" cy="12" r="9"/><path d="M12 11v6m0-10h.01"/>'};
  icon.innerHTML='<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">'+paths[item.type]+'</svg>';
  const text=document.createElement('span');text.className='toast-message';text.textContent=item.message;
  toast.append(icon,text);
  let timer=null,remaining=item.type==='error'?4000:3500,started=0,paused=false,leaving=false;
  function dismiss(){
   if(leaving)return;leaving=true;clearTimeout(timer);toast.classList.add('toast-leaving');
   setTimeout(()=>{toast.remove();active=null;next();},200);
  }
  function resume(){if(leaving||toast.matches(':hover')||toast.contains(document.activeElement))return;clearTimeout(timer);paused=false;started=performance.now();timer=setTimeout(dismiss,remaining);}
  function pause(){if(paused||leaving)return;paused=true;clearTimeout(timer);remaining=Math.max(500,remaining-(performance.now()-started));}
  const close=document.createElement('button');close.type='button';close.className='toast-close';close.textContent='×';close.setAttribute('aria-label','Закрыть уведомление');close.onclick=dismiss;toast.append(close);
  toast.addEventListener('mouseenter',pause);toast.addEventListener('mouseleave',resume);toast.addEventListener('focusin',pause);toast.addEventListener('focusout',()=>setTimeout(resume,0));
  toast.addEventListener('click',event=>{if(!event.target.closest('button'))dismiss();});
  container.replaceChildren(toast);resume();
 }
 window.NeDotifyToast={show};
 if(!window.__nedotifyToastBridgeArmed){window.__nedotifyToastBridgeArmed=true;window.addEventListener('nedotify:toast',e=>{const d=e.detail||{};show(d.msg||d.message,d.type,d);});}
 document.addEventListener('DOMContentLoaded',next,{once:true});
})();
