const assert=require('node:assert/strict'),fs=require('node:fs'),http=require('node:http'),path=require('node:path');
const {chromium}=require('playwright');
const root=path.resolve(__dirname,'../ui');
const server=http.createServer((req,res)=>{
 const pathname=new URL(req.url,'http://localhost').pathname;
 if(pathname.startsWith('/test-cover')) {
  res.setHeader('Content-Type','image/svg+xml');
  if(pathname.endsWith('cors.svg'))res.setHeader('Access-Control-Allow-Origin','*');
  res.end('<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20"><rect width="20" height="20" fill="#2040e0"/></svg>');return;
 }
 const file=path.resolve(root,pathname.startsWith('/MACos_ui/')?'.'+pathname:'web_new_v2/'+(pathname==='/'?'index.html':pathname.slice(1)));
 if(!file.startsWith(root+path.sep)||!fs.existsSync(file)||!fs.statSync(file).isFile()){res.writeHead(404);res.end();return;}
 let data=fs.readFileSync(file);if(file.endsWith('index.html'))data=data.toString().replace(/<script\b[^>]*>[\s\S]*?<\/script>/g,'').replace('</head>','<link rel="stylesheet" href="/css/components/atmosphere-settings.css"><link rel="stylesheet" href="/MACos_ui/tokens.css"><link rel="stylesheet" href="/MACos_ui/interface.css"><link rel="stylesheet" href="/MACos_ui/settings.css"></head>');
 res.setHeader('Content-Type',{'.html':'text/html; charset=utf-8','.css':'text/css','.js':'text/javascript','.woff2':'font/woff2'}[path.extname(file)]||'application/octet-stream');res.end(data);
});
const covers=http.createServer((req,res)=>server.emit('request',req,res));
(async()=>{await new Promise(r=>covers.listen(0,'127.0.0.1',r));await new Promise(r=>server.listen(0,'127.0.0.1',r));const browser=await chromium.launch({headless:true});
try{const page=await browser.newPage();const errors=[];page.on('pageerror',e=>errors.push(e.message));
await page.goto(`http://127.0.0.1:${server.address().port}/`);
await page.evaluate(async()=>{document.getElementById('app-splash')?.remove();window.settings={theme:{},interface:{},optimization:{}};
window.awaitBridge=async()=>true;window.pywebview={api:{get_favorites:async()=>[1,2,3,4].map(id=>({id,cover_url:'data:image/svg+xml,'+encodeURIComponent(`<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20"><rect width="20" height="20" fill="red"/></svg>`)})),save_setting:async()=>true}};
window.utils=await import('/js/utils.js');window.atmosphere=await import('/js/home-atmosphere.js');
window.atmosphere.initHomeAtmosphere();document.body.append(document.getElementById('view-settings'));document.getElementById('view-settings').classList.add('active');});
await page.evaluate(() => {
 document.getElementById('view-settings').classList.remove('active');
 const home=document.getElementById('view-home');home.classList.add('active');
 home.innerHTML='<img class="test-cover" style="width:100px;height:100px" src="data:image/svg+xml,'+encodeURIComponent('<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20"><rect width="20" height="20" fill="#e04020"/></svg>')+'">';
 const avatar=home.querySelector('img').cloneNode();avatar.id='home-avatar-img';avatar.className='';avatar.src='data:image/svg+xml,'+encodeURIComponent('<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20"><rect width="20" height="20" fill="black"/></svg>');home.prepend(avatar);
 window.settings.theme.decorations_enabled=false;
 window.settings.theme.home_dynamic_background=false;
 document.dispatchEvent(new Event('nedotify:settings_applied'));
});
await page.waitForTimeout(600);
assert.equal(await page.locator('#home-color-atmosphere').count(),1,'cover atmosphere must automatically enable when wallpaper is off, including old saved opt-out');
assert.equal(await page.locator('#home-color-atmosphere span').first().evaluate(el=>el.style.backgroundColor),'rgb(224, 64, 32)');
for(const style of ['current','macos']) {
 await page.evaluate(style=>{document.documentElement.dataset.uiStyle=style;window.dispatchEvent(new Event('nedotify:appearance_changed'));},style);
 assert.equal(await page.locator('#home-color-atmosphere').count(),1);
}
for(const suffix of ['blocked.svg','cors.svg']) {
 await page.evaluate(url=>{document.querySelector('#view-home .test-cover').src=url;},`http://127.0.0.1:${covers.address().port}/test-cover-${suffix}`);
 await page.waitForTimeout(700);
 const surface=await page.locator('#home-color-atmosphere span').first().evaluate(el=>({color:el.style.backgroundColor,image:el.style.backgroundImage}));
 if(suffix==='cors.svg')assert.equal(surface.color,'rgb(32, 64, 224)');
 else assert.ok(surface.image.includes('blocked.svg'),'CORS-blocked covers must still tint the backdrop through the blurred original: '+JSON.stringify(surface));
}
await page.evaluate(()=>{document.documentElement.dataset.macosMode='dark';});
await page.waitForTimeout(2200);
await page.screenshot({path:'C:/Users/Артур/.codex/visualizations/2026/11/01/01a195ed-34ae-7921-9739-df311a05dcef/home-cover-atmosphere.png'});
await page.evaluate(()=>{window.settings.theme.decorations_enabled=true;document.dispatchEvent(new Event('nedotify:settings_applied'));});
assert.equal(await page.locator('#home-color-atmosphere').count(),0,'wallpaper and cover atmosphere must not overlap');
await page.evaluate(async()=>{window.settings.optimization.resource_bg=false;(await import('/js/settings.js')).applyResourceToggle('bg',false);});
assert.equal(await page.locator('#home-color-atmosphere').count(),1,'resource background toggle must immediately enable cover atmosphere');
await page.evaluate(async()=>{window.settings.optimization.resource_bg=true;(await import('/js/settings.js')).applyResourceToggle('bg',true);});
assert.equal(await page.locator('#home-color-atmosphere').count(),0);
console.log('PASS automatic cover atmosphere and extracted cover colors in both skins');
await page.evaluate(async()=>{
 window.searchCalls=[];window.pywebview.api.search=async(...args)=>window.searchCalls.push(args);
 window.searchModule=await import('/js/search.js');window.searchModule.initSearch();
 document.getElementById('view-home').classList.remove('active');document.getElementById('view-search').classList.add('active');
});
await page.locator('#search-input').fill('Artist');
assert.equal(await page.locator('#search-platform-btn').count(),0);
await page.locator('.type-filter-btn[data-type="tracks"]').click();
await page.waitForTimeout(400);
assert.deepEqual(await page.evaluate(()=>window.searchCalls.map(args=>args.slice(0,3))),[['Artist','all','tracks']]);
console.log('PASS switching category while typing issues one combined search');
await page.evaluate(async()=>{
 window.feature=await import('/js/feature-controls.js');
 window.longExplanation='Проверьте доступ к папке. '.repeat(40);
 window.feature.showOperationError({title:'Не удалось скачать трек',user_message:window.longExplanation,action:'retry',retry:async()=>{}});
});
assert.equal(await page.locator('.toast-message').textContent(),'Не удалось скачать трек','long explanations must not bloat the compact notification');
await page.getByRole('button',{name:'Подробнее',exact:true}).click();
assert.equal(await page.locator('.toast-details').textContent(),await page.evaluate(()=>window.longExplanation.trim()));
assert.ok(await page.locator('.toast-details').isVisible());
for(const style of ['current','macos'])for(const width of [360,600,1280]) {
 await page.setViewportSize({width,height:700});
 await page.evaluate(style=>{document.documentElement.dataset.uiStyle=style;document.documentElement.dataset.macosMode='dark';},style);
 const rect=await page.locator('.toast').boundingBox();assert.ok(rect.x>=0&&rect.x+rect.width<=width&&rect.height<=500,JSON.stringify({style,width,rect}));
}
await page.screenshot({path:'C:/Users/Артур/.codex/visualizations/2026/11/01/01a195ed-34ae-7921-9739-df311a05dcef/error-details.png'});
await page.locator('.toast-details').click();assert.equal(await page.locator('.toast').count(),1,'reading details must not dismiss notification');
await page.locator('.toast-close').click();await page.waitForTimeout(300);
assert.equal(await page.locator('.toast').count(),0);
console.log('PASS long error explanation can be read and dismissed in one notification');
assert.deepEqual(errors,[]);
}finally{await browser.close();server.close();covers.close();}})().catch(e=>{console.error(e);process.exitCode=1;});
