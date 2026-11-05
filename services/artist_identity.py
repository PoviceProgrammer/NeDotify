"""Conservative artist aliases; no automatic transliteration of unrelated names."""
import unicodedata
import re
import hashlib
import threading
import weakref

DEFAULT_ALIASES = {'фараон': 'PHARAOH', 'pharaon': 'PHARAOH'}
_alias_cache = weakref.WeakKeyDictionary()
_alias_lock = threading.RLock()


def name_key(value):
    return ' '.join(unicodedata.normalize('NFKC', str(value or '')).casefold().replace('ё', 'е').split())


def artist_aliases(settings=None):
    revision = getattr(settings, 'revision', None) if settings else None
    if settings is not None and isinstance(revision, int):
        with _alias_lock:
            cached = _alias_cache.get(settings)
            if cached and cached[0] == revision:
                return cached[1]
    aliases = dict(DEFAULT_ALIASES)
    configured = settings.get('personalization', 'artist_aliases', {}) if settings else {}
    if isinstance(configured, dict):
        aliases.update({name_key(k): str(v).strip() for k, v in configured.items()
                        if name_key(k) and isinstance(v, str) and v.strip()})
    bindings = settings.get('personalization', 'artist_bindings', {}) if settings else {}
    if isinstance(bindings, dict):
        for key, binding in bindings.items():
            if not isinstance(binding, dict):
                continue
            refs = binding.get('catalog_ids') or {}
            if not isinstance(refs, dict):
                continue
            source = next((s for s in ('youtube', 'itunes', 'deezer') if refs.get(s)), None)
            if source:
                digest = hashlib.sha256(str(refs[source]).encode()).hexdigest()
                if binding.get('context'):
                    lookup = '@context:' + hashlib.sha256(key.encode()).hexdigest()
                    aliases[lookup] = '@catalog:' + source + ':' + digest
                else:
                    canonical = binding.get('canonical_name')
                    if canonical and isinstance(canonical, str) and canonical.strip():
                        aliases[name_key(key)] = str(canonical).strip()
    if settings is not None and isinstance(revision, int):
        with _alias_lock:
            _alias_cache[settings] = (revision, aliases)
    return aliases


def binding_key(name, context=None):
    context = context if isinstance(context, dict) else {}
    source, sid = context.get('source'), context.get('source_id')
    return name_key(name) + ('\0' + str(source) + '\0' + str(sid) if source and sid else '')


def artist_binding(settings, name, context=None):
    bindings = settings.get('personalization', 'artist_bindings', {}) if settings else {}
    if not isinstance(bindings, dict):
        return None
    return bindings.get(binding_key(name, context)) or bindings.get(name_key(name))


def canonical_artist(value, aliases=None):
    if not value:
        return ''
    str_val = str(value)
    if str_val.startswith('@catalog:') or str_val.startswith('@context:'):
        return ''
    key, visited = name_key(value), set()
    aliases = DEFAULT_ALIASES if aliases is None else aliases
    last_canonical = key
    while key in aliases and key not in visited:
        visited.add(key)
        target = aliases[key]
        if not target or not isinstance(target, str):
            break
        if target.startswith('@catalog:') or target.startswith('@context:'):
            break
        last_canonical = name_key(target)
        key = last_canonical
    return last_canonical


def track_key(track, aliases=None):
    title = re.sub(r'\s*[\[(](?:official(?: music)? (?:video|audio)|lyrics?|visuali[sz]er)[\])]\s*',
                   ' ', str(track.get('title') or ''), flags=re.I)
    context = {'source': track.get('source'), 'source_id': track.get('source_id') or track.get('id')}
    scoped = '@context:' + hashlib.sha256(binding_key(track.get('artist'), context).encode()).hexdigest()
    artist = (aliases or {}).get(scoped) or canonical_artist(track.get('artist'), aliases)
    return artist, name_key(title)
