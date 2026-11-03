"""Deterministic IPC recovery without a real Discord client or user account."""
import asyncio
import threading
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import core.services.discord_rpc as module
from core.services.discord_rpc import DiscordRPCService, public_cover_url, public_track_url


class Clock:
    def __init__(self): self.value=100.
    def __call__(self): return self.value
    def advance(self, seconds): self.value+=seconds


class Settings:
    def __init__(self, **options): self.values={'discord_rpc_enabled':True, **options}
    def get(self, category, key, default=None): return self.values.get(key,default)


class Client:
    def __init__(self, *args, **kwargs):
        self.loop=kwargs.get('loop'); self.calls=[]; self.failure=None; self.closed=False
    def connect(self): self.calls.append(('connect',None))
    def update(self, **payload):
        if self.failure:
            error,self.failure=self.failure,None
            raise error
        self.calls.append(('update',payload))
    def clear(self): self.calls.append(('clear',None))
    def close(self): self.closed=True; self.calls.append(('close',None))


@pytest.fixture
def rpc(monkeypatch):
    clock=Clock(); service=DiscordRPCService(Settings(),clock=clock,wall_clock=lambda:10000,jitter=lambda:.5)
    clients=[]
    def factory(*args,**kwargs):
        client=Client(*args,**kwargs);clients.append(client);return client
    monkeypatch.setattr(module,'_load_presence',lambda:factory)
    monkeypatch.setattr(service,'start',lambda **kwargs:None)
    service._active=True
    yield service,clock,clients
    service.stop();service._run_cycle()


def track(name='First', **extra):
    return {'id':name,'title':name,'artist':'Artist','source':'youtube','source_id':'dQw4w9WgXcQ','duration':180,**extra}


def payload(client): return [value for method,value in client.calls if method=='update'][-1]


def test_connect_restores_latest_track_after_ready_and_uses_current_position(rpc):
    service,clock,clients=rpc
    service.update_snapshot(track(), 'playing',30,180)
    latest={'track':track('Latest'),'state':'playing','position_sec':70,'duration_sec':180,'playback_rate':1,'updated_at':clock()}
    service.set_snapshot_provider(lambda:latest)
    service._run_cycle()
    assert service.state=='CONNECTED'
    assert payload(clients[0])['details']=='Latest'
    assert payload(clients[0])['end']==10110
    assert payload(clients[0])['buttons'][0]['url']=='https://www.youtube.com/watch?v=dQw4w9WgXcQ'


def test_pause_resume_seek_rate_and_unknown_duration(rpc):
    service,clock,clients=rpc
    service.update_snapshot(track(), 'playing',20,180);service._run_cycle()
    service.update_snapshot(track(), 'paused',30,180);clock.advance(2);service._run_cycle()
    assert 'end' not in payload(clients[0]);assert 'На паузе' in payload(clients[0])['state']
    service.update_snapshot(track(), 'playing',100,180,2);clock.advance(2);service._run_cycle()
    assert payload(clients[0])['end']==10038
    assert len(clients)==1, 'seek/resume must reuse the connected IPC client'
    service.update_snapshot(track(duration=0), 'playing',30,0);clock.advance(2);service._run_cycle()
    assert 'end' not in payload(clients[0])
    service.update_snapshot(state='stopped');clock.advance(2);service._run_cycle()
    assert clients[0].calls[-1][0]=='clear'


def test_late_discord_start_disconnect_and_bounded_recovery_use_latest_snapshot(rpc, monkeypatch):
    service,clock,clients=rpc
    original=module._load_presence
    monkeypatch.setattr(module,'_load_presence',lambda:lambda *a,**kw:(_ for _ in ()).throw(ConnectionRefusedError()))
    service.update_snapshot(track(),'playing',0,180);service._run_cycle()
    assert service.state=='RECONNECTING';assert service._retry_at==115
    monkeypatch.setattr(module,'_load_presence',original)
    service.update_snapshot(track('Second'),'playing',50,180)
    service._run_cycle();assert not clients
    clock.advance(15);service._run_cycle();assert payload(clients[0])['details']=='Second'
    clients[0].failure=BrokenPipeError();clock.advance(15);service._run_cycle()
    assert not service.connected;assert clients[0].closed
    service.update_snapshot(track('Third'),'paused',40,180);clock.advance(15);service._run_cycle()
    assert len(clients)==2;assert payload(clients[1])['details']=='Third';assert 'end' not in payload(clients[1])


def test_invalid_assets_fallback_without_reconnect_and_options_refresh(rpc):
    service,clock,clients=rpc
    service.update_snapshot(track(cover_url='https://i.ytimg.com/vi/dQw4w9WgXcQ/hqdefault.jpg'),'playing',0,180)
    service._run_cycle();assert payload(clients[0])['large_image'].startswith('https://')
    ServerError=type('ServerError',(Exception,),{})
    clients[0].failure=ServerError('Invalid image');clock.advance(2);service.refresh();service._run_cycle()
    assert service.connected;assert len(clients)==1
    assert 'large_image' not in payload(clients[0]);assert 'buttons' not in payload(clients[0])
    service.settings.values.update(discord_show_cover=False,discord_show_time=False,discord_show_listen=False,discord_show_artist=False)
    service.refresh();clock.advance(2);service._run_cycle()
    result=payload(clients[0]);assert result['large_image']=='aura_logo'
    assert not any(key in result for key in ('end','buttons','state'))


def test_stop_cancels_pending_reconnect_and_clear_closes_connection(rpc):
    service,clock,clients=rpc
    service.update_snapshot(track(),'playing',0,180);service._run_cycle()
    service.stop();service._run_cycle()
    assert service.state=='DISABLED';assert service._retry_at==0
    assert clients[0].calls[-2:]==[('clear',None),('close',None)]
    service.update_snapshot(track('After shutdown'),'playing',0,180)
    clock.advance(100);service._run_cycle();assert len(clients)==1


@pytest.mark.parametrize('url', ['http://youtube.com/watch?v=dQw4w9WgXcQ','https://localhost/track/a',
    'file:///C:/secret.mp3','https://127.0.0.1/api/stream','https://soundcloud.com/a/b?token=secret'])
def test_private_urls_never_become_listen_buttons(url):
    assert public_track_url({'source':'local','url':url}) is None
    assert public_cover_url(url) is None


def test_worker_does_not_block_callers_or_spin_on_snapshot_provider(monkeypatch):
    calls=[];ready=threading.Event();closed=threading.Event()
    class WorkerClient(Client):
        def connect(self): ready.set();return super().connect()
        def close(self): closed.set();super().close()
    monkeypatch.setattr(module,'_load_presence',lambda:WorkerClient)
    service=DiscordRPCService(Settings())
    def provider():
        calls.append(1)
        return {'track':track(),'state':'playing','position_sec':0,'duration_sec':180}
    service.set_snapshot_provider(provider);service.start()
    try:
        assert ready.wait(1)
        # A self-waking worker would invoke this thousands of times immediately.
        assert not closed.wait(.05)
        assert len(calls)<=4
        service.update_snapshot(track('Latest'),'paused',60,180)
    finally:
        service.shutdown()
    assert closed.is_set();assert service._worker is None


def test_whole_ready_handshake_is_timeout_bounded():
    service=DiscordRPCService(Settings());service.IO_TIMEOUT=.01
    class Hanging:
        async def handshake(self): await asyncio.Event().wait()
    client=Hanging();service._bound_io(client)
    with pytest.raises(TimeoutError): asyncio.run(client.handshake())


@pytest.mark.parametrize('consent',[False,None,'false','true',1])
def test_no_ipc_without_explicit_boolean_consent(monkeypatch,consent):
    lookup=Mock(side_effect=AssertionError('IPC without consent'))
    monkeypatch.setattr(module,'_load_presence',lookup)
    service=DiscordRPCService(Settings(discord_rpc_enabled=consent))
    service.update_snapshot(track(),'playing',20,180);service.start()
    assert service.state=='DISABLED';assert service._worker is None
    lookup.assert_not_called()


def test_payload_uses_real_pypresence_serializer_without_ipc(rpc):
    from pypresence import Presence
    service,clock,clients=rpc
    service.update_snapshot(track(),'playing',20,180)
    result=service._payload(service._snapshot)
    assert result['activity_type'].value == 2
    sent=[]
    async def response():return {'ok':True}
    loop=asyncio.new_event_loop()
    client=SimpleNamespace(loop=loop,read_output=response,send_data=lambda *args:sent.append(args))
    try:
        assert Presence.update(client,**result)=={'ok':True}
        assert len(sent)==1
    finally:
        loop.close()


def test_api_rpc_settings_refresh_status_and_close_ignores_legacy_tray(api, core_ns, monkeypatch):
    service=SimpleNamespace(stop=Mock(),start=Mock(),refresh=Mock(),get_status=lambda:{'state':'CONNECTED','connected':True,'enabled':True})
    core_ns.discord_rpc=service
    assert api.get_discord_rpc_status()['state']=='CONNECTED'
    assert api.save_setting('discord_show_cover',False,'app')
    service.refresh.assert_called_once()
    assert api.save_setting('discord_show_cover','false','app') is False
    window=SimpleNamespace(destroy=Mock(),hide=Mock());api._window=window
    core_ns.settings.set('general','minimize_to_tray',True)
    class ImmediateTimer:
        daemon=False
        def __init__(self,delay,fn):self.fn=fn
        def start(self):self.fn()
    monkeypatch.setattr('core.api.threading.Timer',ImmediateTimer)
    monkeypatch.setattr(api,'flush_listening',lambda:None)
    assert api.close_window()['success'];assert api.close_window()['success']
    window.destroy.assert_called_once();window.hide.assert_not_called();service.stop.assert_called_once()


def test_outgoing_crossfade_deck_cannot_replace_selected_rpc_state(api,core_ns):
    service=SimpleNamespace(update_snapshot=Mock(),set_snapshot_provider=Mock())
    core_ns.discord_rpc=service
    api._active_listening_token='selected-deck'
    api._current_track=track('Incoming')
    api._discord_sync('playing',position_sec=12)
    original=dict(api._discord_facts)
    assert api.report_state('paused',45000,listening_session='outgoing-deck') is False
    assert api.report_position(50000,180000,listening_session='outgoing-deck') is False
    assert api._discord_facts==original
    assert service.update_snapshot.call_count==1
