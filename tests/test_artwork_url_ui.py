"""Managed artwork uses same-origin, token-free routes in the WebView."""

from tests.jsdom import run_node, source


def test_managed_cover_uses_same_origin_route_even_before_proxy_info_arrives():
    run_node(r"""
import assert from 'node:assert/strict';
import vm from 'node:vm';
const context = vm.createContext({
  window: {PROXY_PORT: 49123, PROXY_TOKEN: 'very-secret-token', settings: {}},
  URL, encodeURIComponent,
});
const code = SOURCE;
const start = code.indexOf('export function getCoverUrl(');
const end = code.indexOf('export function formatArtistNames(');
vm.runInContext(code.slice(start, end).replaceAll('export ', ''), context);
const path = 'C:/Users/Артур/.nedotify/covers/обложка.jpg';
const expected = `./api/cover?path=${encodeURIComponent(path)}`;
assert.equal(context.getCoverUrl({cover_path: path}), expected);
context.window.PROXY_PORT = undefined;
context.window.PROXY_TOKEN = undefined;
assert.equal(context.getCoverUrl({cover_path: path}), expected, 'cold start must not produce an empty image URL');
assert.ok(!context.getCoverUrl({cover_path: path}).includes('very-secret-token'));
assert.equal(context.getCoverUrl({cover_path: 'C:/app/ui/web_new_v2/covers/cover.png'}), './covers/cover.png');
assert.equal(context.getCoverUrl({cover_path: 'C:/app/ui/web_new_v2/covers/../secret.png'}), `./api/cover?path=${encodeURIComponent('C:/app/ui/web_new_v2/covers/../secret.png')}`);
""".replace('SOURCE', source('utils.js')))


def test_profile_avatar_uses_same_origin_route_without_proxy_bearer():
    run_node(r"""
import assert from 'node:assert/strict';
import vm from 'node:vm';
const image = {src: '', style: {display: ''}};
const icon = {style: {display: ''}};
const edit = {open: false};
const input = {value: ''};
const nodes = new Map([
  ['profile-display-name', {textContent: ''}], ['profile-name-input', input],
  ['profile-edit-dialog', edit], ['profile-date-joined', {textContent: ''}],
  ['profile-avatar-img', image], ['profile-avatar-icon', icon],
]);
const context = vm.createContext({
  window: {PROXY_PORT: 49123, PROXY_TOKEN: 'very-secret-token', settings: {personalization: {avatar_path: 'C:/Users/Артур/.nedotify/avatars/личный.png', nickname: 'Имя'}}},
  document: {getElementById: id => nodes.get(id)},
  text(id, value) {nodes.get(id).textContent = value;},
  encodeURIComponent,
});
const code = SOURCE;
const start = code.indexOf('function refreshIdentity()');
const end = code.indexOf('export async function loadProfile()', start);
vm.runInContext(code.slice(start, end), context);
context.refreshIdentity();
assert.equal(image.src, `./api/avatar?path=${encodeURIComponent('C:/Users/Артур/.nedotify/avatars/личный.png')}`);
assert.ok(!image.src.includes('very-secret-token'));
""".replace('SOURCE', source('profile.js')))
