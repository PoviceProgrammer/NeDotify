"""Metadata-only catalogue radio; no audio extraction or background pools."""
import time
import re

from services.artist_identity import canonical_artist, name_key
from services.deezer_service import DeezerService


class RecommendationDiscovery:
    def __init__(self, settings=None, deezer=None):
        self.settings = settings
        self._deezer = deezer

    def get_candidates(self, seeds, artists, limit=30, deadline=None):
        if self.settings and not self.settings.get('services', 'deezer_enabled', True):
            return []
        deadline = deadline if deadline is not None else time.monotonic() + 7
        limit = min(60, max(0, int(limit)))
        if not limit or time.monotonic() >= deadline:
            return []
        if self._deezer is None:
            self._deezer = DeezerService(self.settings)
        provider = self._deezer
        names = list(dict.fromkeys([str(a).strip() for a in artists if str(a).strip()] +
                                  [str(t.get('artist') or '').strip() for t in seeds if t.get('artist')]))[:3]
        results, seen = [], set()

        def rows(path, **params):
            if len(results) >= limit or time.monotonic() >= deadline:
                return []
            try:
                data = provider._get(path, **params)
                return data.get('data', []) if isinstance(data, dict) else []
            except Exception:
                return []

        def add(items, origin, seed_artist):
            for item in items:
                if len(results) >= limit:
                    break
                try:
                    track = provider._track(item)
                except Exception:
                    continue
                sid = track.get('source_id')
                if not sid or sid in seen:
                    continue
                seen.add(sid)
                results.append(dict(track, recommendation_source=origin,
                                    recommendation_relevance=.8 if origin == 'deezer_related' else .75,
                                    recommendation_seed_artists=[canonical_artist(seed_artist)]))

        for name in names:
            # An uploader/channel name must not silently select a different artist.
            matches = [row for row in rows('search/artist', q=name, limit=3)
                       if canonical_artist(row.get('name') or '') == canonical_artist(name)]
            candidate_ids = set()
            for match in matches:
                try:
                    candidate_ids.add(provider._id(match.get('id')))
                except Exception:
                    continue
            if not candidate_ids:
                continue
            # Identical artist names are not identity evidence. Require a seed
            # recording with the same title and duration from this catalogue ID.
            verified_ids = set()
            for seed in seeds:
                if canonical_artist(seed.get('artist')) != canonical_artist(name):
                    continue
                try:
                    duration = float(seed.get('duration') or 0)
                except (ValueError, TypeError):
                    continue
                if duration <= 0 or not seed.get('title'):
                    continue
                # Public search can return no rows for quoted track filters
                # containing punctuation. Search ordinary terms, then enforce
                # the exact recording identity below instead of trusting rank.
                query = re.sub(r'[^\w\s]', ' ', name + ' ' + str(seed['title']))
                recordings = rows('search', q=query, limit=5)
                for recording in recordings:
                    artist = recording.get('artist') or {}
                    try:
                        same_duration = abs(float(recording.get('duration') or 0) - duration) <= max(4, duration * .025)
                    except (ValueError, TypeError):
                        continue
                    if (str(artist.get('id')) in candidate_ids and same_duration and
                            name_key(recording.get('title')) == name_key(seed['title'])):
                        verified_ids.add(str(artist['id']))
            if len(verified_ids) != 1:
                continue
            aid = next(iter(verified_ids))
            add(rows('artist/' + aid + '/radio', limit=min(20, limit)), 'deezer_radio', name)
            related = rows('artist/' + aid + '/related', limit=3)
            for artist in related[:2]:
                try:
                    related_id = provider._id(artist.get('id'))
                except Exception:
                    continue
                add(rows('artist/' + related_id + '/top', limit=5), 'deezer_related', name)
        return results
