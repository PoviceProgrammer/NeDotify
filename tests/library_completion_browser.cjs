// Real Chromium + shipped library modules, with an isolated in-memory bridge.
// NODE_PATH must point at the bundled runtime's node_modules; no user data.
const {chromium} = require('playwright');
const {readFileSync, existsSync, statSync} = require('node:fs');
const {resolve, extname, sep} = require('node:path');
const http = require('node:http');
const assert = require('node:assert/strict');
const root = resolve(__dirname, '..', 'ui');
const styles = [
  '/css/components/library-refresh.css', '/css/components/downloads-view.css',
  '/css/components/smart-playlists.css', '/MACos_ui/tokens.css',
  '/MACos_ui/interface.css', '/MACos_ui/library.css',
];
const server = http.createServer((req, res) => {
  const pathname = decodeURIComponent(new URL(req.url, 'http://localhost').pathname);
  const path = resolve(root, pathname.startsWith('/MACos_ui/') ? '.' + pathname : 'web_new_v2/' + (pathname === '/' ? 'index.html' : pathname.slice(1)));
  if (!path.startsWith(root + sep) || !existsSync(path) || !statSync(path).isFile()) {res.writeHead(404);res.end();return;}
  let data = readFileSync(path);
  if (path.endsWith('index.html')) data = data.toString().replace(/<script\b[^>]*>[\s\S]*?<\/script>/g, '')
    .replace('</head>', styles.map(href => `<link rel="stylesheet" href="${href}">`).join('') + '</head>');
  res.setHeader('Content-Type', ({'.html':'text/html','.css':'text/css','.js':'text/javascript','.svg':'image/svg+xml','.woff2':'font/woff2','.png':'image/png'})[extname(path)] || 'application/octet-stream');
  res.end(data);
});

async function initialize(page, style, width) {
  await page.setViewportSize({width, height:1000});
  await page.goto(`http://127.0.0.1:${server.address().port}`);
  await page.addScriptTag({url:'/js/lucide.min.js'});
  await page.evaluate(async style => {
    document.documentElement.dataset.uiStyle = style;
    document.documentElement.dataset.macosMode = 'dark';
    document.getElementById('app-splash')?.remove();
    document.querySelectorAll('.view-page').forEach(view => view.classList.remove('active'));
    document.getElementById('view-library').classList.add('active');
    window.awaitBridge = async () => {};
    window.settings = {};
    window.showPage = () => {};
    const tracks = [1,2,3].map(id => ({id, source:'youtube', source_id:'fixture'+id,
      title:'Fixture song '+id, artist:'Artist '+id, duration:120, is_favorite:id===1,
      is_downloaded:id===2, file_path:id===2?'C:/fixture/untouched.wav':'', added_at:'2026-10-29T09:00:00Z'}));
    let playlists = [1,2,3].map(id => ({id,name:'Collection '+id,track_count:1}));
    const members = new Map([[1,[1]],[2,[2]],[3,[3]]]);
    const smart = [{id:10,name:'Smart saved',rule:{favorite:true,sort:'newest'}}];
    const calls = [];
    const clone = value => structuredClone(value);
    const listing = () => playlists.map(p => ({...p,track_count:(members.get(p.id)||[]).length}));
    window.libraryFixture = {tracks, members, calls, playlists:()=>playlists};
    window.pywebview = {api:{
      get_library:async(limit=8,offset=0)=>({tracks:clone(tracks.slice(offset,offset+limit)),total:tracks.length}),
      get_library_summary:async()=>({favorite_count:1,favorite_ids:[1],downloaded_count:1}),
      get_favorites:async()=>clone(tracks.filter(t=>t.is_favorite)),
      get_downloaded_tracks:async()=>clone(tracks.filter(t=>t.is_downloaded)),
      get_playlists:async()=>clone(listing()),
      get_playlist_tracks:async id=>clone(tracks.filter(t=>(members.get(Number(id))||[]).includes(t.id))),
      create_playlist:async name=>{calls.push(['create-attempt']);if(libraryFixture.rejectCreate)return null;await new Promise(r=>setTimeout(r,40));const id=Math.max(0,...playlists.map(p=>p.id))+1;playlists.push({id,name});members.set(id,[]);calls.push(['create',id]);return id;},
      rename_playlist:async(id,name)=>{playlists.find(p=>p.id===Number(id)).name=name;calls.push(['rename',id]);return {success:true};},
      delete_playlist:async id=>{playlists=playlists.filter(p=>p.id!==Number(id));members.delete(Number(id));calls.push(['delete',id]);return {success:true};},
      add_to_playlist:async(id,track)=>{const ids=members.get(Number(id));if(!ids.includes(track.id))ids.push(track.id);calls.push(['add',id,track.id]);return {success:true};},
      remove_from_playlist:async(id,tid)=>{members.set(Number(id),(members.get(Number(id))||[]).filter(t=>t!==Number(tid)));calls.push(['remove',id,tid]);return {success:true};},
      open_local_file:async()=>{calls.push(['import-local']);return {cancelled:true};},
      import_external_playlist:async()=>{calls.push(['import-link']);return {success:true,count:0,name:'Imported'};},
      get_storage_info:async()=>({}), get_downloads:async()=>[],
      get_smart_playlists:async()=>clone(smart),
      get_smart_playlist_tracks:async()=>clone(tracks.filter(t=>t.is_favorite)),
      create_smart_playlist:async(name,rule)=>{const pl={id:11,name,rule};smart.push(pl);calls.push(['create-smart']);return {success:true,playlist:clone(pl)};},
      play_track:async()=>true, toggle_shuffle:async()=>true,
      download_all_favorites:async()=>({success:true,count:1}),
      download_playlist:async()=>({success:true,count:1}),
    }};
    window.libraryModule = await import('/js/library.js');
    window.downloadModule = await import('/js/downloads-view.js');
    libraryModule.initLibrary();
    downloadModule.initDownloadManagerView(document.getElementById('lib-download-manager'));
    await libraryModule.loadLibrary();
    window.lucide.createIcons();
  }, style);
  await page.locator('#lib-overview-collections [data-collection-id="3"]').waitFor();
}

(async()=>{
  await new Promise(done=>server.listen(0,'127.0.0.1',done));
  const browser = await chromium.launch({headless:true, ...(process.env.CHROME_PATH?{executablePath:process.env.CHROME_PATH}:{})});
  try {
    const page = await browser.newPage();
    const errors=[];page.on('pageerror',error=>errors.push(String(error)));
    await page.route(/https?:\/\/(?!127\.0\.0\.1)/,route=>route.abort());
    page.setDefaultTimeout(5000);
    for (const style of ['current','macos']) for (const width of [600,900,1280]) {
      errors.length=0;
      await initialize(page,style,width);
      assert.equal(await page.locator('#lib-overview-collections .lib-collection-card').count(),3,'all playlist covers should render');
      assert.equal(await page.locator('.lib-left-sidebar').isVisible(),false,'no internal management sidebar');
      for (const id of ['lib-card-favorites','lib-card-offline']) {
        const box = await page.locator('#'+id).boundingBox();
        assert.ok(box && box.height<=80,`${style}/${width}: compact tabs ${id} ${JSON.stringify(box)}`);
      }
      const columns = await page.locator('#lib-overview-collections').evaluate(el=>getComputedStyle(el).gridTemplateColumns.split(' ').length);
      assert.ok(columns>=2,`${style}/${width}: covers must form a grid`);
      await page.locator('[data-library-trigger="lib-btn-import"]').click();
      assert.equal(await page.evaluate(()=>libraryFixture.calls.some(c=>c[0]==='import-local')),true,'import remains reachable');
      await page.locator('[data-library-trigger="lib-btn-convert"]').click();
      assert.equal(await page.locator('#modal-import-playlist').isVisible(),true,'link import remains reachable');
      await page.locator('#modal-ip-cancel').click();
      const downloads=page.locator('#lib-download-manager summary');
      await downloads.click();
      assert.equal(await page.locator('#lib-download-manager [data-action="refresh"]').isVisible(),true,'download controls remain reachable');
      await page.locator('#lib-download-manager [data-action="refresh"]').click();

      await page.locator('#lib-overview-collections .lib-collection-create').click();
      await page.evaluate(()=>{libraryFixture.rejectCreate=true;});
      await page.locator('#modal-cp-input').fill('Rejected by backend');
      await page.locator('#modal-cp-submit').click();
      await page.waitForFunction(()=>!document.getElementById('modal-cp-submit').disabled);
      assert.equal(await page.locator('#modal-create-playlist').isVisible(),true,'failed creation must keep the editor open');
      await page.evaluate(()=>{libraryFixture.rejectCreate=false;});
      await page.locator('#modal-cp-input').fill('Created from grid');
      await page.locator('#modal-cp-input').evaluate(input=>{
        input.dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',bubbles:true}));
        input.dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',bubbles:true}));
      });
      await page.locator('#lib-overview-collections [data-collection-id="4"]').waitFor();
      assert.equal(await page.evaluate(()=>libraryFixture.calls.filter(c=>c[0]==='create-attempt').length),2,'repeated Enter must share the pending create');
      const card = page.locator('#lib-overview-collections [data-collection-id="4"]');
      await card.hover();await card.locator('.lib-collection-menu').click();
      await page.locator('#lib-playlist-actions [data-action="rename"]').click();
      await page.locator('#lib-rename-name').fill('Renamed collection');
      await page.locator('.lib-rename-form [type="submit"]').click();
      await page.waitForFunction(()=>document.querySelector('#lib-overview-collections [data-collection-id="4"] strong')?.textContent==='Renamed collection');
      await page.evaluate(()=>libraryModule.openPlaylistMenu(libraryFixture.tracks[1],200,180));
      await page.locator('#playlist-menu-items button').filter({hasText:'Renamed collection'}).click();
      await card.locator('.lib-collection-open').click();
      await page.locator('#lib-active-tracks .lib-remove-track').waitFor();
      await page.locator('#lib-active-tracks .lib-remove-track').click();
      await page.waitForFunction(()=>document.querySelector('#lib-active-tracks')?.textContent.includes('В этом плейлисте пока нет треков'));
      assert.equal(await page.evaluate(()=>libraryFixture.tracks.length),3,'membership removal preserves tracks');
      assert.equal(await page.evaluate(()=>libraryFixture.tracks[1].file_path),'C:/fixture/untouched.wav','membership removal preserves the file');
      await page.locator('#lib-btn-playlist-options').click();
      await page.locator('#lib-playlist-actions [data-action="delete"]').click();
      await page.locator('#modal-dpl-confirm').click();
      await page.waitForFunction(()=>!document.querySelector('#lib-overview-collections [data-collection-id="4"]'));
      assert.equal(await page.evaluate(()=>libraryFixture.tracks.length),3,'playlist deletion preserves tracks');

      await page.locator('#lib-card-favorites').click();
      await page.waitForFunction(()=>document.getElementById('lib-active-title').textContent==='Любимые треки');
      assert.equal(await page.locator('#lib-active-tracks .track-item').count(),1);
      await page.locator('#lib-card-offline').click();
      await page.waitForFunction(()=>document.getElementById('lib-active-title').textContent==='Офлайн треки');
      assert.equal(await page.locator('#lib-active-tracks .track-item').count(),1);
      await page.locator('[data-library-trigger="lib-btn-overview"]').click();
      await page.locator('#lib-smart-list .lib-smart-open').first().click();
      await page.waitForFunction(()=>document.getElementById('lib-active-title').textContent==='Smart saved');
      assert.equal(await page.locator('#lib-active-tracks .lib-remove-track').count(),0,'computed collections have no manual membership removal');
      await page.locator('#lib-btn-smart-create').click();
      await page.locator('.lib-smart-dialog input[name="name"]').fill('New smart');
      await page.locator('.lib-smart-dialog [type="submit"]').click();
      await page.waitForFunction(()=>document.getElementById('lib-active-title').textContent==='New smart');
      await page.locator('[data-library-trigger="lib-btn-overview"]').click();
      await page.locator('#lib-collection-filter').fill('Collection 2');
      assert.equal(await page.locator('#lib-overview-collections .lib-collection-card').count(),1,'playlist search filters full grid');
      assert.deepEqual(errors,[],`no uncaught UI errors: ${style}/${width}`);
      console.log(`PASS library CRUD/membership/imports/downloads/smart/grid ${style} ${width}`);
    }
  } finally {await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;}).finally(()=>server.close());
