from tests.jsdom import run_node, source


def test_volume_pointer_accepts_own_track_and_drag():
    run_node(r'''
    import vm from 'node:vm';
    import assert from 'node:assert/strict';
    const src=SOURCE;
    const listeners={}, docListeners={}, calls=[];
    const track={addEventListener:(k,f)=>listeners[k]=f,removeEventListener(){},focus(){},
      getBoundingClientRect:()=>({left:10,width:100}),setAttribute(){},removeAttribute(){},
      setPointerCapture(){},hasPointerCapture:()=>false};
    const ctx=vm.createContext({document:{getElementById:()=>track,
      addEventListener:(k,f)=>docListeners[k]=f,removeEventListener(){}},
      window:{addEventListener(){},removeEventListener(){}},playbackState:{},isDraggingProgress:false});
    vm.runInContext(src.slice(src.indexOf('function setupDragBar('),src.indexOf('\nfunction api(method,')),ctx);
    ctx.setupDragBar('pb-volume-track',{onDrag:v=>calls.push(v),onRelease:v=>calls.push(v)});
    const event={pointerId:1,button:0,clientX:35,target:{closest:selector=>selector.includes('.volume-track')?track:null},preventDefault(){}};
    listeners.pointerdown(event);
    assert.equal(calls[0],.25,'click must change volume');
    docListeners.pointermove({...event,clientX:85});assert.equal(calls.at(-1),.75);
    docListeners.pointerup({...event,clientX:110});assert.equal(calls.at(-1),1);
    '''.replace('SOURCE', source('player.js')))


def test_riff_playback_modes_and_invalid_persisted_settings():
    run_node(r'''
    import assert from 'node:assert/strict';
    const {AUDIO_DEFAULTS,normalizeAudioTools,audioPlayback}=await import('data:text/javascript;base64,'+Buffer.from(SOURCE).toString('base64'));
    assert.deepEqual(audioPlayback({speed:1.5}),{rate:1.5,preservesPitch:true});
    assert.deepEqual(audioPlayback({speed:1.5,linkedSpeed:1.25,pitch:12}),{rate:2.5,preservesPitch:false});
    assert.deepEqual(audioPlayback({linkedSpeed:.5,pitch:-12}),{rate:.25,preservesPitch:false});
    for(const invalid of [null,[],42,{}, {speed:null,volume:'',pitch:false}])assert.deepEqual(normalizeAudioTools(invalid),AUDIO_DEFAULTS);
    const bounded=normalizeAudioTools({speed:-8,pitch:50,volume:Infinity,echo:120,engine:'unknown',hqEnabled:'true'});
    assert.equal(bounded.speed,.5);assert.equal(bounded.pitch,12);assert.equal(bounded.volume,1);
    assert.equal(bounded.echo,100);assert.equal(bounded.engine,'hqmusic-3');assert.equal(bounded.hqEnabled,false);
    '''.replace('SOURCE',source('audio-effects.js')))


def test_artist_catalog_continues_past_100_and_retains_remasters_and_remixes():
    from types import SimpleNamespace
    from services.artist_service import ArtistService
    calls=[]
    def playlist(browse_id, limit):
        calls.append(limit)
        return {'tracks':[{'videoId':str(i),'title':f'Song {i}','artists':[{'name':'Artist','id':'channel'}]} for i in range(130)] + [
            {'videoId':'master','title':'Song (2025 Remastered)','artists':[{'name':'Artist','id':'channel'}]},
            {'videoId':'radio','title':'Song (Radio Edit)','artists':[{'name':'Artist','id':'channel'}]},
            {'videoId':'original','title':'Remix','artists':[{'name':'Artist','id':'channel'}]},
            {'videoId':'remix','title':'Song (Club Remix)','artists':[{'name':'Artist','id':'channel'}]},
            {'videoId':'homonym','title':'Song','artists':[{'name':'Artist','id':'other-channel'}]}]}
    yt=SimpleNamespace(get_playlist=playlist)
    service=ArtistService(yt,settings=None)
    service.catalog._call=lambda fn,*args:fn()
    tracks=service._collect_tracks(yt,'channel',{'songs':{'browseId':'playlist'}},'Artist')
    assert calls == [None]
    assert len(tracks) == 134
    ids={track['source_id'] for track in tracks}
    assert {'master','radio','original','remix'} <= ids
    assert 'homonym' not in ids


def test_queue_history_uses_actual_navigation_instead_of_preceding_rows():
    from audio.queue import PlaybackQueue
    queue=PlaybackQueue()
    queue.set_tracks([{'id':i} for i in range(4)])
    queue.jump_to(2)
    assert all(track['id'] != 1 for track in queue.snapshot()['history'])
    queue.next_track()
    assert queue.snapshot()['history'][-1]['id'] == 2


def test_favorite_artwork_fetch_can_limit_rows_without_truncating_the_library(tmp_db):
    for i in range(8):
        track_id=tmp_db.add_track(title=f'Song {i}',artist='Artist',source='local',source_id=str(i))
        tmp_db.toggle_favorite(track_id)
    assert len(tmp_db.get_favorite_tracks(limit=4)) == 4
    assert len(tmp_db.get_favorite_tracks()) == 8


def test_artist_album_page_keeps_cursor_on_failure_and_filters_homonyms(monkeypatch):
    from types import SimpleNamespace
    from services.artist_service import ArtistService
    service=ArtistService(SimpleNamespace(),settings=None)
    albums=[{'source_id':str(i),'title':f'Album {i}'} for i in range(6)]
    monkeypatch.setattr(service,'_cache_get',lambda key:{'name':'Artist','albums':albums})
    def album(sid):
        if sid=='4':raise ConnectionError('offline')
        return {'tracks':[
            {'videoId':'valid'+sid,'title':'Song '+sid,'artists':[{'name':'Artist','id':'channel'}]},
            {'videoId':'wrong','title':'Wrong','artists':[{'name':'Artist','id':'other'}]},
            {'videoId':'remix','title':'Song (Remix)','artists':[{'name':'Artist','id':'channel'}]},
            {'videoId':'master'+sid,'title':'Song (Remastered)','artists':[{'name':'Artist','id':'channel'}]}]}
    yt=SimpleNamespace(get_album=album)
    monkeypatch.setattr(service,'_ytmusic',lambda:yt)
    monkeypatch.setattr(service.catalog,'_call',lambda fn,*args:fn())
    page=service.get_tracks_page({'source':'youtube','source_id':'channel'},3)
    assert page['next_offset']==4
    assert page['has_more'] is True
    assert page['retryable'] is True
    assert {t['source_id'] for t in page['tracks']}=={'valid3','master3','remix'}
    yt.get_album=lambda sid:{'tracks':[{'videoId':'new'+sid,'title':'Next '+sid,'artists':[{'name':'Artist','id':'channel'}]}]}
    page=service.get_tracks_page({'source':'youtube','source_id':'channel'},page['next_offset'])
    assert page['next_offset']==6 and not page['has_more']
    assert [t['source_id'] for t in page['tracks']]==['new4','new5']


def test_itunes_album_page_uses_recording_ids_and_excludes_other_artists(monkeypatch):
    from types import SimpleNamespace
    from services.artist_service import ArtistService
    service=ArtistService(SimpleNamespace(),settings=None)
    monkeypatch.setattr(service,'_cache_get',lambda key:{'name':'Artist','albums':[{'source_id':str(i)} for i in range(5)]})
    def lookup(url,**kwargs):
        assert 'id=4&' in url and 'entity=song' in url
        return {'results':[
            {'wrapperType':'track','kind':'song','artistId':77,'trackId':901,'trackName':'Original'},
            {'wrapperType':'track','kind':'song','artistId':77,'trackId':902,'trackName':'Original (Remastered)'},
            {'wrapperType':'track','kind':'song','artistId':77,'trackId':903,'trackName':'Original (DJ Remix)'},
            {'wrapperType':'track','kind':'song','artistId':88,'trackId':904,'trackName':'Homonym'}]}
    monkeypatch.setattr('services.artist_service.ITunesGateway.get',lookup)
    page=service.get_tracks_page({'source':'itunes','source_id':'77'},4)
    assert [t['id'] for t in page['tracks']]==['spotify_901','spotify_902','spotify_903']
    assert not page['has_more']
