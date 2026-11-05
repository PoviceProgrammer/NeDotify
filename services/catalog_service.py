"""Catalogue identities and genuine album details, without synthetic results."""
import atexit
import concurrent.futures
import copy
import threading
import time
import urllib.parse

from services.base_service import BaseMusicService
from services.artist_identity import artist_aliases, artist_binding, canonical_artist, name_key
from services.music_matching import artist_matches, similarity
from services.itunes_gateway import ITunesGateway, CatalogueUnavailable
from services.lyrics_translit import alt_script_artist

_catalog_pool = concurrent.futures.ThreadPoolExecutor(max_workers=4, thread_name_prefix='Catalogue')
atexit.register(lambda: _catalog_pool.shutdown(wait=False, cancel_futures=True))


def credited_to(item, artist_name, channel_id='', settings=None):
    people = item.get('artists') or []
    ids = [str(p.get('id') or p.get('browseId')) for p in people if isinstance(p, dict) and (p.get('id') or p.get('browseId'))]
    if channel_id and ids:
        return channel_id in ids
    return artist_matches(artist_name, people, settings)


class CatalogService(BaseMusicService):
    def __init__(self, youtube_service=None, settings=None):
        super().__init__()
        self.youtube = youtube_service
        self.settings = settings
        self._results = {}
        self._flights = {}
        self._deezer = None

    def _deezer_get(self, path, **params):
        from services.deezer_service import DeezerService
        with self._cache_lock:
            if self._deezer is None:
                self._deezer = DeezerService(settings=self.settings)
            service = self._deezer
        return service._get(path, **params)

    def _call(self, fn, deadline, is_current=lambda: True):
        if not is_current() or time.monotonic() >= deadline:
            raise CatalogueUnavailable('Истёк срок запроса')
        future = _catalog_pool.submit(lambda: fn() if is_current() else (_ for _ in ()).throw(CatalogueUnavailable('Запрос устарел')))
        try:
            return future.result(timeout=max(0.01, deadline - time.monotonic()))
        except concurrent.futures.TimeoutError as exc:
            future.cancel()
            raise CatalogueUnavailable('Каталог не ответил вовремя') from exc

    def _cached(self, key, fetch, deadline):
        with self._cache_lock:
            hit = self._results.get(key)
            if hit and hit[0] > time.monotonic():
                return copy.deepcopy(hit[1])
            flight = self._flights.get(key)
            owner = flight is None
            if owner:
                flight = {'event': threading.Event()}
                self._flights[key] = flight
        if not owner:
            if not flight['event'].wait(max(0, deadline - time.monotonic())):
                return {'status': 'unavailable', 'error': 'Каталог не ответил вовремя'}
            return copy.deepcopy(flight['result'])
        try:
            result = fetch()
            result = copy.deepcopy(result)
            if not isinstance(result, dict):
                raise ValueError('Некорректный ответ каталога')
        except Exception as exc:
            result = {'status': 'unavailable', 'error': str(exc)}
        try:
            with self._cache_lock:
                if result.get('status') in ('found', 'not_found'):
                    self._results[key] = (time.monotonic() + (900 if result['status'] == 'found' else 60), result)
                    while len(self._results) > 128:
                        self._results.pop(next(iter(self._results)))
                flight['result'] = result
        finally:
            with self._cache_lock:
                flight.setdefault('result', {'status': 'unavailable'})
                self._flights.pop(key, None)
                flight['event'].set()
        return copy.deepcopy(result)

    def _artist_candidates(self, name, deadline, is_current, include_deezer=False):
        yt = getattr(self.youtube, '_ytmusic', None)
        hits, failed = [], False
        names_to_try = [name]
        alt = alt_script_artist(name)
        if alt and alt.strip().lower() != name.strip().lower() and alt not in names_to_try:
            names_to_try.append(alt)

        # A stalled primary catalogue must leave time for the public iTunes
        # fallback. Share this sub-budget across both script spellings.
        now = time.monotonic()
        youtube_deadline = min(deadline, now + min(3.0, max(0, deadline - now) * .4))
        for q in names_to_try:
            if time.monotonic() >= youtube_deadline or not is_current():
                break
            if yt:
                try:
                    for h in self._call(lambda q=q: yt.search(q, filter='artists', limit=8), youtube_deadline, is_current) or []:
                        sid, title = h.get('browseId'), h.get('artist') or h.get('name')
                        if sid and title:
                            thumbs = h.get('thumbnails') or []
                            hits.append({'name': title, 'source': 'youtube', 'source_id': str(sid),
                                         'avatar_url': thumbs[-1].get('url', '') if thumbs else '',
                                         'subscribers': h.get('subscribers') or ''})
                except Exception:
                    failed = True
            else:
                failed = True

        if not hits and time.monotonic() < deadline and is_current():
            # Preserve a final catalogue attempt when iTunes stalls too.
            itunes_deadline = min(deadline, time.monotonic() + 2)
            for q in names_to_try:
                if time.monotonic() >= itunes_deadline or not is_current():
                    break
                try:
                    url = 'https://itunes.apple.com/search?' + urllib.parse.urlencode({'term': q, 'entity': 'musicArtist', 'media': 'music', 'limit': 8})
                    data = ITunesGateway.get(url, deadline=itunes_deadline, is_current=is_current, settings=self.settings)
                    for h in data.get('results', []):
                        if h.get('artistId') and h.get('artistName'):
                            hits.append({'name': h['artistName'], 'source': 'itunes', 'source_id': str(h['artistId']), 'genres': h.get('primaryGenreName', '')})
                    if hits:
                        failed = False
                except Exception:
                    failed = True
        if (not hits or (include_deezer and any(hit['source'] == 'itunes' for hit in hits))) and time.monotonic() < deadline and is_current():
            try:
                data = self._call(lambda: self._deezer_get('search/artist', q=name, limit=8), deadline, is_current)
                for item in data.get('data', []):
                    sid = str(item.get('id') or '')
                    if item.get('type') == 'artist' and sid.isdecimal() and int(sid) > 0 and item.get('name'):
                        hits.append({'name': item['name'], 'type': 'artist', 'source': 'deezer', 'source_id': sid,
                                     'avatar_url': item.get('picture_xl') or item.get('picture_big') or item.get('picture') or ''})
                failed = False
            except Exception:
                # Retain a definitive empty result from a working primary;
                # a failed optional fallback does not invalidate that result.
                pass
        unique = {(h['source'], h['source_id']): h for h in hits}
        return list(unique.values()), failed

    def resolve_artist(self, name, artist_ref=None, is_current=lambda: True, _deadline=None):
        deadline = _deadline if _deadline is not None else time.monotonic() + 8
        ref = artist_ref if isinstance(artist_ref, dict) else {}
        context = ref.get('context')
        saved = artist_binding(self.settings, name, context)
        explicit = bool(ref.get('source_id'))
        if not explicit and saved:
            ids = saved.get('catalog_ids') or {}
            source = next((s for s in ('youtube', 'itunes', 'deezer') if ids.get(s)), None)
            if source:
                ref = {'source': source, 'source_id': str(ids[source]), 'name': saved.get('canonical_name')}
        key = ('artist', name_key(name), repr(ref), repr(artist_aliases(self.settings)))

        def fetch():
            if ref.get('source_id'):
                source, sid = ref.get('source', 'youtube'), str(ref['source_id'])
                if source == 'youtube':
                    yt = getattr(self.youtube, '_ytmusic', None)
                    if not yt:
                        raise CatalogueUnavailable('YouTube Music недоступен')
                    try:
                        raw = self._call(lambda: yt.get_artist(sid), deadline, is_current)
                    except Exception as exc:
                        if getattr(getattr(exc, 'response', None), 'status_code', None) == 404 or getattr(exc, 'code', None) == 404:
                            raw = None
                        else:
                            raise
                    if not isinstance(raw, dict) or not raw.get('name'):
                        candidates, _ = self._artist_candidates(name, deadline, is_current)
                        return {'status': 'ambiguous' if candidates else 'not_found', 'binding_missing': bool(saved), 'candidates': candidates}
                    return {'status': 'found', 'name': raw['name'], 'source': source, 'source_id': sid, 'profile_data': raw}
                if source == 'itunes' and sid.isdigit():
                    url = f'https://itunes.apple.com/lookup?id={sid}&entity=album&limit=200'
                    data = ITunesGateway.get(url, deadline=deadline, is_current=is_current, settings=self.settings)
                    record = next((h for h in data['results'] if str(h.get('artistId')) == sid and h.get('wrapperType') == 'artist'), None)
                    if not record:
                        return {'status': 'not_found', 'binding_missing': bool(saved)}
                    return {'status': 'found', 'name': record['artistName'], 'source': source, 'source_id': sid, 'profile_data': data}
                if source == 'deezer' and sid.isascii() and sid.isdecimal() and int(sid) > 0:
                    raw = self._call(lambda: self._deezer_get('artist/' + sid), deadline, is_current)
                    if raw.get('type') != 'artist' or str(raw.get('id')) != sid or not raw.get('name'):
                        return {'status': 'not_found'}
                    return {'status': 'found', 'name': raw['name'], 'source': source, 'source_id': sid, 'profile_data': raw}
                return {'status': 'not_found', 'error': 'Неверный ID исполнителя'}
            hint_track = ref.get('hint_track') or (context.get('title') if isinstance(context, dict) else None) or (context.get('track') if isinstance(context, dict) else None)
            candidates, failed = self._artist_candidates(name, deadline, is_current, include_deezer=bool(hint_track))
            alt = alt_script_artist(name)
            exact = [h for h in candidates if artist_matches(name, h['name'], self.settings) or (alt and artist_matches(alt, h['name'], self.settings))]
            near = [h for h in candidates if similarity(name, h['name']) >= .75 or (alt and similarity(alt, h['name']) >= .75)]
            # S4-001: a free-text query is not a confirmed artist entity. The
            # UI marks such requests (require_candidates) and the resolver must
            # then never auto-select the single name match - the user picks
            # from the candidates, otherwise any string that happens to equal a
            # channel name would open that (possibly wrong) artist's profile.
            if len(exact) == 1 and not ref.get('require_candidates'):
                return self.resolve_artist(name, exact[0], is_current, deadline)

            # ART-011: Disambiguate homonyms with hint_track (Riff server.js:3042)
            matching_candidates = exact or near
            if hint_track and len(matching_candidates) > 1:
                from services.music_matching import normalize as norm_title
                norm_hint = norm_title(hint_track)
                supported = []
                checked_all = True
                try:
                    itunes_data = self._itunes_candidates_data(matching_candidates, deadline, is_current)
                except Exception:
                    itunes_data = {'results': []}
                    checked_all = False
                for cand in matching_candidates:
                    has_match = False
                    if time.monotonic() < deadline and is_current():
                        try:
                            songs = self._candidate_songs(cand, deadline, is_current, itunes_data)
                            for s in songs:
                                s_title = s.get('title') or ''
                                if s_title and norm_title(s_title) == norm_hint:
                                    has_match = True
                                    break
                        except Exception:
                            checked_all = False
                    else:
                        checked_all = False
                    if has_match:
                        cand['matching_track'] = hint_track
                        supported.append(cand)
                if checked_all and len(supported) == 1:
                    return self.resolve_artist(name, supported[0], is_current, deadline)

            options = exact or near
            if options:
                options.sort(key=lambda candidate: not bool(candidate.get('matching_track')))
                return {'status': 'ambiguous', 'candidates': options}
            return {'status': 'unavailable' if failed else 'not_found', 'error': 'Не удалось проверить исполнителя' if failed else 'Исполнитель не найден'}
        return self._cached(key, fetch, deadline)

    def _itunes_candidates_data(self, candidates, deadline, is_current):
        ids = sorted({str(c['source_id']) for c in candidates if c.get('source') == 'itunes' and str(c.get('source_id','')).isdigit()})
        if not ids:
            return None
        return ITunesGateway.get('https://itunes.apple.com/lookup?id=' + ','.join(ids) + '&entity=song&limit=200',
                                 deadline=deadline, is_current=is_current, settings=self.settings)

    def _candidate_songs(self, candidate, deadline, is_current, itunes_data=None):
        """Catalogue evidence stays attached to the candidate's own provider ID."""
        source, sid = candidate.get('source'), str(candidate.get('source_id') or '')
        if source == 'youtube':
            yt = getattr(self.youtube, '_ytmusic', None)
            if not yt:
                raise CatalogueUnavailable('YouTube Music недоступен')
            raw = self._call(lambda: yt.get_artist(sid), deadline, is_current)
            candidate['subscribers'] = raw.get('subscribers') or ''
            songs = [song for song in (raw.get('songs') or {}).get('results') or []
                     if not song.get('artists') or credited_to(song, candidate['name'], sid, self.settings)]
        elif source == 'itunes':
            raw = itunes_data if itunes_data is not None else ITunesGateway.get(f'https://itunes.apple.com/lookup?id={sid}&entity=song&limit=200',
                                   deadline=deadline, is_current=is_current, settings=self.settings)
            songs = [{'title': item.get('trackName', '')} for item in raw['results']
                     if item.get('kind') == 'song' and str(item.get('artistId')) == sid]
        elif source == 'deezer':
            raw = self._call(lambda: self._deezer_get('artist/' + sid + '/top', limit=50), deadline, is_current)
            songs = [{'title': item.get('title', '')} for item in raw.get('data', [])
                     if str((item.get('artist') or {}).get('id')) == sid]
        else:
            raise CatalogueUnavailable('Источник не поддерживает проверку исполнителя')
        titles = list(dict.fromkeys(song['title'] for song in songs if song.get('title')))
        candidate['preview_track'] = ' · '.join(titles[:3])
        return songs

    def preview_artists(self, candidates, is_current=lambda: True):
        deadline = time.monotonic() + 8
        output = copy.deepcopy(candidates)
        try:
            itunes_data = self._itunes_candidates_data(output, deadline, is_current)
        except Exception:
            itunes_data = {'results': []}
        for candidate in output:
            if not is_current() or time.monotonic() >= deadline:
                continue
            try:
                self._candidate_songs(candidate, deadline, is_current, itunes_data)
            except Exception:
                continue
        return output

    def album_details(self, album, local_lookup=None, is_current=lambda: True, _deadline=None):
        deadline = _deadline if _deadline is not None else time.monotonic() + 8
        source = album.get('source') or 'local'
        sid = str(album.get('source_id') or album.get('id') or '')
        title, artist = album.get('title') or album.get('album') or '', album.get('artist') or ''
        if source == 'local':
            tracks = local_lookup(title, artist) if local_lookup else []
            result = {'status': 'found' if tracks else 'not_found', 'verified': False, 'album': dict(album, source='local'), 'tracks': tracks}
            yt = getattr(self.youtube, '_ytmusic', None)
            if tracks and yt and title and artist:
                try:
                    hits = self._call(lambda: yt.search(f'{artist} {title}', filter='albums', limit=8), deadline, is_current)
                    matches = [h for h in hits or [] if similarity(title, h.get('title')) == 1 and artist_matches(artist, h.get('artists'), self.settings) and h.get('browseId')]
                    if len(matches) == 1:
                        reference = dict(album, source='youtube', source_id=matches[0]['browseId'], artists=matches[0].get('artists') or [])
                        verified = self.album_details(reference, is_current=is_current, _deadline=deadline)
                        result.update(verified=verified.get('status') == 'found', catalog_status=verified.get('status'))
                    else:
                        result['catalog_status'] = 'ambiguous' if matches else 'not_found'
                except Exception:
                    result['catalog_status'] = 'unavailable'
            return result
        key = ('album', source, sid, name_key(title), name_key(artist), repr(artist_aliases(self.settings)))
        def fetch():
            if source == 'deezer':
                from services.deezer_service import DeezerService
                result = self._call(lambda: DeezerService(self.settings).collection('album', sid), deadline, is_current)
                return {'status': 'found', 'verified': True, 'album': dict(album, title=result['name']),
                        'tracks': result['tracks']}
            if source in ('spotify', 'itunes'):
                collection = sid.removeprefix('spotify_album_')
                if not collection.isdigit():
                    return {'status': 'not_found', 'error': 'Неверный ID альбома'}
                data = ITunesGateway.get(f'https://itunes.apple.com/lookup?id={collection}&entity=song&limit=200', deadline=deadline, is_current=is_current, settings=self.settings)
                raw = next((h for h in data['results'] if h.get('wrapperType') == 'collection' and h.get('collectionType') == 'Album' and str(h.get('collectionId')) == collection), None)
                if not raw:
                    return {'status': 'not_found', 'tracks': []}
                actual_title, actual_artist = raw.get('collectionName', ''), raw.get('artistName', '')
                if (title and similarity(title, actual_title) < .85) or (artist and not artist_matches(artist, actual_artist, self.settings)):
                    return {'status': 'not_found', 'error': 'Название или исполнитель альбома не совпадают', 'tracks': []}
                tracks = []
                for h in data['results']:
                    if h.get('kind') != 'song' or str(h.get('collectionId')) != collection or not h.get('trackId'):
                        continue
                    person, song = h.get('artistName') or actual_artist, h.get('trackName') or ''
                    tracks.append({'id': 'spotify_' + str(h['trackId']), 'source': 'spotify', 'source_id': f'ytsearch1: {person} - {song}',
                                   'title': song, 'artist': person, 'album': actual_title, 'duration': (h.get('trackTimeMillis') or 0) / 1000,
                                   'cover_url': (h.get('artworkUrl100') or '').replace('100x100bb', '600x600bb')})
                details = dict(album, source_id=collection, title=actual_title, artist=actual_artist, type='album')
            elif source == 'youtube':
                yt = getattr(self.youtube, '_ytmusic', None)
                if not yt:
                    raise CatalogueUnavailable('YouTube Music недоступен')
                browse = sid.removeprefix('yt_album_')
                if not browse:
                    return {'status': 'not_found', 'tracks': []}
                if browse.startswith('OLAK'):
                    playlist = self._call(lambda: yt.get_playlist(browse, limit=1), deadline, is_current)
                    browse = next((t.get('album', {}).get('id') for t in playlist.get('tracks', []) if isinstance(t.get('album'), dict) and t['album'].get('id')), '')
                if not browse.startswith('MPRE'):
                    return {'status': 'not_found', 'error': 'Запись не является альбомом', 'tracks': []}
                raw = self._call(lambda: yt.get_album(browse), deadline, is_current)
                if not raw or not raw.get('title') or not isinstance(raw.get('tracks'), list):
                    return {'status': 'not_found', 'tracks': []}
                actual_title = raw['title']
                people = raw.get('artists') or []
                actual_artist = ', '.join(h.get('name', '') for h in people)
                wanted_ids = {str(p.get('id') or p.get('browseId')) for p in album.get('artists') or [] if p.get('id') or p.get('browseId')}
                if album.get('artist_channel_id'):
                    wanted_ids = {str(album['artist_channel_id'])}
                offered_ids = {str(p.get('id') or p.get('browseId')) for p in people if p.get('id') or p.get('browseId')}
                if wanted_ids and offered_ids and not wanted_ids.intersection(offered_ids):
                    return {'status': 'not_found', 'error': 'Альбом принадлежит другому исполнителю', 'tracks': []}
                if (title and similarity(title, actual_title) < .85) or (artist and not artist_matches(artist, people, self.settings)):
                    return {'status': 'not_found', 'error': 'Название или исполнитель альбома не совпадают', 'tracks': []}
                tracks = []
                for h in raw['tracks']:
                    video = h.get('videoId')
                    if not video or h.get('isAvailable') is False:
                        continue
                    thumbs = h.get('thumbnails') or raw.get('thumbnails') or []
                    tracks.append({'id': 'yt_' + video, 'source': 'youtube', 'source_id': video, 'title': h.get('title', ''),
                                   'artist': ', '.join(p.get('name', '') for p in h.get('artists') or people), 'artists': h.get('artists') or people,
                                   'album': actual_title, 'duration': h.get('duration_seconds') or 0, 'cover_url': thumbs[-1].get('url', '') if thumbs else ''})
                details = dict(album, title=actual_title, artist=actual_artist, source_id=browse, type='album')
            else:
                return {'status': 'not_found', 'error': 'Источник не содержит подтверждённого альбома', 'tracks': []}
            return {'status': 'found', 'verified': True, 'album': details, 'tracks': tracks}
        return self._cached(key, fetch, deadline)
