# WN-20 — SoundCloud provider — ROLE A (Correctness & Reliability)

## AREA WN-20 — SoundCloud provider — ROLE A

### 1. Scope reviewed

**Files opened (path: line ranges actually read)**

- `services/soundcloud_service.py` — **full file, L1–1055** (all 971 non-empty lines):
  - `_TTLCache` L17–49
  - `_UNAVAILABLE_MARKS` L70–77, `_UNAVAILABLE_TTL` L83, `_UNAVAILABLE_MSG` L85
  - `_is_drm_transcoding` L88–97, `_is_unplayable_error` L100–103, `_MEDIA_DENIED_STATUSES` L109, `_unavailable_key` L112–123
  - `class SoundCloudService(BaseMusicService)` L126–1055: `__init__` L129–171, `_get_client_id` L173–210, `_api_get` L212–229, `reset_ydl` L231–235, `_get_ydl` L237–264, `_get_ydl_search` L266–289, `available` L291–293, `search` L295–402, `get_playlist_tracks` L404–491, `get_track_metadata` L493–524, `_mark_unavailable` L526–539, `_media_url_is_servable` L541–567, `get_stream_url` L569–846, `download_audio_sync` L847–958, `get_related_tracks_sync` L960–1016, `get_waveform_data_sync` L1018–1055
- `services/base_service.py` L1–329 (cache contract, `_join_request`, `_cache_lock`, `normalize_proxy_url`)
- `requirements.txt` L1–25 (the `curl_cffi` comment at L10–14)
- `.venv_win/Lib/site-packages/yt_dlp/extractor/soundcloud.py` L1–1173 + L1316–1360 (the reference extractor: DRM rule, `policy` handling, preview detection, impersonation)
- `.venv_win/Lib/site-packages/yt_dlp/extractor/common.py` (via `inspect.getsource`) — `raise_geo_restricted`, `report_drm`
- `.venv_win/Lib/site-packages/yt_dlp/YoutubeDL.py` L4238–4331 (impersonate-target resolution / "no impersonate target is available")

**Callers traced (read for the calling contract, defects attributed to their owning area)**

- `core/api.py` L2080–2232 (`search` fan-out, 8 s SoundCloud deadline at L2197), L2540–2613 (`get_playlist_tracks`), L3267–3284 (`_resolve_track_metadata` → `get_track_metadata`), L3588–3590 (`get_waveform_data_sync`)
- `core/app.py` L300–506 (`resolve_stream_url_async`, SoundCloud URL building L322–329, YouTube→SoundCloud fallback L446–492), L565–586 (pool shutdown)
- `core/resolver.py` L1–271 (`StreamResolver`, `mark_unavailable`, `_FAIL_TTL = 120`)
- `core/downloader.py` L130–189 (`_call_provider`), L500–662 (`_fetch_from_provider`), L664–711 (`_fetch_with_retry`)
- `core/download_transfer.py` L1–128 (`DownloadContext.stem`, `ydl_options`)
- `core/proxy.py` L380–499 (`_rewrite_hls_playlist`), L960–1179 (SoundCloud cookie injection, 403 self-heal, HLS branch)
- `services/track_resolver.py` L240–359 (`_search_soundcloud`, per-call `SoundCloudService` construction at L251–252)
- `services/playlist_import_service.py` L180–209 (per-call `SoundCloudService` construction at L191–192)
- `audio/engine.py` L395–474 (SoundCloud branch; duration unit bug at L421 — **belongs to WN-17**)

**Tests read**: `tests/test_soundcloud_drm_unavailable.py` (355 L), `tests/test_hls_playback.py` (162 L), `tests/test_engine_resolve.py` L520–560.
**Executed**: `pytest tests/test_soundcloud_drm_unavailable.py tests/test_hls_playback.py -q` → **18 passed** (so the findings below are gaps the current suite does not cover).

**Dynamic probes written** (scratch, outside the repo): `%TEMP%\opencode\audit_reports\_sc_probe.py`, `_sc_probe2.py`, `_sc_probe3.py`, `_sc_probe4.py` — hermetic stubs over the real `SoundCloudService`.

---

### 2. Findings

#### F-WN-20-1  [P1] — A single DRM transcoding discards a playable URL found in a *later* non-DRM transcoding (diverges from the yt-dlp rule the docstring claims to reuse)

- **File:** `services/soundcloud_service.py:662–690` (loop L665–680, verdict L682–690); reference `.venv_win/Lib/site-packages/yt_dlp/extractor/soundcloud.py:375–379`
- **Confirmed:** yes
- **Description:** `has_drm` is set as soon as *any* transcoding in the list is DRM, and the verdict `if stream_url and has_drm:` then throws away a `stream_url` that was found in a **later, non-DRM** transcoding and marks the whole track unavailable for an hour. yt-dlp's rule is the opposite: DRM is only fatal when **no** format was produced at all.
- **Cause:** the two facts are combined incorrectly. yt-dlp: `if not formats: if has_drm: self.report_drm(track_id)`. The service: `if stream_url and has_drm: → discard`. The `break` at L680 normally hides the bug (progressive is sorted first at L663 and breaks out before a DRM entry is visited), but the sorted order is `0 if protocol == 'progressive' else 1` — so when the progressive transcoding yields **no** URL, the loop continues into the DRM entry (`has_drm = True`) and then into a later non-DRM entry that *does* resolve.
- **Trigger conditions:** a track whose `media.transcodings` contains ≥3 entries where (a) the first/progressive one returns no `url`, (b) a `cbc-*`/`ctr-*` entry is visited, and (c) a later non-DRM entry (e.g. `hls_opus_0_0`) resolves.
- **User impact:** the track is declared "недоступен: защищён DRM или снят автором" for an hour and a perfectly playable HLS/MP3 URL is thrown away — the user's library silently loses a track that can be played.
- **Evidence:**
  ```python
  662:  has_drm = False
  663:  sorted_tc = sorted(transcodings, key=lambda x: 0 if x.get('format', {}).get('protocol') == 'progressive' else 1)
  665:  for tc in sorted_tc:
  666:      if _is_drm_transcoding(tc):
  667:          has_drm = True
  668:          continue
  ...
  682:  if stream_url and has_drm:
  ...
  689:      self._mark_unavailable(track_url, 'DRM-protected transcodings')
  690:      stream_url = None
  ```
  vs. yt-dlp 2026.08.19 `extractor/soundcloud.py`:
  ```python
  375:  if not formats:
  376:      if has_drm:
  377:          self.report_drm(track_id)
  ```
- **Reproduction / verification:** probe `_sc_probe4.py` CASE A′ — payload with `mp3_0/progressive` (media endpoint returns no `url`), `abr_sq/cbc-aes`, `hls_opus_0_0/hls` (media endpoint returns `https://cdn.example/playable.m3u8`). Result: `resolved url: None`, `memoised unavailable? True`, `stream cache: None` — i.e. the playable HLS URL was found, then discarded. yt-dlp on the same payload keeps one format and plays it.
- **Suggested fix:** make the DRM verdict mirror yt-dlp — treat DRM as fatal only when *no* playable URL was obtained (`if not stream_url and has_drm:`), and keep the per-transcoding DRM skip (L666–668) as it is.
- **Fix side effects:** a genuinely DRM track whose only *non-DRM* transcoding resolves to a CDN-403 URL would no longer be memoised by this branch — it must still be caught by the `_media_url_is_servable` probe at L692–699, which is the intended second line of defence.
- **Discovered by:** A

#### F-WN-20-2  [P1] — One CDN probe answering 401/403/404/410 silently removes the track for a full hour, with a "DRM / removed by the author" message that is usually wrong

- **File:** `services/soundcloud_service.py:109` (`_MEDIA_DENIED_STATUSES`), `:541–567` (`_media_url_is_servable`), `:585–592` (short-circuit), `:692–699` (`_mark_unavailable`), `:83` (`_UNAVAILABLE_TTL = 3600`)
- **Confirmed:** yes (mechanism); the real-world frequency of a *transient* CDN denial is a hypothesis (see §4)
- **Description:** the "final" verdict is written from a **single** ranged GET with no retry, and the four statuses are treated as proof of DRM/removal. The memo then suppresses all re-resolution for 3600 s. The service cannot distinguish "the CDN refuses common-encryption media" from "this edge/WAF/geo node refused me right now".
- **Cause:** `_media_url_is_servable` returns `status not in _MEDIA_DENIED_STATUSES` (L564) with a single attempt and no backoff; `_mark_unavailable` (L526–539) then writes an entry keyed by track, and `get_stream_url` L585–592 answers from that memo without touching the network. The user-facing text is fixed at `_UNAVAILABLE_MSG` (L85) regardless of the actual reason stored in the memo (the memo even stores the accurate reason `"CDN refused the media URL"`).
- **Trigger conditions:** the CDN answers 401/403/404/410 for a URL that is in fact playable (geo edge, WAF/rate-limit, transient 404 on an edge node, a proxy in the middle rewriting the response).
- **User impact:** the track disappears from playback for an hour with the message "Трек недоступен: защищён DRM или снят автором" — the diagnosis is wrong and the user cannot retry (the second attempt performs **0** network calls).
- **Evidence:**
  ```python
  109:  _MEDIA_DENIED_STATUSES = frozenset({401, 403, 404, 410})
  ...
  554:  probe = self._session.get(url, timeout=3.0, headers={'Range': 'bytes=0-1'}, stream=True)
  564:  return status not in _MEDIA_DENIED_STATUSES
  ...
  698:  self._mark_unavailable(track_url, 'CDN refused the media URL')
  ...
  585:  unavailable = self._unavailable_cache.get(_unavailable_key(track_url))
  586:  if unavailable and not cached_url:
  591:      error_callback(_UNAVAILABLE_MSG)
  ```
- **Reproduction / verification:** probe `_sc_probe3.py` CASE G — stub CDN answers 403 for the ranged probe. 1st attempt: memo = `"CDN refused the media URL"`. Probe status then flipped back to 200 (CDN recovered); 2nd attempt: `extra CDN calls on 2nd attempt: 0`, `error = Трек недоступен: защищён DRM или снят автором`, `memo TTL: 3600 seconds`.
- **Suggested fix:** (a) retry the probe once or twice before declaring a verdict; (b) shorten the TTL for a CDN-refusal verdict (it is not a property of the track) and keep the long TTL only for extractor-level verdicts; (c) surface the stored reason in the message instead of the fixed DRM wording.
- **Fix side effects:** a genuinely DRM track would then cost a few extra probe round trips per attempt; a shorter TTL means a real DRM track is re-probed more often (bounded by the memo TTL, not a storm).
- **Discovered by:** A

#### F-WN-20-3  [P1] — The SoundCloud probe can invalidate a **YouTube fallback** URL and then blame DRM — cross-provider contamination of the shared stream cache

- **File:** `services/soundcloud_service.py:607–617` (probe of the cached URL), `:526–539` (`_mark_unavailable` pops `soundcloud:<key>` from the shared `BaseMusicService._stream_cache`), `:783–796` (the YouTube fallback writes its URL into the same cache slot)
- **Confirmed:** yes
- **Description:** the cached URL under `soundcloud:<track_url>` may be a **YouTube** URL produced by the fallback at L783–796 (`resolved_source: 'youtube'`). `get_stream_url` re-probes that URL with the *SoundCloud* session (L610–611) and, on a 401/403/404/410, calls `_mark_unavailable` → the working YouTube fallback is **deleted from the shared stream cache** and the track is memoised as "DRM / removed by the author" for an hour.
- **Cause:** the probe/mark path has no notion of which provider produced the cached URL; `metadata['resolved_source'] = 'youtube'` (L792) is stored but never consulted by L607–617.
- **Trigger conditions:** a SoundCloud track whose extraction failed and whose YouTube fallback succeeded, where the follow-up probe of the `googlevideo.com` URL returns 401/403/404/410 (edge/CDN refusal, a proxy rewriting the response, a geo-node refusal).
- **User impact:** a track that was playing fine through the YouTube fallback stops playing, the library entry goes dead for an hour, and the message names DRM — a diagnosis that has nothing to do with what happened.
- **Evidence:**
  ```python
  607:  cached = self.get_from_cache(cache_key)
  608:  cached_url = cached.get('stream_url') if cached else None
  609:  if cached_url:
  610:      if (self._verified_cache.get(cached_url)
  611:              or self._media_url_is_servable(cached_url)):
  ...
  615:          self._mark_unavailable(track_url, 'CDN refused the cached media URL')
  616:          error_callback(_UNAVAILABLE_MSG)
  ```
  and `_mark_unavailable`:
  ```python
  538:  with self._cache_lock:
  539:      self._stream_cache.pop(f'soundcloud:{track_url}', None)
  ```
- **Reproduction / verification:** probe `_sc_probe3.py` CASE E — seed `BaseMusicService.set_to_cache("soundcloud:12345", {... "stream_url": "https://r1---sn.googlevideo.com/videoplayback?expire=... ", "resolved_source": "youtube"})`, probe returns 403. Result: `resolved url: None`, `error: Трек недоступен: защищён DRM или снят автором`, `memoised unavailable? True`, `stream cache after: None` — the working fallback was destroyed.
- **Suggested fix:** only probe/mark URLs the service itself obtained from SoundCloud (check `metadata.get('resolved_source')` / the `source_id` provenance), and never delete a non-SoundCloud fallback from the shared cache.
- **Fix side effects:** a stale YouTube fallback would then be served until the base-class 6 h TTL / `stream_url_expired` retires it — the existing `core/playback_recovery.py` self-heal covers that path.
- **Discovered by:** A

#### F-WN-20-4  [P2] — `policy == "BLOCK"` (geo-restricted) is not recognised: the verdict is never memoised and the user gets a raw English exception

- **File:** `services/soundcloud_service.py:645` (only `SNIP` is handled), `:70–77` (`_UNAVAILABLE_MARKS` has no geo mark), `:731–739` (the re-raise path), `:840–843` (the raw exception message)
- **Confirmed:** yes
- **Description:** yt-dlp reports a blocked track by raising `GeoRestrictedError("This video is not available from your location due to geo restriction")`. None of `_UNAVAILABLE_MARKS` matches that text, so the exception is re-raised and the track is **never** memoised — every play attempt repeats the whole cascade (api-v2 + yt-dlp + a YouTube fallback search), and the user is shown the raw Python exception text instead of a message.
- **Cause:** the "permanent failure" classifier was built from the DRM/private/removed wording only; the geo wording yt-dlp produces (`raise_geo_restricted`, `extractor/soundcloud.py:378–379`) was never added.
- **Trigger conditions:** any track whose api-v2 payload carries `"policy": "BLOCK"` and no playable transcoding.
- **User impact:** repeated full-resolution cascades on every click (network + CPU), and an untranslated error string: "Произошла ошибка: Exception - ERROR: This video is not available from your location due to geo restriction".
- **Evidence:**
  ```python
  645:  preview_only = t_data.get('policy') == 'SNIP'
  ```
  ```python
  731:  except Exception as exc:
  732:      if not _is_unplayable_error(exc):
  733:          raise
  ...
  842:  error_callback(f'Произошла ошибка: {type(e).__name__} - {str(e)}')
  ```
  `_UNAVAILABLE_MARKS` = `('drm', 'private video', 'video unavailable', 'this video is unavailable', 'has been removed', 'does not exist')` — no geo wording.
- **Reproduction / verification:** probe `_sc_probe2.py` CASE C — payload with `"policy": "BLOCK"` and empty transcodings, yt-dlp stub raising the geo message. Result: `resolved url: None`, `error: Произошла ошибка: Exception - ERROR: This video is not available from your location due to geo restriction`, `memoised unavailable? False` (i.e. the verdict is re-derived on every attempt).
- **Suggested fix:** add the geo wording to `_UNAVAILABLE_MARKS` (and/or handle `policy == 'BLOCK'` explicitly next to the `SNIP` check at L645) and map it to a user-facing message.
- **Fix side effects:** a geo-blocked track would be memoised for up to an hour even though the block can lift — the TTL should be shorter for this class, or the verdict should be cleared on a successful resolution.
- **Discovered by:** A

#### F-WN-20-5  [P2] — `download_audio_sync` cannot recognise SoundCloud's 30-second preview URL, so a preview file can be registered as the downloaded track

- **File:** `services/soundcloud_service.py:887–893` (the download path) vs. `:743–744` (the correct check in `get_stream_url`)
- **Confirmed:** yes (code divergence); the end-to-end effect is a hypothesis about the exact URL yt-dlp selects (see §4)
- **Description:** the streaming path rejects a preview with **both** tests — `'preview' not in s_candidate` **and** `not re.search(r'/playlist/0/30/', s_candidate)` — but the download path only uses the first one. SoundCloud's 30-second preview URLs have the shape `.../playlist/0/30/...`, which does **not** contain the substring "preview", so a preview is treated as a full song.
- **Cause:** the two code paths implement the same predicate independently and drifted apart.
- **Trigger conditions:** a SNIP/preview-only SoundCloud track that yt-dlp resolves to the `/playlist/0/30/` format (yt-dlp's own preview detector is `t.get('snipped') or '/preview/' in format_url or re.search(r'/(?:preview|playlist)/0/30/', stream_url)`, `extractor/soundcloud.py:357–359`).
- **User impact:** the library shows the track as downloaded, but the local file ends after 30 seconds — the user believes the download succeeded.
- **Evidence:**
  ```python
  743:  if (s_candidate and 'preview' not in s_candidate
  744:          and not re.search(r'/playlist/0/30/', s_candidate)):
  ```
  ```python
  887:  is_preview = False
  888:  if info:
  889:      url_candidate = info.get('url', '')
  890:      if 'preview' in url_candidate:
  891:          is_preview = True
  ```
- **Reproduction / verification:** static comparison of the two predicates in the same file against yt-dlp's preview detector (`extractor/soundcloud.py:357–359`). A live reproduction needs a SNIP track.
- **Suggested fix:** reuse one predicate for both paths (e.g. a module-level `_is_preview_url(url)`), and additionally honour `info.get('is_preview')`/`format_id` from yt-dlp.
- **Fix side effects:** a preview would then be routed to the YouTube fallback branch at L893–924, which is slower but correct.
- **Discovered by:** A

#### F-WN-20-6  [P2] — A transcoding entry with `"format": null` raises `AttributeError` and abandons the whole api-v2 fast path for that track

- **File:** `services/soundcloud_service.py:96` (`_is_drm_transcoding`), `:663` (the sort key), `:665–673` (`tc.get(...)`)
- **Confirmed:** yes
- **Description:** `.get('format', {})` returns `None` when the key is **present with a null value**, and the code then calls `.get('protocol')` on it. The same pattern is in the `sorted()` key function at L663, so the exception is raised even before the DRM check.
- **Cause:** a missing-key default is used where a null-safe read is needed.
- **Trigger conditions:** one transcoding entry in the api-v2 payload with `"format": null` (or a `None` entry inside `transcodings`).
- **User impact:** the whole fast path for that track is abandoned (`except Exception as api_ex` at L717 → "Fast SoundCloud stream extraction failed") and the resolution falls back to the slow yt-dlp path; if that also fails, the user sees the raw text "Произошла ошибка: AttributeError - 'NoneType' object has no attribute 'get'".
- **Evidence:**
  ```python
  96:  protocol = str((transcoding or {}).get('format', {}).get('protocol') or '').lower()
  ```
  ```python
  663:  sorted_tc = sorted(transcodings, key=lambda x: 0 if x.get('format', {}).get('protocol') == 'progressive' else 1)
  ```
- **Reproduction / verification:** probe `_sc_probe.py` §3 — `_is_drm_transcoding({'format': None})` → `AttributeError: 'NoneType' object has no attribute 'get'` (raised at `soundcloud_service.py:96`). Probe `_sc_probe2.py` CASE B shows the same abort inside a real `get_stream_url` call (log line: `Fast SoundCloud stream extraction failed: 'NoneType' object has no attribute 'get'`).
- **Suggested fix:** read the protocol defensively — `fmt = (transcoding or {}).get('format') or {}` — in both L96 and L663, and skip non-dict transcoding entries.
- **Fix side effects:** none; the strictness was accidental.
- **Discovered by:** A

#### F-WN-20-7  [P2] — One track with `"duration": null` in the search payload aborts the entire api-v2 search page

- **File:** `services/soundcloud_service.py:337` (search), `:435` (playlist), `:708` (stream metadata), `:995` (related)
- **Confirmed:** yes
- **Description:** `int(item.get('duration', 0) / 1000)` divides before it converts. When the key is present with a null value, `.get('duration', 0)` returns `None` and `None / 1000` raises `TypeError`. In `search` the exception is caught by the *whole-API* handler at L357, so one bad item in a 20-item page discards the page.
- **Cause:** the `or 0` guard is missing on the value returned by `.get`.
- **Trigger conditions:** any api-v2 item with `"duration": null`.
- **User impact:** the whole SoundCloud result page is lost (the REST path is abandoned and the yt-dlp fallback runs, which is slow and usually returns far fewer results); with yt-dlp unavailable the user sees "Поиск SoundCloud недоступен" for a query that in fact had 19 usable hits.
- **Evidence:**
  ```python
  337:  duration = int(item.get('duration', 0) / 1000)
  ```
  (identical pattern at L435, L708, L995)
- **Reproduction / verification:** probe `_sc_probe2.py` CASE D — a search payload with one item carrying `"duration": None`. Result: `callback got: [('ERR', 'Поиск SoundCloud недоступен')]` and the log `Fast SoundCloud REST API search failed, trying yt-dlp: unsupported operand type(s) for /: 'NoneType' and 'int'` — i.e. the single bad item lost the whole page.
- **Suggested fix:** `dur_ms = item.get('duration') or 0; duration = int(dur_ms / 1000)` at all four sites (and skip the item instead of the page on a per-item failure).
- **Fix side effects:** none.
- **Discovered by:** A

#### F-WN-20-8  [P3] — api-v2 rate limiting (429) is neither retried nor surfaced; the `Retry-After` header is ignored

- **File:** `services/soundcloud_service.py:158` (`max_retries=0`), `:212–229` (`_api_get`), `:322`, `:423`, `:503`, `:642`, `:675`
- **Confirmed:** yes
- **Description:** the HTTP adapter is mounted with `max_retries=0` (L158) and `_api_get` only special-cases 401/403 (L215–229). A 429 — with or without a `Retry-After` header — is returned to the caller, which silently degrades into the yt-dlp path (slow) or into a generic error. The rate limit is never reported to the user or to the log at warning level.
- **Cause:** the 429 case is not part of the error vocabulary of the service, unlike the 401/403 refresh logic.
- **Trigger conditions:** ~600 api-v2 requests / 10 min (the limit yt-dlp's own extractor documents, `extractor/soundcloud.py:813–816`) — reachable during a batch import or a recommendation sweep.
- **User impact:** the provider silently degrades to yt-dlp (10–20 s per track) instead of backing off; the user sees a generic failure instead of "SoundCloud rate limit reached".
- **Evidence:**
  ```python
  158:  adapter = HTTPAdapter(pool_connections=20, pool_maxsize=20, max_retries=0)
  ...
  215:  if response.status_code not in (401, 403):
  216:      return response
  ```
- **Reproduction / verification:** probe `_sc_probe4.py` CASE H — api-v2 stub answers 429 with `Retry-After: 30`. Result: `api calls: ['https://api-v2.soundcloud.com/tracks/12345?client_id=cid']` (one call, no retry), `retry honoured? False`, and the user-facing message is a raw exception, not a rate-limit message.
- **Suggested fix:** honour `Retry-After` on 429 with a bounded back-off (and surface a "rate limited" error category).
- **Fix side effects:** a back-off inside the worker threads occupies pool slots — the 8 s UI search deadline (WN-06) would fire first, so the back-off must stay well under it or be moved off the request path.
- **Discovered by:** A

#### F-WN-20-9  [P3] — "No client id" is never surfaced as such; the api-v2 path is skipped silently

- **File:** `services/soundcloud_service.py:173–210` (`_get_client_id`), `:317–318`, `:500–502`, `:618–638`, `:977–979`
- **Confirmed:** yes
- **Description:** `_get_client_id()` returns `None` when the scrape fails or the 10 s cooldown at L209 is active. Every consumer then simply skips the api-v2 path (`if cid and t_url:` L638, `if cid:` L317/L416/L500/L977) and falls through to yt-dlp or to a generic error. Nothing tells the user that the client-id discovery failed — the most common cause of "SoundCloud stopped working" after a SoundCloud front-end change.
- **Cause:** the failure mode has no dedicated error path; it is expressed as "no fast path".
- **Trigger conditions:** the client-id scrape fails (SoundCloud changed its JS bundle, the regex at L195 no longer matches, the network is down, the cooldown at L181/L209 is active).
- **User impact:** the user gets "Поиск SoundCloud недоступен" or a raw exception instead of an actionable message, and the service permanently loses its fast path for the next 10 s after each failure.
- **Evidence:**
  ```python
  181:  if time.monotonic() < self._client_id_retry_at:
  182:      return None
  ...
  209:  self._client_id_retry_at = time.monotonic() + 10.0
  ```
  ```python
  318:  if cid:
  319:      try:
  ...
  383:  if error_callback:
  384:      error_callback('Поиск SoundCloud недоступен')
  ```
- **Reproduction / verification:** probe `_sc_probe4.py` CASE I — `_get_client_id` forced to `None`: the api-v2 branch is skipped entirely and the caller receives the generic error, with no mention of the client id.
- **Suggested fix:** distinguish "no client id" from "no results" and report it (e.g. `error_callback('Не удалось получить client_id SoundCloud')`), and log the scrape failure at warning level with the reason.
- **Fix side effects:** a "no client id" error would replace the yt-dlp fallback for users whose yt-dlp can still resolve tracks — the fallback should stay, but the message should say both.
- **Discovered by:** A

#### F-WN-20-10  [P3] — The download fallback can return a yt-dlp `.ytdl` resume file as the "downloaded track"

- **File:** `services/soundcloud_service.py:952–957`
- **Confirmed:** hypothesis (the code path is confirmed; the end-to-end trigger was not reproduced)
- **Description:** after a successful `extract_info(download=True)`, the code falls back to "the first file in the download directory whose name starts with the expected prefix and does not end in `.part`". yt-dlp writes a resume/info sidecar named `<final filename>.ytdl` (`yt_dlp/utils.py:230 → return filename + '.ytdl'`), which is **not** excluded by the `.part` test, and a `.ytdl` file is not playable audio.
- **Cause:** the suffix filter enumerates only `.part`.
- **Trigger conditions:** `prepare_filename()` returning a path that does not exist (e.g. a rename/extension mismatch between the template and the written file) while a `.ytdl` sidecar with the same prefix exists.
- **User impact:** the library row is marked "downloaded" with a non-audio file; playback of the local copy fails.
- **Evidence:**
  ```python
  955:  for f in os.listdir(output_dir):
  956:      if f.startswith(download_context.stem if download_context else f'sc_{ts}') and not f.endswith('.part'):
  957:          return os.path.join(output_dir, f)
  ```
- **Reproduction / verification:** not reproduced — it requires `prepare_filename` to disagree with the file on disk. The sidecar naming is confirmed in `yt_dlp/utils.py:230`.
- **Suggested fix:** restrict the scan to the expected extensions and exclude `.part`/`.ytdl`/`.temp`; better, return the path produced by `prepare_filename` only.
- **Fix side effects:** a genuine download whose extension differs from the template would no longer be found by the scan — that is exactly the case the scan was written for, so the extension set should be derived from the actual format instead of a hard-coded list.
- **Discovered by:** A

#### F-WN-20-11  [P3] — Every `SoundCloudService` instance allocates a 10-thread pool + a `requests.Session` and fires an eager client-id scrape; two call sites construct one per call and never shut it down

- **File:** `services/soundcloud_service.py:132` (`ThreadPoolExecutor(max_workers=10)`), `:155` (`requests.Session()`), `:169` (eager `self._executor.submit(self._get_client_id)`); callers `services/track_resolver.py:251–252`, `services/playlist_import_service.py:191–192`
- **Confirmed:** yes
- **Description:** the constructor unconditionally creates a 10-worker pool, a `requests.Session` (never closed) and starts a client-id scrape. `core/app.py:576` shuts down only the app-level instance; the instances created inside `TrackResolver._search_soundcloud` and `PlaylistImportService._enrich_soundcloud_tracks` are never shut down and their sessions are never closed.
- **Cause:** the service owns thread/socket resources but exposes no `close()`, and two call sites treat it as a cheap factory.
- **Trigger conditions:** every playlist import that has tracks without a title/artist, and every `TrackResolver` constructed without a SoundCloud service (the downloader constructs one per Spotify download, `core/downloader.py:516–522`).
- **User impact:** up to 10 idle threads and an open connection pool per import/download; each new instance also performs a client-id scrape, i.e. one extra network round trip per call.
- **Evidence:**
  ```python
  132:  self._executor = ThreadPoolExecutor(max_workers=10)
  155:  self._session = requests.Session()
  169:  self._executor.submit(self._get_client_id)
  ```
  ```python
  # services/playlist_import_service.py
  192:  svc = SoundCloudService(settings=self.settings)
  ```
- **Reproduction / verification:** read of the three call sites; no shutdown call exists for those instances (`grep` for `_executor.shutdown` finds only `core/app.py:584`).
- **Suggested fix:** give the service a `close()`/`__del__`-style teardown and reuse a single instance (the app already owns one via `core/app.py::soundcloud`) instead of constructing per call.
- **Fix side effects:** sharing one instance serialises the per-instance caches (`_related_cache`, `_track_metadata_cache`) across importers — that is the intended behaviour and the caches are lock-protected.
- **Discovered by:** A

---

### 3. Clean areas

- **`_TTLCache` (L17–49) is correct.** Verified by execution: the TTL is measured from **insert** time (`set` stores `time.time()`), a read does **not** extend it (a hit at 0.6 s with `ttl=1.0` still expires at 1.2 s); the size is hard-bounded with LRU eviction (5 sets into a 3-entry cache → `['k2','k3','k4']`); every mutation happens under a per-instance lock, so it is safe against the 10-worker pool. Expired entries are removed lazily on `get` and never purged in bulk, but the `max_entries` bound (100/200) prevents unbounded growth — so "no purge" is not a leak here. The `_track_metadata_cache` deliberately shares `BaseMusicService._cache_lock` (an `RLock`, so re-entrant and deadlock-free with `set_to_cache`/`get_from_cache`), which satisfies contract #2 (a new shared field joins the class's existing lock).
- **`_unavailable_key` (L112–123) does what it claims.** Verified: `2301904229`, `https://api-v2.soundcloud.com/tracks/2301904229` and the same URL with a `?client_id=` suffix all collapse to `sc_unavailable:2301904229`; a permalink collapses to its own lower-cased key. The memo is therefore shared across the spellings the callers actually use (`core/app.py:322–329` builds an api-v2 URL for numeric ids, `audio/engine.py:412` passes the raw `source_id`).
- **The DRM protocol rule matches yt-dlp exactly.** `_is_drm_transcoding` (`ctr-`/`cbc-` prefix) is byte-for-byte the rule in the installed `yt_dlp/extractor/soundcloud.py:309–311`; `_is_unplayable_error` matches yt-dlp's own DRM wording ("This video is DRM protected", `extractor/common.py:1228`). The DRM track is therefore never offered to the player — the primary contract of this area holds (`tests/test_soundcloud_drm_unavailable.py` passes).
- **Transient failures are not memoised.** `_media_url_is_servable` returns `True` for 5xx and for every transport exception (L565–567), and the yt-dlp path re-raises any error that is not in `_UNAVAILABLE_MARKS` (L731–733), so a socket timeout never marks a track unavailable (`tests/test_soundcloud_drm_unavailable.py::test_transient_failure_is_not_remembered` passes).
- **The single-flight bookkeeping does not leak.** `_join_request` (L594–597) registers the pending key and every exit path calls the joined callback (success **or** error), which pops `_pending_requests` — no orphaned key can suppress later searches for the same query.
- **Filename sanitisation (contract #8) is satisfied.** `download_audio_sync` never interpolates the track title/artist into a path: the names are `sc_<ts>.mp3`, `sc_<ts>.%(ext)s`, `sc_yt_<ts>.%(ext)s` (L871, L911, L931) and, with a `DownloadContext`, `download_<safe_id>_<sha16>_<id>.<ext>` (`core/download_transfer.py:20,27`). No SoundCloud title — which routinely contains `/`, `:`, `?`, `*` — ever reaches the filesystem. The fixed `.mp3` extension in `output_path` (L872) is only a fallback return value; the real path comes from `prepare_filename` first (L949–951), and the downloader re-checks `os.path.exists` (`core/downloader.py:660`), so the mismatch cannot produce a corrupt library entry.
- **The HLS contract with the proxy holds.** The provider does **not** filter `hls` presets (only `abr_*`, matching yt-dlp's "broken abr format" rule at `extractor/soundcloud.py:320–322`), so an m3u8 URL can reach the player; `core/proxy.py:1128–1152` then rewrites the manifest through `_rewrite_hls_playlist` (L396–418). `tests/test_hls_playback.py::test_soundcloud_search_metadata_resolves_hls_without_track_lookup` pins the provider half and passes.
- **The `curl_cffi` / impersonation concern does not apply to this provider.** The service never sets `impersonate` on its yt-dlp options (L243–254, L272–283), and none of the extractors it routes to request impersonation: `SoundcloudIE` (track), `SoundcloudSetIE` (playlist) and `SoundcloudSearchIE` (`scsearch`, `extractor/soundcloud.py:1316–1360`) all call `_call_api` without `impersonate`. Only `SoundcloudPagedPlaylistBaseIE` (user pages / related / track stations, `extractor/soundcloud.py:1031`) requests it — a path this service never uses. `curl_cffi` is installed in `.venv_win` (verified with `importlib.util.find_spec`), so the "no impersonate target is available" warning in `requirements.txt:11` cannot be triggered by the SoundCloud provider's own code paths.
- **Result normalisation is consistent.** Search, playlist, related and stream metadata all emit `title/artist/duration(seconds)/source='soundcloud'/source_id(str id)/source_url/cover_url`; the yt-dlp fallbacks emit the same keys (`duration` from yt-dlp is already in seconds). The `collection` (search/related) vs `tracks` (playlist) response shapes are used correctly (`search/tracks` → `collection`, `/playlists/{id}` → `tracks`).
- **The empty-query and no-hit paths are safe.** `core/api.py:2087–2088` rejects an empty query before the provider is called; a query that matches nothing yields an empty list and the yt-dlp fallback (not an exception); the search cache stores the empty list and replays it for the 300 s base-class TTL.

---

### 4. Coverage gaps

- **No live-network verification.** The machine has no working SoundCloud client id and the audit rules forbid touching the user's profile, so every finding above is either code-level or reproduced against hermetic stubs. In particular I could not measure how often the SoundCloud CDN answers 401/403/404/410 for a *playable* track (the trigger for F-WN-20-2) nor confirm the exact URL shape yt-dlp selects for a preview track (F-WN-20-5).
- **The real api-v2 payload shape for a DRM track is taken from the repository's own fixture** (`tests/test_soundcloud_drm_unavailable.py:52–63`, `"format": {"protocol": "cbc-aes"}`), not from the live API. If the live payload expresses DRM differently (e.g. only via `"policy"`), `_is_drm_transcoding` would miss it — the yt-dlp source confirms the `ctr-`/`cbc-` rule, so the risk is low, but it is unverified against the live service.
- **The multi-transcoding ordering that triggers F-WN-20-1** was reproduced with a stub payload, not with a real track; whether the live API emits `progressive → cbc-* → playable-hls` in that order is unknown.
- **I did not review the non-SoundCloud parts of the callers.** `core/api.py` (WN-03…WN-10), `core/proxy.py` (WN-11), `core/resolver.py` (WN-15), `core/downloader.py` (WN-13), `services/track_resolver.py` (WN-18) and `services/playlist_import_service.py` (WN-24) were read only for the SoundCloud call contract.
- **One caller-side defect was found and is NOT reported as a WN-20 finding:** `audio/engine.py:421` divides the provider's duration by 1000 although `services/soundcloud_service.py` returns **seconds** (L708, L337, L435, L995) — the same contract YouTube uses. The provider is correct; the division is wrong. This belongs to **WN-17 (audio engine)** and is already pinned by the `xfail(strict=True)` test `tests/test_engine_resolve.py:528–544`. Not double-reported here.
- **Not exercised:** the `android/` subtree (out of scope) and the packaged-exe paths (`sys._MEIPASS`).
- **The full test suite was not run** — only the two SoundCloud-relevant files (`18 passed`). The 429/no-client-id/geo-restriction/preview paths have no test coverage today, which is why the four defects above survived the existing suite.
