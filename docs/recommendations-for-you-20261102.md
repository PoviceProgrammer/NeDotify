# Windows «Для тебя»: Riff source audit and discovery repair

Reference: rootscripts/riff commit
`860b3276b74b3904ec6d3dcbdf3e12209022c18b`, fetched on 2026-11-02 into
`../fix/riff-reference-20261102`. Reviewed actual server and renderer source,
package.json and MIT license; no Electron/Node dependency is added to NeDotify.

## Source comparison

Riff's `src/server/server.js` implements `ytMixTracks`, `dzArtistId`,
`dzRelatedTracks`, `dzRadioTracks`, `gatherCandidates`, `rankCandidates`, and
`recommendVibeTracks`. Favorites and listening history supply weighted seeds.
Up to four seeds fan out into YouTube Mix search, Deezer artist radio, and top
tracks of related artists. Ranking excludes heard tracks and negative feedback,
combines corroborating seeds and balances artists. Metadata is resolved to a
playable source separately. Its caches share in-flight operations.

Primary reference:
[Riff recommendation source](https://github.com/rootscripts/riff/blob/860b3276b74b3904ec6d3dcbdf3e12209022c18b/src/server/server.js#L1187).
MIT attribution is retained in `licenses/RIFF-MIT.txt`. Python adaptations use
NeDotify's existing providers, deadlines, caches and playback bridge.

## Reproduced gaps

The Windows frontend passes a generated mix's actual `tracks` array to playback;
it does not replace the array with a saved playlist. A shipped-JavaScript
regression now pins this for both SoundCloud and Deezer metadata.

The backend previously requested related-radio candidates only for native
YouTube and SoundCloud seed identities. Imported Spotify-style and local seeds
never reached that path. With unavailable/empty radio results, generic artist
search and familiar-library fallback dominated. Daily artist buckets then
filtered the same small shared feed plus familiar tracks, including artists
for whom no new candidates had been requested.

`test_imported_playlist_seeds_reach_real_related_discovery_without_api_keys`
first failed on the shipped backend. A separate negative fixture verifies that
saved playlist tracks cannot be labelled «Открытия для вас».

User library data is read-only; live probes use an isolated copy and report
metadata/counts rather than credentials or signed URLs.

## Changes

Imported/local seeds can reach native radio via a verified metadata match.
Daily buckets retain candidates recommended from their seed artists, including
new performers; they share a bounded candidate batch and a 17-second overall
budget. A daily mix requires unheard material and places available unheard
recordings at the beginning, so its covers reflect the generated music.
«Любимые и знакомые» remains explicitly familiar.

Recommendation-only identity normalization recognizes explicitly credited
reuploads across sources while retaining remix/version and different-artist
distinctions. A cached, lightweight identity set covers the full saved library,
independently of the bounded taste/history payload. Negative feedback and source
opt-outs continue to apply; source switches invalidate discovery caches.

Native SoundCloud seeds now fetch/cache actual recording metadata before using
their related graph. A title/version mismatch or incompatible duration rejects
the stored ID; metadata-based catalogue resolution can recover the right seed.
Uploader differences remain supported when title and duration corroborate the
recording. Missing duration requires matching recording credits as well. No
library rows are rewritten. The exact wrong-ID regression failed before the fix
(5 failures / 3 passing positive controls), then all eight cases passed.

Deezer radio and related-artist metadata follow the Riff approach through the
existing four-worker candidate pool. An artist ID must be confirmed by an exact
seed recording title/duration match; the first same-name search hit is not
trusted. Ordinary search terms are used because the live structured artist/
track query returned no matches for a real public control recording. Actual
response metadata is verified after searching. Streams are resolved only on
playback, using the existing full-track provider path, with no preview audio.

YouTube Radio subtitle engagement counters such as «Отметок Нравится» are no
longer interpreted as additional artist names. Actual channel IDs remain
authoritative. No machine-learning models or runtime dependencies were added.

## Live results

Initial probe: `tools/bench/results/discovery-baseline-20261102-153951.json`.
Both primary providers worked (20 related metadata entries each); three daily
mixes contained zero new tracks. Counts below mean total tracks / unheard
compositions relative to the saved library, not a promise of semantic relevance.

| Mix | Before | After |
| --- | ---: | ---: |
| Любимые и знакомые | 12 / 0 | 12 / 0 |
| Открытия для вас | 12 / 12 | 12 / 12 |
| Ежедневный микс 1 | 2 / 0 | 7 / 5 |
| Ежедневный микс 2 | 6 / 1 | 9 / 4 |
| Ежедневный микс 3 | 3 / 0 | 6 / 3 |
| Ежедневный микс 4 | 4 / 0 | 12 / 12 |

Final headless probe: `discovery-after-20261102-211101.json`. It used 66 known
compositions, fingerprint
`d94f81921ea02c89065e9fa23c591fb1890859faa45933de91c190b214be7995`.
Cold mix generation ran before provider warmup: 4015 ms wall / 594 ms process
CPU. «Открытия» contained YouTube 3, SoundCloud 6 and Deezer 3. The preceding
final-code probe (`211007`) measured 4269 ms wall / 688 ms CPU. These are two
observations, not a before/after speedup claim; provider graphs change over time.
Verified Deezer discovery returned 29 metadata tracks in the final probe; a separate
Daft Punk control returned 30 in 1141 ms
(`discovery-catalogue-control-20261102-155635.json`).

Before the user's subsequent instruction not to launch the application, native
checks in both Windows skins completed: clicking the actual «Открытия» card
queued its exact 12 tracks in order and produced advancing decoded audio.
Artifacts: `recommendation-native-20261102-155415` and `155431`. These checks
preceded the last Deezer search-query fix; the final three-source composition
was verified headlessly. No further application window was launched after the
user's instruction.

The unexpected religious recording was traced to a mislabeled stored seed:
SoundCloud `715124080` was labelled The Weeknd / Blinding Lights locally, while
its actual metadata identifies a 6896-second recording by another uploader.
`recommendation-outlier-20261102-160234.json` pins both actual metadata and its
related graph. The final probe records every requested SC graph ID and every
mix recording ID: that seed's graph is no longer requested, and its unrelated
recommendation `1582443743` is absent from all generated mixes. A correctly
identified The Weeknd seed (`718846078`) supplies the replacement graph.

The checks establish new content, provenance, identity checks and queue fidelity;
they do not establish ideal human taste matching. No arbitrary artist/topic
blacklist was introduced. Final-code validation is headless; GPU/RAM savings or
fresh native playback validation are not claimed.

Final validation: default pytest suite **2742 passed, 9 skipped, 1 deselected**
in 133.75 seconds. Source inventory, dependency consistency (`pip check`) and
scoped whitespace checks passed. Live-report assertions confirm exclusion of
the wrong seed graph and its unrelated recording, 12 unheard discoveries and
unheard material in every daily mix. No application was launched for these
final checks, in accordance with the user's instruction.
