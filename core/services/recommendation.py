import json
import math
import random
from typing import Any, Dict, List, Union

















class RecommendationEngine:
    def __init__(self, user_profile: Dict[str, Any], current_context: Dict[str, Any], catalog: List[Dict[str, Any]]):
        self.profile = user_profile or {}
        self.context = current_context or {}
        self.catalog = [t for t in (catalog or []) if isinstance(t, dict)]
        self.catalog_map = {str(t.get("id")): t for t in self.catalog if t.get("id") is not None}
        self.history_set = set(str(x) for x in (self.profile.get("history") or []) if x is not None)
        self.favorites_set = set(str(x) for x in (self.profile.get("favorites") or []) if x is not None)
        self.subs_set = set(str(x) for x in (self.profile.get("subscriptions") or []) if x is not None)
        self.skips = self.profile.get("skips") or {}
        if not isinstance(self.skips, dict):
            self.skips = {}
        self.repeats = self.profile.get("repeats") or {}
        if not isinstance(self.repeats, dict):
            self.repeats = {}
        self.skip_penalty_threshold = 1

    @staticmethod
    def _safe_float(val: Any, default: float = 0.0) -> float:
        if val is None:
            return default
        try:
            return float(val)
        except (ValueError, TypeError):
            return default

    def _euclidean_distance(self, t1: Dict[str, Any], t2: Dict[str, Any]) -> float:
        features = ["bpm", "energy", "mood", "acoustics", "bass"]
        dist = 0.0
        for f in features:
            v1 = self._safe_float(t1.get(f), 120.0 if f == "bpm" else 0.5)
            v2 = self._safe_float(t2.get(f), 120.0 if f == "bpm" else 0.5)
            if f == "bpm":
                v1 = v1 / 200.0
                v2 = v2 / 200.0
            dist += (v1 - v2) ** 2
        return math.sqrt(dist)

    def _get_eligible_tracks(self) -> List[Dict[str, Any]]:
        return [t for t in self.catalog if self.skips.get(str(t.get("id") or ""), 0) <= self.skip_penalty_threshold]

    def _cluster_by_vibe(self, tracks: List[Dict[str, Any]], target_energy: float, target_genre: str = None) -> List[Dict[str, Any]]:
        filtered = tracks
        if target_genre:
            filtered = [t for t in filtered if t.get("genre") == target_genre]
        filtered.sort(key=lambda t: abs(self._safe_float(t.get("energy"), 0.5) - target_energy))
        return filtered

    def _enforce_ratio(self, pool: List[Dict[str, Any]], count: int) -> List[str]:
        familiar_pool = [t for t in pool if str(t.get("id") or "") in self.history_set or str(t.get("id") or "") in self.favorites_set]
        discovery_pool = [t for t in pool if str(t.get("id") or "") not in self.history_set and str(t.get("id") or "") not in self.favorites_set]

        familiar_count = int(count * random.uniform(0.6, 0.7))
        discovery_count = count - familiar_count

        selected = []

        if len(familiar_pool) >= familiar_count:
            selected.extend(random.sample(familiar_pool, familiar_count))
        else:
            selected.extend(familiar_pool)
            discovery_count += familiar_count - len(familiar_pool)

        if len(discovery_pool) >= discovery_count:
            selected.extend(random.sample(discovery_pool, discovery_count))
        else:
            selected.extend(discovery_pool)

        random.shuffle(selected)
        return [str(t["id"]) for t in selected if t.get("id") is not None]

    def generate_dynamic_mixes(self) -> List[Dict[str, Any]]:
        eligible = self._get_eligible_tracks()
        mixes = []

        is_workout = self.context.get("activity") == "workout"
        target_energy = 0.8 if is_workout else 0.5
        vibe_pool = self._cluster_by_vibe(eligible, target_energy)
        daily_mix_tracks = self._enforce_ratio(vibe_pool, 10)

        mixes.append({
            "name": "Daily Mix 1",
            "description": f"Focused on {'high' if target_energy > 0.6 else 'chill'} energy",
            "focus": self.context.get("activity", "chill"),
            "tracks": daily_mix_tracks,
        })

        discovery_pool = [t for t in eligible if str(t.get("id") or "") not in self.history_set]

        fav_tracks = [self.catalog_map[tid] for tid in self.favorites_set if tid in self.catalog_map]

        if fav_tracks:
            centroid = {
                f: sum(self._safe_float(t.get(f), 120.0 if f == "bpm" else 0.5) for t in fav_tracks) / len(fav_tracks)
                for f in ("bpm", "energy", "mood", "acoustics", "bass")
            }
            discovery_pool.sort(key=lambda t: self._euclidean_distance(t, centroid))

        dw_tracks = [str(t["id"]) for t in discovery_pool[:10] if t.get("id") is not None]

        mixes.append({
            "name": "Discover Weekly",
            "description": "New finds for you",
            "focus": "discovery",
            "tracks": dw_tracks,
        })

        release_pool = [t for t in eligible if t.get("is_new_release") and str(t.get("artist_id") or "") in self.subs_set]

        mixes.append({
            "name": "Release Radar",
            "description": "New releases from your favorites",
            "focus": "new_releases",
            "tracks": [str(t["id"]) for t in release_pool[:10] if t.get("id") is not None],
        })

        return mixes

    def generate_smart_recs(self) -> Dict[str, Any]:
        eligible = self._get_eligible_tracks()

        history_list = [str(x) for x in (self.profile.get("history") or []) if x is not None]
        last_track_id = history_list[-1] if history_list else None
        next_track = []

        if last_track_id and last_track_id in self.catalog_map:
            last_track = self.catalog_map[last_track_id]
            similar = sorted(eligible, key=lambda t: self._euclidean_distance(t, last_track))
            next_track = [str(t["id"]) for t in similar if t.get("id") is not None and str(t["id"]) != last_track_id][:3]

        radio_artist = next(iter(self.subs_set), None) if self.subs_set else None
        artist_radio_tracks = []

        if radio_artist:
            artist_radio_tracks = [str(t["id"]) for t in eligible if str(t.get("artist_id") or "") == radio_artist and t.get("id") is not None][:10]

        return {
            "next_track_prediction": next_track,
            "artist_radio": {
                "artist_id": radio_artist,
                "tracks": artist_radio_tracks,
            },
        }

    def generate_dynamic_charts(self) -> Dict[str, Any]:
        global_pool = sorted(self.catalog, key=lambda t: self._safe_float(t.get("global_streams"), 0), reverse=True)
        viral_pool = sorted(self.catalog, key=lambda t: self._safe_float(t.get("viral_velocity"), 0), reverse=True)

        personal = sorted(self.repeats.items(), key=lambda x: self._safe_float(x[1], 0), reverse=True)

        return {
            "global_top_50": [str(t["id"]) for t in global_pool[:10] if t.get("id") is not None],
            "viral_72h": [str(t["id"]) for t in viral_pool[:10] if t.get("id") is not None],
            "personal_top": [str(tid) for tid, count in personal[:10]],
        }

    def generate_artist_spotlights(self) -> Dict[str, List[Dict[str, Any]]]:
        return {
            "similar_artists": [
                {
                    "artist_id": "a_sim",
                    "artist_name": "Similar Artist",
                    "reason": "Based on your tastes",
                }
            ],
            "niche_discovery": [
                {
                    "artist_id": "a_niche",
                    "artist_name": "Niche Artist",
                    "reason": "High energy match",
                }
            ],
        }

    def generate_all(self) -> Dict[str, Any]:
        return {
            "dynamic_mixes": self.generate_dynamic_mixes(),
            "smart_recs": self.generate_smart_recs(),
            "dynamic_charts": self.generate_dynamic_charts(),
            "artist_spotlights": self.generate_artist_spotlights(),
        }


def run_recommendation(user_profile: Dict, current_context: Dict, catalog: List[Dict]) -> Dict:
    engine = RecommendationEngine(user_profile, current_context, catalog)
    return engine.generate_all()


def build_real_engine(db, personalization: dict) -> RecommendationEngine:
    import time
    catalog = db.get_all_tracks(limit=200) or []
    history_records = db.get_history(limit=100) or []
    history = [str(r.get("track_id", "")) for r in history_records if r.get("track_id")]
    favorites_records = db.get_favorite_tracks() or []
    favorites = [str(r.get("id", "")) for r in favorites_records if r.get("id")]
    most_played = db.get_most_played(limit=50) or []
    repeats = {str(r.get("id", "")): r.get("play_count", 0) for r in most_played if r.get("id")}
    
    pers = personalization or {}
    fav_genres = pers.get("favorite_genres", [])
    exp_artists = pers.get("explicit_artists", [])
    pref_moods = pers.get("preferred_moods", [])
    
    user_profile = {
        "history": history,
        "favorites": favorites,
        "subscriptions": exp_artists,
        "genres": fav_genres,
        "moods": pref_moods,
        "skips": {},
        "repeats": repeats,
    }
    
    hour = time.localtime().tm_hour
    activity = "chill"
    if 6 <= hour < 12:
        activity = "morning"
    elif 12 <= hour < 18:
        activity = "focus"
    elif 18 <= hour < 22:
        activity = "workout"
        
    current_context = {
        "time_of_day": "morning" if activity == "morning" else "evening",
        "device": "desktop",
        "activity": activity,
    }
    
    for t in catalog:
        t["id"] = str(t.get("id", ""))
        t["bpm"] = t.get("bpm") or 120
        t["energy"] = t.get("energy") or 0.5
        t["mood"] = t.get("mood") or 0.5
        t["acoustics"] = t.get("acoustics") or 0.5
        t["bass"] = t.get("bass") or 0.5
        
    return RecommendationEngine(user_profile, current_context, catalog)
