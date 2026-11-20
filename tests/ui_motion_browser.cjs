const {chromium}=require(process.env.PLAYWRIGHT_CORE_PATH || 'playwright');
const fs=require('node:fs'),path=require('node:path'),http=require('node:http'),assert=require('node:assert/strict');
const root=path.resolve(process.cwd(),'ui');
const server=http.createServer((req,res)=>{
 const pathname=new URL(req.url,'http://localhost').pathname;
 const file=path.resolve(root,pathname.startsWith('/MACos_ui/')?'.'+pathname:'web_new_v2/'+(pathname==='/'?'index.html':pathname.slice(1)));
 if(!file.startsWith(root+path.sep)||!fs.existsSync(file)||!fs.statSync(file).isFile()){res.writeHead(404);res.end();return;}
 let data=fs.readFileSync(file);
 if(file.endsWith('index.html'))data=data.toString().replace(/<script\b[^>]*>[\s\S]*?<\/script>/g,'').replace('</head>','<link rel="stylesheet" href="/MACos_ui/tokens.css"><link rel="stylesheet" href="/MACos_ui/interface.css"></head>');
 res.setHeader('Content-Type',{'.html':'text/html; charset=utf-8','.css':'text/css','.js':'text/javascript'}[path.extname(file)]||'application/octet-stream');res.end(data);
});
async function checkContentMotion(page) {
 const result = await page.evaluate(() => {
  const notice = document.createElement('div');
  notice.id = 'playlist-import-progress';
  notice.textContent = 'Импорт';
  document.body.append(notice);
  const panel = document.getElementById('panel');
  NeDotifyMotion.reveal(panel);
  NeDotifyMotion.reveal(panel);
  const reveals = panel.getAnimations().length;
  const drawer = document.createElement('aside');
  drawer.id = 'queue-drawer';
  drawer.className = 'open';
  const list = document.createElement('div');
  list.style.height = '120px';
  list.innerHTML = '<div data-motion-key="one" style="height:30px">One</div><div data-motion-key="two" style="height:30px">Two</div>';
  drawer.append(list);
  document.body.append(drawer);
  const before = NeDotifyMotion.listPositions(list);
  list.append(list.firstElementChild);
  NeDotifyMotion.settleList(list, before);
  const moved = list.firstElementChild.getAnimations().map(a => a.effect.getKeyframes()[0].translate);
  getComputedStyle(notice).opacity;
  notice.hidden = true;
  const clickThrough = getComputedStyle(notice).pointerEvents === 'none';
  const exit = notice.getAnimations().some(a => a.transitionProperty === 'display');
  return {reveals, moved, clickThrough, exit};
 });
 assert.deepEqual(result,{reveals:1,moved:['0px 30px'],clickThrough:true,exit:true});
 await page.waitForFunction(()=>getComputedStyle(document.getElementById('playlist-import-progress')).display==='none');
}
async function checkSurfaceMotion(page) {
 // The shell sheets are always linked, so these rules are live without loading
 // a deferred view pack: context menu, settings overlay and its card.
 const styles = await page.evaluate(() => {
  const prop = (selector) => getComputedStyle(document.querySelector(selector)).transitionProperty;
  const menu = document.querySelector('.context-menu');
  menu.classList.add('visible');
  const result = {
   menu: prop('.context-menu'),
   menuBehavior: getComputedStyle(menu).transitionBehavior,
   overlay: prop('#view-settings'),
   card: prop('#view-settings .settings-modal-card'),
  };
  menu.classList.remove('visible');
  result.closingPointer = getComputedStyle(menu).pointerEvents;
  result.exit = menu.getAnimations().some(a => a.transitionProperty === 'display');
  menu.classList.add('visible');
  return result;
 });
 assert.match(styles.menu, /display/);
 assert.match(styles.menuBehavior, /allow-discrete/);
 assert.match(styles.overlay, /opacity/);
 assert.match(styles.card, /transform/);
 assert.equal(styles.closingPointer, 'none');
 assert.equal(styles.exit, true);
 await page.emulateMedia({reducedMotion:'reduce'});
 assert.equal(await page.evaluate(() => getComputedStyle(document.querySelector('.context-menu')).transitionProperty), 'none');
 await page.emulateMedia({reducedMotion:'no-preference'});
 console.log('Context menu, settings overlay and card transitions verified');
}
(async()=>{await new Promise(r=>server.listen(0,'127.0.0.1',r));const browser=await chromium.launch({headless:true,executablePath:process.env.CHROME_PATH});try{const page=await browser.newPage({viewport:{width:1200,height:850}});await page.goto(`http://127.0.0.1:${server.address().port}/`);await page.addScriptTag({url:'/js/ui-motion.js'});await checkSurfaceMotion(page);await page.evaluate(()=>{document.getElementById('app-splash')?.remove();document.body.innerHTML='<button id="under">Under</button><dialog id="motion-test"><button id="dlg-btn">Close</button><div id="dlg-pane">Tab 1</div></dialog><section id="panel">Initial</section>';window.clicks=0;document.getElementById('under').onclick=()=>window.clicks++;});for(const skin of ['current','macos']){await page.evaluate(s=>document.documentElement.dataset.uiStyle=s,skin);await page.evaluate(()=>document.getElementById('motion-test').showModal());await page.waitForFunction(()=>getComputedStyle(document.getElementById('motion-test')).opacity==='1');await page.evaluate(()=>{const p=document.getElementById('dlg-pane');NeDotifyMotion.swap(p,()=>p.textContent='Tab 2');});const hitInsideDialog=await page.evaluate(()=>{const btn=document.getElementById('dlg-btn').getBoundingClientRect();const el=document.elementFromPoint(btn.left+2,btn.top+2);return el?el.id||el.tagName:'';});assert.ok(hitInsideDialog==='dlg-btn'||hitInsideDialog==='motion-test','dialog must remain visible during in-dialog panel swap');assert.equal(await page.locator('#dlg-pane').innerText(),'Tab 2');await page.evaluate(()=>document.getElementById('motion-test').close());assert.equal(await page.locator('#motion-test').evaluate(d=>d.open),false);await page.locator('#under').click();await page.waitForTimeout(260);assert.equal(await page.locator('#motion-test').evaluate(d=>getComputedStyle(d).display),'none');await page.evaluate(()=>{const d=document.getElementById('motion-test');d.showModal();d.close();d.showModal();});await page.waitForTimeout(280);assert.equal(await page.locator('#motion-test').evaluate(d=>d.open),true);await page.evaluate(()=>document.getElementById('motion-test').close());await page.waitForTimeout(260);await page.evaluate(()=>{const p=document.getElementById('panel');NeDotifyMotion.swap(p,()=>p.textContent='Old');NeDotifyMotion.swap(p,()=>p.textContent='Latest');});await page.waitForFunction(()=>document.getElementById('panel').textContent==='Latest'&&!document.getElementById('panel').style.viewTransitionName);await page.evaluate(()=>{const m=document.createElement('div');m.id='menu-test';m.textContent='Menu';document.body.append(m);window.retiring=m;NeDotifyMotion.remove(m);});assert.equal(await page.evaluate(()=>retiring.inert&&retiring.style.pointerEvents==='none'),true);await page.waitForTimeout(250);assert.equal(await page.evaluate(()=>retiring.isConnected),false);console.log(skin+': modal open/close, rapid reopening, nonblocking exit, latest tab and menu cleanup passed');}await checkContentMotion(page);await page.emulateMedia({reducedMotion:'reduce'});await page.evaluate(()=>{const p=document.getElementById('panel');NeDotifyMotion.swap(p,()=>p.textContent='Reduced');});assert.equal(await page.locator('#panel').innerText(),'Reduced');assert.equal(await page.locator('#panel').evaluate(p=>{NeDotifyMotion.reveal(p);return p.getAnimations().length}),0);console.log('Content reveal, queue reorder, banner exit and reduced motion passed');}finally{await browser.close();server.close();}})().catch(e=>{console.error(e);server.close();process.exitCode=1;});