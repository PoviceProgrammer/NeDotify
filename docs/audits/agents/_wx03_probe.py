"""Probe: which DEFAULT_SETTINGS keys have read/write sites in Python and JS."""
import os, re, sys, io, json
sys.stdout.reconfigure(encoding='utf-8')
ROOT = r"C:\Users\Артур\NeDotify\AURA_Music_backup\AURA_Music_main"
sys.path.insert(0, ROOT)
from core.settings import DEFAULT_SETTINGS

PY_DIRS = ['core', 'audio', 'services', 'utils', 'audio']
PY_FILES = ['main.py']
JS_DIR = os.path.join(ROOT, 'ui', 'web_new_v2', 'js')

py_files = []
for d in ['core', 'audio', 'services', 'utils']:
    for dp, dn, fn in os.walk(os.path.join(ROOT, d)):
        if 'android' in dp: continue
        for f in fn:
            if f.endswith('.py'): py_files.append(os.path.join(dp, f))
py_files += [os.path.join(ROOT, f) for f in PY_FILES]
js_files = [os.path.join(JS_DIR, f) for f in os.listdir(JS_DIR) if f.endswith('.js')]
js_files.append(os.path.join(ROOT, 'ui', 'web_new_v2', 'index.html'))

def load(paths):
    out = {}
    for p in paths:
        try:
            with open(p, encoding='utf-8') as fh:
                out[p] = fh.read().splitlines()
        except Exception:
            pass
    return out

pys = load(py_files)
jss = load(js_files)

def find_py(cat, key, dotted=False):
    hits = []
    if dotted:
        pats = [re.compile(r"""settings\.get\(\s*['"]%s\.%s['"]""" % (re.escape(cat), re.escape(key)))]
    else:
        pats = [re.compile(r"""settings\.get\(\s*['"]%s['"]\s*,\s*['"]%s['"]""" % (re.escape(cat), re.escape(key))),
                re.compile(r"""settings\.get\(\s*['"]%s['"]\s*,\s*['"]%s['"]""" % (re.escape(cat), re.escape(key)))]
    for p, lines in pys.items():
        for i, l in enumerate(lines, 1):
            for pat in pats:
                if pat.search(l):
                    hits.append((os.path.relpath(p, ROOT), i, l.strip()))
                    break
    return hits

def find_py_set(cat, key, dotted=False):
    hits = []
    if dotted:
        pats = [re.compile(r"""settings\.set\(\s*['"]%s\.%s['"]""" % (re.escape(cat), re.escape(key)))]
    else:
        pats = [re.compile(r"""settings\.set\(\s*['"]%s['"]\s*,\s*['"]%s['"]""" % (re.escape(cat), re.escape(key)))]
    for p, lines in pys.items():
        for i, l in enumerate(lines, 1):
            for pat in pats:
                if pat.search(l):
                    hits.append((os.path.relpath(p, ROOT), i, l.strip()))
                    break
    return hits

def find_js(cat, key):
    hits = []
    pats = [re.compile(r"""savedSetting\(\s*['"]%s['"]\s*,\s*['"]%s['"]""" % (re.escape(cat), re.escape(key))),
            re.compile(r"""window\.settings\??\.%s\??\.%s\b""" % (re.escape(cat), re.escape(key))),
            re.compile(r"""window\.settings\[\s*['"]%s['"]\s*\]\s*\??\.\s*['"]?%s""" % (re.escape(cat), re.escape(key))),
            ]
    for p, lines in jss.items():
        for i, l in enumerate(lines, 1):
            for pat in pats:
                if pat.search(l):
                    hits.append((os.path.relpath(p, ROOT), i, l.strip()[:150]))
                    break
    return hits

def find_js_write(cat, key):
    hits = []
    pats = [re.compile(r"""saveSetting\(\s*['"]%s['"]\s*,.*?['"]%s['"]""" % (re.escape(key), re.escape(cat))),
            re.compile(r"""request\(\s*['"]save_setting['"]\s*,\s*['"]%s['"]\s*,.*?['"]%s['"]""" % (re.escape(key), re.escape(cat))),
            ]
    for p, lines in jss.items():
        for i, l in enumerate(lines, 1):
            for pat in pats:
                if pat.search(l):
                    hits.append((os.path.relpath(p, ROOT), i, l.strip()[:150]))
                    break
    return hits

rows = []
for cat, keys in DEFAULT_SETTINGS.items():
    for key in keys:
        pyr = find_py(cat, key) + find_py(cat, key, dotted=True)
        pyw = find_py_set(cat, key) + find_py_set(cat, key, dotted=True)
        jsr = find_js(cat, key)
        jsw = find_js_write(cat, key)
        rows.append(dict(cat=cat, key=key, pyr=pyr, pyw=pyw, jsr=jsr, jsw=jsw))

print("=== KEYS WITH NO PYTHON READ, NO PYTHON WRITE, NO JS READ, NO JS WRITE ===")
for r in rows:
    if not (r['pyr'] or r['pyw'] or r['jsr'] or r['jsw']):
        print(f"  DEAD  {r['cat']}.{r['key']}")

print()
print("=== KEYS READ SOMEWHERE BUT NEVER WRITTEN ANYWHERE (py or js) ===")
for r in rows:
    if (r['pyr'] or r['jsr']) and not (r['pyw'] or r['jsw']):
        print(f"  RO-ONLY  {r['cat']}.{r['key']}  pyread={len(r['pyr'])} jsread={len(r['jsr'])}")
        for h in r['pyr'][:3]: print(f"       PY {h[0]}:{h[1]}  {h[2][:110]}")
        for h in r['jsr'][:3]: print(f"       JS {h[0]}:{h[1]}  {h[2][:110]}")

print()
print("=== KEYS WRITTEN BUT NEVER READ (py or js) ===")
for r in rows:
    if (r['pyw'] or r['jsw']) and not (r['pyr'] or r['jsr']):
        print(f"  WO-ONLY  {r['cat']}.{r['key']}  pywrite={len(r['pyw'])} jswrite={len(r['jsw'])}")
        for h in r['pyw'][:3]: print(f"       PY {h[0]}:{h[1]}  {h[2][:110]}")
        for h in r['jsw'][:3]: print(f"       JS {h[0]}:{h[1]}  {h[2][:110]}")

print()
print("=== KEYS WITH NO JS CONTROL AT ALL (no js read, no js write) ===")
for r in rows:
    if not r['jsr'] and not r['jsw']:
        print(f"  NO-UI  {r['cat']}.{r['key']}   pyread={len(r['pyr'])} pywrite={len(r['pyw'])}")
        for h in r['pyr'][:2]: print(f"       PY {h[0]}:{h[1]}  {h[2][:110]}")
        for h in r['pyw'][:2]: print(f"       PYset {h[0]}:{h[1]}  {h[2][:110]}")
