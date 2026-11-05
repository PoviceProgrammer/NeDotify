"""Artist profile matching batches credits through the canonical bridge method."""

from tests.jsdom import run_node, source


def test_artist_profile_matches_split_credits_using_backend_canonical_keys():
    run_node(r"""
import assert from 'node:assert/strict';
import vm from 'node:vm';
let calls = [];
const aliases = new Map([['artist a', 'artist-a'], ['artist-a', 'artist-a'], ['alpha', 'alpha'], ['beta', 'beta']]);
const context = vm.createContext({
  window: {pywebview: {api: {get_canonical_artist_names: async names => {
    calls.push(names);
    return names.map(name => aliases.get(String(name).toLowerCase()) || String(name).toLowerCase());
  }}}}, Set, Array, String, Promise,
});
const sourceText = SOURCE;
const start = sourceText.indexOf('const KNOWN_UNSPLITTABLE_ARTISTS') !== -1 ? sourceText.indexOf('const KNOWN_UNSPLITTABLE_ARTISTS') : sourceText.indexOf('function splitArtistCredit(');
const end = sourceText.indexOf('export async function fetchArtistTracks(');
vm.runInContext(sourceText.slice(start, end), context);
const tracks = [
  {title: 'one', artist: 'Beta feat. Artist A'},
  {title: 'two', artist: 'Someone Else'},
  {title: 'three', artist: 'Artist A & Alpha'},
];
const matched = await context.filterTracksByArtist(tracks, 'ARTIST A');
assert.deepEqual(Array.from(matched, track => track.title), ['one', 'three']);
assert.equal(calls.length, 1, 'artist credits should be resolved in one batch');
assert.deepEqual(Array.from(calls[0]), ['ARTIST A', 'Beta', 'Artist A', 'Someone Else', 'Artist A', 'Alpha']);
""".replace('SOURCE', source('artist_profile.js')))
