import re, os, collections
ROOT = r"C:\Users\Артур\NeDotify\AURA_Music_backup\AURA_Music_main"
UI = os.path.join(ROOT, "ui")
SHARED = [
 "web_new_v2/css/fonts.css","web_new_v2/css/tokens.css","web_new_v2/css/components/base.css",
 "web_new_v2/css/components/player-bar.css","web_new_v2/css/components/player-view.css",
 "web_new_v2/css/components/lyrics.css","web_new_v2/css/components/home-view.css",
 "web_new_v2/css/components/track-table.css","web_new_v2/css/themes.css",
 "web_new_v2/css/components/home-refresh.css","web_new_v2/css/components/search-refresh.css",
 "web_new_v2/css/components/library-refresh.css","web_new_v2/css/components/downloads-view.css",
 "web_new_v2/css/components/smart-playlists.css","web_new_v2/css/components/feature-tools.css",
 "web_new_v2/css/components/settings-refresh.css","web_new_v2/css/components/onboarding.css",
 "web_new_v2/css/components/profile-refresh.css","web_new_v2/css/components/window-resize.css",
 "web_new_v2/css/components/visual-polish.css","web_new_v2/css/components/ui-style-picker.css",
]
MACOS = ["MACos_ui/tokens.css","MACos_ui/interface.css","MACos_ui/settings.css","MACos_ui/library.css"]

def count(files, label):
    tot = collections.Counter()
    for rel in files:
        p = os.path.join(UI, rel.replace("/", os.sep))
        css = re.sub(r"/\*.*?\*/", " ", open(p, encoding="utf-8").read(), flags=re.S)
        bd = len(re.findall(r"(?<!-)\bbackdrop-filter\s*:", css))
        bdn = len(re.findall(r"(?<!-)\bbackdrop-filter\s*:\s*none", css))
        fbl = len(re.findall(r"(?<!-webkit-)(?<!-moz-)\bfilter\s*:\s*[^;{}]*blur\(", css))
        tot["bd"] += bd; tot["bd_none"] += bdn; tot["bd_active"] += bd - bdn; tot["fbl"] += fbl
    print(f"{label}: backdrop-filter decls={tot['bd']}  (none={tot['bd_none']}, active={tot['bd_active']})  filter:blur() decls={tot['fbl']}")
    return tot

count(SHARED, "SHARED layer")
count(MACOS, "MACos pack ")
count(SHARED + MACOS, "TOTAL      ")

print()
# distinct selectors carrying an ACTIVE shared backdrop-filter
sels = set()
for rel in SHARED:
    p = os.path.join(UI, rel.replace("/", os.sep))
    css = re.sub(r"/\*.*?\*/", " ", open(p, encoding="utf-8").read(), flags=re.S)
    i = 0; n = len(css); buf = ""
    while i < n:
        ch = css[i]
        if ch == "{":
            sel = " ".join(buf.split()); buf = ""; i += 1; start = i; d = 1
            while i < n and d > 0:
                if css[i] == "{": d += 1
                elif css[i] == "}":
                    d -= 1
                    if d == 0: break
                i += 1
            body = css[start:i]
            for m in re.finditer(r"(?<!-)\bbackdrop-filter\s*:\s*([^;{}]+)", body):
                if "none" not in m.group(1):
                    for s in sel.split(","):
                        s = " ".join(s.split())
                        if s: sels.add(s)
            i += 1; continue
        if ch == ";": buf = ""; i += 1; continue
        buf += ch; i += 1
print("distinct selectors in the SHARED layer with an active backdrop-filter:", len(sels))
for s in sorted(sels): print("   ", s)
