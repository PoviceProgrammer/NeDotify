"""Exercise the integrated queue, real output containers, leases and metadata."""
import base64
from contextlib import contextmanager
import json
import os
from pathlib import Path
import shutil
from types import SimpleNamespace

import pytest

from core.download_processing import OutputPolicy, process_download, safe_filename, fetch_cover
from core.download_transfer import DownloadContext, DownloadInterrupted
from tests.audio_helpers import wave_bytes


def test_source_output_embeds_metadata_and_cover_without_ffmpeg(tmp_path, monkeypatch):
    from mutagen.wave import WAVE
    path = tmp_path / 'native.wav'
    path.write_bytes(wave_bytes())
    ctx = DownloadContext(1, 'youtube', 'video', lambda: None, lambda *a: None)
    ctx.tools = {}
    monkeypatch.setattr('core.download_processing.run_tool', lambda *a, **k: pytest.fail('source audio must not transcode'))
    cover = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aOZkAAAAASUVORK5CYII=')
    track = dict(id=1, title='Song', artist='Artist', album='Album', year=2026, track_number=2, genre='Rock', source='youtube', source_id='video')
    final, warnings = process_download(str(path), track, OutputPolicy(), ctx, str(tmp_path), (cover,'image/png'))
    audio = WAVE(final)
    assert audio.tags['TIT2'].text == ['Song']
    assert audio.tags['TPE1'].text == ['Artist']
    assert audio.tags['TALB'].text == ['Album']
    assert audio.tags['TRCK'].text == ['2']
    assert audio.tags['TXXX:SOURCE'].text == ['youtube:video']
    assert audio.tags.getall('APIC')[0].data == cover
    assert not warnings
    assert path.read_bytes() == wave_bytes(), 'A pre-existing external file must not be edited/moved'


def test_library_cover_url_is_used_for_embedded_artwork():
    encoded = 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aOZkAAAAASUVORK5CYII='
    result = fetch_cover({'cover_url': 'data:image/png;base64,' + encoded}, lambda: None)
    assert result == (base64.b64decode(encoded), 'image/png')


@pytest.mark.parametrize('fmt', ['mp3','m4a','opus','flac','wav'])
def test_actual_output_container_and_tags(tmp_path, fmt):
    ffmpeg = shutil.which('ffmpeg')
    if not ffmpeg:
        pytest.skip('Real ffmpeg unavailable; output conversion is unverified')
    from mutagen import File
    ctx = DownloadContext(1, 'fixture', 'native', lambda: None, lambda *a: None)
    ctx.tools = {'ffmpeg_path': ffmpeg}
    source = tmp_path / (ctx.stem + '.wav')
    source.write_bytes(wave_bytes())
    result, warnings = process_download(str(source), {'id':1,'title':'Fixture','artist':'Artist'}, OutputPolicy(format=fmt), ctx, str(tmp_path))
    assert Path(result).suffix == '.' + fmt
    assert File(result).info.length > 0
    assert not warnings


def test_lossy_source_is_not_falsely_promoted_to_flac(tmp_path):
    ctx = DownloadContext(1, 'youtube', 'id', lambda: None, lambda *a: None)
    source = tmp_path / (ctx.stem + '.mp3')
    source.write_bytes(wave_bytes())
    with pytest.raises(ValueError, match='lossless'):
        process_download(str(source), {'id':1}, OutputPolicy(format='flac'), ctx, str(tmp_path))
    assert not list(tmp_path.glob('*.flac'))


def test_existing_correct_tags_are_not_replaced_with_empty_or_wrong_metadata(tmp_path):
    from mutagen.wave import WAVE
    from mutagen.id3 import TIT2
    ctx = DownloadContext(1, 'fixture', 'native', lambda: None, lambda *a: None)
    source = tmp_path / (ctx.stem + '.wav')
    source.write_bytes(wave_bytes())
    audio = WAVE(source)
    audio.add_tags()
    audio.tags.add(TIT2(encoding=3,text='Verified title'))
    audio.save()
    final, _ = process_download(str(source), {'id':1,'title':'Other title','artist':''}, OutputPolicy(), ctx, str(tmp_path))
    assert WAVE(final).tags['TIT2'].text == ['Verified title']


def test_windows_filenames_are_safe_and_identity_prevents_title_collisions():
    one = safe_filename({'title':'CON', 'artist':'A:/\\?*"<>|\x00'}, 1)
    assert not any(ch in one for ch in '<>:"/\\|?*\x00')
    assert one != safe_filename({'title':'CON', 'artist':'A:/\\?*"<>|\x00'}, 2)
    assert safe_filename({'title':'NUL'}, 1).startswith('_')


def test_artwork_wait_is_deferred_until_after_audio_conversion(tmp_path, monkeypatch):
    """Cover IO and conversion overlap; tags still receive the finished cover."""
    order = []
    ctx = DownloadContext(1, 'fixture', 'native', lambda: None, lambda *a: None)
    ctx.tools = {'ffmpeg_path': 'fixture-ffmpeg'}
    source = tmp_path / (ctx.stem + '.wav')
    source.write_bytes(wave_bytes())
    cover_data = (b'cover', 'image/jpeg')
    def convert(args, *unused, **kw):
        order.append('convert')
        # Keep this test about scheduling, not FFmpeg codec availability.
        Path(args[-1]).write_bytes(wave_bytes())
    def cover():
        order.append('cover')
        return cover_data
    def tags(path, track, artwork):
        assert artwork == cover_data
        order.append('tags')
    monkeypatch.setattr('core.download_processing.run_tool', convert)
    monkeypatch.setattr('core.download_processing.embed_tags', tags)
    process_download(str(source), {'id': 1}, OutputPolicy(format='mp3'), ctx, str(tmp_path), cover)
    assert order == ['convert', 'cover', 'tags']


def test_queue_captures_quality_and_destination_and_cancel_is_per_track(downloader, tmp_db, core_ns, tmp_path):
    core_ns.settings.set('downloads', 'format', 'opus')
    core_ns.settings.set('downloads', 'directory', str(tmp_path))
    ids = [tmp_db.add_track(title=str(n),source='youtube',source_id=str(n)) for n in range(2)]
    for track_id in ids:
        assert downloader.queue_download(track_id,'youtube',str(track_id))
    before = downloader.get_downloads()
    assert len({row['job_id'] for row in before}) == 2
    saved = json.loads(before[0]['options'])
    assert saved['format'] == 'opus' and saved['directory'] == str(tmp_path)
    assert downloader.cancel_download(ids[0]) == {'success':True,'count':1}
    assert tmp_db.download_queue_get_status(ids[0]) == 'cancelled'
    assert tmp_db.download_queue_get_status(ids[1]) == 'pending'
    assert downloader.retry_download(ids[0])['count'] == 1


def test_tool_lease_spans_provider_and_postprocessing(downloader, tmp_db, core_ns, monkeypatch, redirect_home):
    leased = []
    @contextmanager
    def lease(**options):
        leased.append(True)
        try:
            yield {'yt_dlp_module':True}
        finally:
            leased.pop()
    core_ns.setup = SimpleNamespace(acquire_download_tools=lease)
    track_id = tmp_db.add_track(title='Lease',source='youtube',source_id='lease')
    downloader.queue_download(track_id,'youtube','lease')
    def provider(_id, folder, download_context=None):
        assert leased
        path = Path(folder) / (download_context.stem + '.wav')
        path.write_bytes(wave_bytes())
        return str(path)
    original = __import__('core.downloader',fromlist=['process_download']).process_download
    def process(*args,**kwargs):
        assert leased
        return original(*args,**kwargs)
    core_ns.youtube.download_audio_sync = provider
    monkeypatch.setattr('core.downloader.process_download',process)
    downloader._download_worker(downloader._queue.pop(0))
    assert not leased
    assert tmp_db.download_queue_get_status(track_id) == 'completed'


def test_complete_hashed_audio_cache_skips_provider(downloader, tmp_db, core_ns, monkeypatch, redirect_home):
    from utils.cache_manager import stream_cache_stem
    track_id = tmp_db.add_track(title='Cached',source='youtube',source_id='cached')
    folder = redirect_home / '.nedotify' / 'streams'
    folder.mkdir(parents=True)
    cached = folder / (stream_cache_stem('youtube','cached') + '.wav')
    cached.write_bytes(wave_bytes())
    monkeypatch.setattr(tmp_db,'get_cached_stream',lambda *a,**k:{'cached_file_path':str(cached)})
    core_ns.youtube.download_audio_sync = lambda *a,**k:pytest.fail('Complete cache should avoid provider IO')
    downloader.queue_download(track_id,'youtube','cached')
    downloader._download_worker(downloader._queue.pop(0))
    assert tmp_db.get_track(track_id)['is_downloaded']
    assert cached.read_bytes() == wave_bytes()


def test_missing_component_failure_has_recovery_action(downloader,tmp_db,core_ns,emitted):
    from core.setup_engine import SetupDependencyError
    @contextmanager
    def lease(**options):
        raise SetupDependencyError('missing_ffmpeg','Восстановите FFmpeg')
        yield
    core_ns.setup = SimpleNamespace(acquire_download_tools=lease)
    track_id = tmp_db.add_track(title='Missing',source='youtube',source_id='missing')
    downloader.queue_download(track_id,'youtube','missing')
    downloader._download_worker(downloader._queue.pop(0))
    failure = next(data for name,data in emitted if name=='download_failed')
    assert failure['code'] == 'missing_ffmpeg' and failure['action'] == 'setup'
    assert not tmp_db.get_track(track_id)['is_downloaded']


def test_download_error_storage_redacts_signed_media_urls(downloader,tmp_db,core_ns):
    track_id = tmp_db.add_track(title='Failure',source='youtube',source_id='failure')
    core_ns.youtube.download_audio_sync = lambda *a,**k:(_ for _ in ()).throw(RuntimeError('Provider error https://cdn.example/file?token=SECRET cookie=COOKIE'))
    downloader.queue_download(track_id,'youtube','failure')
    downloader._download_worker(downloader._queue.pop(0))
    error = downloader.get_downloads()[0]['error']
    assert 'SECRET' not in error and 'COOKIE' not in error


def test_missing_completed_file_can_be_downloaded_again(downloader,tmp_db,tmp_path):
    track_id=tmp_db.add_track(title='Missing file',source='youtube',source_id='missing-file')
    tmp_db.download_queue_add(track_id,'youtube','missing-file')
    tmp_db.download_queue_set_status(track_id,'completed')
    tmp_db.mark_track_downloaded(track_id,str(tmp_path/'gone.mp3'))
    assert downloader.queue_download(track_id,'youtube','missing-file')
    assert tmp_db.download_queue_get_status(track_id)=='pending'


def test_cli_fallback_uses_verified_tool_and_reports_real_progress(tmp_path,monkeypatch):
    progress=[]
    ctx=DownloadContext(1,'youtube','fixture',lambda:None,lambda done,total:progress.append((done,total)))
    ctx.tools={'yt_dlp_path':'C:/fixture/verified-yt-dlp.exe','ffmpeg_path':'C:/fixture/ffmpeg.exe'}
    output=tmp_path/(ctx.stem+'_fixture.m4a')
    def execute(args,checkpoint,timeout,on_line):
        assert args[0]=='C:/fixture/verified-yt-dlp.exe'
        assert '--no-check-certificates' not in args
        assert '--no-playlist' in args
        assert args[-2:]==['--','https://www.youtube.com/watch?v=fixture']
        on_line('nd-progress:1024:2048')
        output.write_bytes(b'fixture')
        on_line('nd-file:'+str(output))
    monkeypatch.setattr('core.download_processing.run_tool',execute)
    assert ctx.download_executable('https://www.youtube.com/watch?v=fixture',str(tmp_path))==str(output)
    assert progress==[(1024,2048)]


def test_transcoding_process_is_terminated_on_cancel(tmp_path):
    import sys
    from core.download_processing import run_tool
    checks=[]
    def cancel():
        checks.append(1)
        if len(checks)>1:
            raise DownloadInterrupted()
    with pytest.raises(DownloadInterrupted):
        run_tool([sys.executable,'-c','import time;time.sleep(30)'],cancel,timeout=3)
    assert len(checks)==2
