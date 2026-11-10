from types import SimpleNamespace

from audio.queue import PlaybackQueue
from tests.helpers import track, fetch


def test_personal_wave_returns_large_ranked_pool_and_excludes_current_queue(recommendations):
    candidates = [track(f'new{i}', f'Title {i}', f'Artist {i%30}', recommendation_relevance=.9)
                  for i in range(180)]
    recommendations._collect_candidates = lambda *a, **kw: candidates
    rows = fetch(recommendations.get_personal_wave, [], candidates[:20])
    assert len(rows) >= 60
    assert len({(t['artist'],t['title']) for t in rows}) == len(rows)
    assert not set(t['source_id'] for t in rows).intersection(t['source_id'] for t in candidates[:20])


def test_personal_wave_preserves_current_song_when_replacing_future():
    queue = PlaybackQueue()
    rows = [dict(title=str(i),entry_id=str(i),_personal_wave_session='wave') for i in range(80)]
    queue.set_tracks(rows, 4)
    playing = queue.current_track
    future = [dict(title=f'new{i}',entry_id=f'n{i}',_personal_wave_session='wave') for i in range(80)]
    assert queue.replace_personal_wave_tail(future,'wave','4')
    assert queue.current_track is playing
    assert queue.snapshot()['tracks'][:5] == rows[:5]
    assert len(queue.snapshot()['tracks']) == 85


def test_late_wave_response_cannot_replace_another_queue():
    queue = PlaybackQueue()
    queue.set_tracks([dict(title='Different playlist',entry_id='other')])
    assert not queue.replace_personal_wave_tail([{'title':'new'}],'wave','old')
    assert queue.current_track['title'] == 'Different playlist'


def test_new_dislike_is_applied_when_reranking_wave(recommendations):
    values = {'disliked_tracks': []}
    recommendations.settings = SimpleNamespace(get=lambda cat,key,default=None: values.get(key,default))
    candidates = [track(f'x{i}',f'Title {i}',f'Artist {i%30}',recommendation_relevance=.9) for i in range(100)]
    recommendations._collect_candidates = lambda *a,**kw: candidates
    first = fetch(recommendations.get_personal_wave, [])
    disliked = first[0]
    values['disliked_tracks'] = [{'artist':disliked['artist'],'title':disliked['title']}]
    next_rows = fetch(recommendations.get_personal_wave, [])
    assert not any(t['artist']==disliked['artist'] and t['title']==disliked['title'] for t in next_rows)
