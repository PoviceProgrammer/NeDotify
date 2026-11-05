"""Linux transport regressions; shared layouts live in the desktop suites."""

from tests.jsdom import run_node, source


def test_posix_downloads_are_played_through_authorized_loopback_proxy():
    run_node(f"""
        import assert from 'node:assert/strict';
        const src = {source('player.js')};
        const fn = src.slice(src.indexOf('function normalizeAudioSourceUrl('),src.indexOf('function loadAudioSource('));
        globalThis.window = {{PROXY_PORT:54321,PROXY_TOKEN:'key with spaces'}};
        const normalize = new Function(`${{fn}};return normalizeAudioSourceUrl;`)();
        for (const file of ['/home/Музыка/песня #1.opus','file:///home/Music/a.ogg','C:\\\\Music\\\\a.mp3']) {{
            const url = new URL(normalize(file));
            assert.equal(url.origin,'http://127.0.0.1:54321');
            assert.equal(url.pathname,'/api/stream');
            assert.equal(url.searchParams.get('url'),file);
            assert.equal(url.searchParams.get('k'),'key with spaces');
        }}
        assert.equal(normalize('//network/track.mp3'),'');
        assert.equal(normalize('https://cdn.example/a.mp3'),'https://cdn.example/a.mp3');
    """)


def test_linux_system_media_controls_drive_real_transport_and_volume():
    run_node(f"""
        import assert from 'node:assert/strict';
        const src = {source('player.js')};
        const fn = src.slice(src.indexOf('export function handleSystemMedia('),src.indexOf('export function initPlayer(')).replace('export ','');
        globalThis.calls=[]; globalThis.fills=[]; const attributes=[];
        globalThis.document={{getElementById:()=>({{setAttribute:(...args)=>attributes.push(args)}})}};
        const {{handle,audioA,audioB,state}}=new Function(`
            const activeAudio={{paused:true,volume:.7}},audioA=activeAudio,audioB={{volume:.7}};
            let currentVolume=70,isMuted=true;
            const togglePlayPause=()=>{{activeAudio.paused=!activeAudio.paused;calls.push('toggle');}};
            const stopPlaybackForQueueEnd=()=>calls.push('stop'),onStateChanged=value=>calls.push(value);
            const seekTo=value=>calls.push(['seek',value]),playbackVolume=()=>isMuted?0:currentVolume/100;
            const setVolumeFill=(...args)=>fills.push(args),updateVolumeIcon=()=>{{}},scheduleVolumeRpc=(...args)=>calls.push(['volume',...args]);
            ${{fn}};
            return {{handle:handleSystemMedia,audioA,audioB,state:()=>({{currentVolume,isMuted}})}};` )();
        handle({{detail:{{action:'play'}}}}); handle({{detail:{{action:'play'}}}});
        assert.deepEqual(calls,['toggle']);
        handle({{detail:{{action:'pause'}}}}); handle({{detail:{{action:'pause'}}}});
        assert.deepEqual(calls,['toggle','toggle']);
        handle({{detail:{{action:'seek',value:12345}}}});
        assert.deepEqual(calls.at(-1),['seek',12345]);
        handle({{detail:{{action:'volume',value:150}}}});
        assert.equal(audioA.volume,1); assert.equal(audioB.volume,1); assert.equal(state().isMuted,false);
        assert.deepEqual(calls.at(-1),['volume',100,true]); assert.equal(fills.length,2);
        handle({{detail:{{action:'volume',value:NaN}}}}); assert.equal(state().currentVolume,100);
        handle({{detail:{{action:'stop'}}}}); assert.deepEqual(calls.slice(-2),['stop','stopped']);
    """)


def test_queue_button_has_one_owner_and_cover_preview_uses_http_route():
    run_node(f"""
        import assert from 'node:assert/strict';
        const player = {source('player.js')}; const queue = {source('queue.js')}; const utils = {source('utils.js')};
        assert.ok(!player.includes("const ppQueue = document.getElementById('pp-btn-queue')"));
        assert.ok(queue.includes("btnPP.addEventListener('click'"));
        assert.ok(player.includes("removeEventListener('nedotify:system_media', handleSystemMedia)"));
        assert.ok(utils.includes('coverImg.src = `./api/cover?path=${{encodeURIComponent(res.path)}}`'));
    """)


def test_titlebar_uses_native_compositor_drag_and_resize_failures_are_visible():
    run_node(f"""
        import assert from 'node:assert/strict';
        const src = {source('window-resize.js')};
        const events = new Map(), classes = new Set(['pywebview-drag-region']);
        const region = {{classList:{{remove:key=>classes.delete(key),add:key=>classes.add(key)}},addEventListener:(key,fn)=>events.set(key,fn)}};
        const handles=[]; const calls=[]; const errors=[];
        globalThis.document={{
            querySelectorAll:()=>[region],body:{{classList:{{contains:()=>false,add(){{}},remove(){{}}}},append(){{}}}},
            createElement:()=>{{const node={{setAttribute(){{}},dataset:{{}},append(handle){{handles.push(handle)}},addEventListener(key,fn){{this[key]=fn}},hasPointerCapture:()=>false}};return node;}},
        }};
        globalThis.window={{pywebview:{{api:{{}}}}}};
        window.pywebview.api.begin_window_drag=async()=>{{calls.push('drag');return {{success:true}}}};
        window.pywebview.api.maximize=()=>calls.push('maximize');
        window.pywebview.api.begin_window_resize=async direction=>{{calls.push(direction);return {{success:false}}}};
        const body=src.slice(src.indexOf('let initialized')).replace('export function','function');
        new Function('showToast', body+';initWindowResize();initWindowResize();')((...args)=>errors.push(args));
        assert.ok(!classes.has('pywebview-drag-region'));assert.ok(classes.has('linux-window-drag-region'));
        const pointer={{button:0,isPrimary:true,detail:1,target:{{closest:()=>null}},preventDefault(){{}},stopPropagation(){{}}}};
        await events.get('pointerdown')(pointer);assert.deepEqual(calls,['drag']);
        await events.get('pointerdown')({{...pointer,target:{{closest:()=>({{}})}}}});assert.deepEqual(calls,['drag']);
        events.get('dblclick')(pointer);assert.deepEqual(calls,['drag','maximize']);
        assert.equal(handles.length,8);
        await handles[0].pointerdown(pointer);assert.equal(calls.at(-1),'n');assert.equal(errors.length,1);
    """)
