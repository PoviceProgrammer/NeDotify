import re, sys, os
sys.stdout.reconfigure(encoding='utf-8')
ROOT = r'C:\Users\Артур\NeDotify\AURA_Music_backup\AURA_Music_main'
sys.path.insert(0, ROOT)
from core.settings import DEFAULT_SETTINGS
files = []
for d in ['core', 'audio', 'services', 'utils']:
    for dp, dn, fn in os.walk(os.path.join(ROOT, d)):
        for f in fn:
            if f.endswith('.py'):
                files.append(os.path.join(dp, f))
files.append(os.path.join(ROOT, 'main.py'))
text = {p: open(p, encoding='utf-8').read() for p in files}
for cat, keys in DEFAULT_SETTINGS.items():
    for key in keys:
        gp = re.compile(r'\.get\(\s*[\'"]%s[\'"]\s*,\s*[\'"]%s[\'"]' % (re.escape(cat), re.escape(key)))
        sp = re.compile(r'\.set\(\s*[\'"]%s[\'"]\s*,\s*[\'"]%s[\'"]' % (re.escape(cat), re.escape(key)))
        gd = re.compile(r'\.get\(\s*[\'"]%s\.%s[\'"]' % (re.escape(cat), re.escape(key)))
        sd = re.compile(r'\.set\(\s*[\'"]%s\.%s[\'"]' % (re.escape(cat), re.escape(key)))
        r = []
        w = []
        for p, t in text.items():
            rel = os.path.relpath(p, ROOT)
            for i, l in enumerate(t.splitlines(), 1):
                if gp.search(l) or gd.search(l):
                    r.append(rel + ':' + str(i))
                if sp.search(l) or sd.search(l):
                    w.append(rel + ':' + str(i))
        print('%-38s R=%-30s W=%s' % (cat + '.' + key, ','.join(r[:3]) or '-', ','.join(w[:3]) or '-'))
