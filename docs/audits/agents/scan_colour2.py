import re, os, collections
ROOT = r"C:\Users\Артур\NeDotify\AURA_Music_backup\AURA_Music_main"
UI = os.path.join(ROOT, "ui")
FILES = [
 "web_new_v2/css/components/base.css","web_new_v2/css/components/player-bar.css",
 "web_new_v2/css/components/player-view.css","web_new_v2/css/components/lyrics.css",
 "web_new_v2/css/components/home-view.css","web_new_v2/css/components/track-table.css",
 "web_new_v2/css/components/home-refresh.css","web_new_v2/css/components/search-refresh.css",
 "web_new_v2/css/components/library-refresh.css","web_new_v2/css/components/settings-refresh.css",
 "web_new_v2/css/components/onboarding.css","web_new_v2/css/components/profile-refresh.css",
 "web_new_v2/css/components/visual-polish.css",
 "MACos_ui/interface.css","MACos_ui/settings.css","MACos_ui/library.css","MACos_ui/tokens.css",
]
WHITE = re.compile(r"rgba?\(\s*255\s*,\s*255\s*,\s*255|#fff\b|#ffffff\b", re.I)
hard = 0
soft = 0
bgs = 0
for rel in FILES:
    p = os.path.join(UI, rel.replace("/", os.sep))
    css = re.sub(r"/\*.*?\*/", " ", open(p, encoding="utf-8").read(), flags=re.S)
    for m in re.finditer(r"(?<!-)\bcolor\s*:\s*([^;{}]+)", css):
        v = m.group(1)
        if not WHITE.search(v): continue
        if "var(" in v: soft += 1
        else: hard += 1
    for m in re.finditer(r"(?<!-)\bbackground(?:-color)?\s*:\s*([^;{}]+)", css):
        if WHITE.search(m.group(1)): bgs += 1
print("white-ish `color:` declarations with a var() fallback :", soft)
print("white-ish `color:` declarations with NO var() at all   :", hard)
print("white-ish `background` declarations                    :", bgs)
