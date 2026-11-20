"""WX-03: enumerate every settings key the UI can WRITE, with the value expression."""
import re, sys, os
sys.stdout.reconfigure(encoding='utf-8')
ROOT = r'C:\Users\Артур\NeDotify\AURA_Music_backup\AURA_Music_main'
sys.path.insert(0, ROOT)
from core.settings import DEFAULT_SETTINGS

JS = os.path.join(ROOT, 'ui', 'web_new_v2', 'js')
files = [os.path.join(JS, f) for f in os.listdir(JS) if f.endswith('.js')]

PATS = [
    # saveSetting('key', VALUE, 'category')
    (re.compile(r"saveSetting\(\s*'([^']+)'\s*,\s*([^,]+?)\s*,\s*'([^']+)'"), 'saveSetting'),
    (re.compile(r"api\.save_setting\(\s*'([^']+)'\s*,\s*([^,]+?)\s*,\s*'([^']+)'"), 'api.save_setting'),
    (re.compile(r"api\(\s*'save_setting'\s*,\s*'([^']+)'\s*,\s*([^,]+?)\s*,\s*'([^']+)'"), 'api(save_setting)'),
    (re.compile(r"request\(\s*'save_setting'\s*,\s*'([^']+)'\s*,\s*([^,]+?)\s*,\s*'([^']+)'"), 'request(save_setting)'),
    # setupToggle('id', 'key', 'category')
    (re.compile(r"setupToggle\(\s*'[^']+'\s*,\s*'([^']+)'\s*,\s*'([^']+)'"), 'setupToggle'),
    # setupSlider('id', 'key', 'category', ...)
    (re.compile(r"setupSlider\(\s*'[^']+'\s*,\s*'([^']+)'\s*,\s*'([^']+)'"), 'setupSlider'),
    # setupCardGroup('id', 'key', ...)  -> always category 'optimization' or 'player'
    (re.compile(r"setupCardGroup\(\s*'[^']+'\s*,\s*'([^']+)'"), 'setupCardGroup'),
]

writes = {}
for p in files:
    for i, line in enumerate(open(p, encoding='utf-8').read().splitlines(), 1):
        for pat, kind in PATS:
            for m in pat.finditer(line):
                if kind == 'setupCardGroup':
                    cat = 'optimization' if 'opt-' in m.group(0) else 'player'
                    key, val = m.group(1), 'card.dataset.val (string)'
                elif kind in ('setupToggle', 'setupSlider'):
                    key, cat, val = m.group(1), m.group(2), ('boolean isOn' if kind == 'setupToggle' else 'Number(slider.value)')
                else:
                    key, val, cat = m.group(1), m.group(2).strip(), m.group(3)
                writes.setdefault((cat, key), []).append(
                    (os.path.basename(p), i, kind, val[:70]))

print('=== UI-WRITTEN keys NOT present in DEFAULT_SETTINGS ===')
for (cat, key), v in sorted(writes.items()):
    if cat not in DEFAULT_SETTINGS or key not in DEFAULT_SETTINGS.get(cat, {}):
        print('  %-22s %-28s <- %s:%d  (%s)  value=%s' % (cat, key, v[0][0], v[0][1], v[0][2], v[0][3]))

print()
print('=== DEFAULT_SETTINGS keys with NO UI writer ===')
for cat, keys in DEFAULT_SETTINGS.items():
    for key in keys:
        if (cat, key) not in writes:
            print('  NO-UI-WRITE  %s.%s' % (cat, key))

print()
print('=== UI writers per declared key (count) ===')
for cat, keys in DEFAULT_SETTINGS.items():
    for key in keys:
        if (cat, key) in writes:
            v = writes[(cat, key)]
            kinds = sorted(set(x[2] for x in v))
            vals = sorted(set(x[3] for x in v))
            print('  %-22s %-30s %-28s %s' % (cat, key, ','.join(kinds), ' | '.join(vals)))
