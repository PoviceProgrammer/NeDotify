import re, os, collections
ROOT = r"C:\Users\Артур\NeDotify\AURA_Music_backup\AURA_Music_main"
UI = os.path.join(ROOT, "ui")
FILES = [
    "web_new_v2/css/components/base.css","web_new_v2/css/components/player-bar.css",
    "web_new_v2/css/components/player-view.css","web_new_v2/css/components/lyrics.css",
    "web_new_v2/css/components/home-view.css","web_new_v2/css/components/track-table.css",
    "web_new_v2/css/components/home-refresh.css","web_new_new" , # placeholder
]
FILES = [f for f in FILES if f in ("web_new_v2/css/components/base.css","web_new_v2/css/components/player-bar.css",
    "web_new_v2/css/components/player-view.css","web_new_v2/css/components/lyrics.css",
    "web_new_v2/css/components/home-view.css","web_new_v2/css/components/track-table.css",
    "web_new_v2/css/components/home-refresh.css","web_new_v2/css/components/search-refresh.css",
    "web_new_v2/css/components/library-refresh.css","web_new_v2/css/components/settings-refresh.css",
    "web_new_v2/css/components/onboarding.css","web_new_v2/css/components/profile-refresh.css",
    "web_new_v2/css/components/visual-polish.css","web_new_v2/css/components/track-table.css")]

WHITE = re.compile(r"rgba?\(\s*255\s*,\s*255\s*,\s*255|#fff\b|#ffffff\b", re.I)
total_color = 0
raw_white_color = 0
raw_white_bg = 0
per_file = collections.Counter()
samples = []
for rel in FILES:
    p = os.path.join(UI, rel.replace("/", os.sep))
    css = re.sub(r"/\*.*?\*/", " ", open(p, encoding="utf-8").read(), flags=re.S)
    for m in re.finditer(r"(?<!-)\b(color|background(?:-color)?|border(?:-[a-z]+-color)?)\s*:\s*([^;{}]+)", css):
        prop, val = m.group(1), m.group(2)
        total_color += 1
        if WHITE.search(val):
            if prop == "color":
                raw_white_color += 1; per_file[rel] += 1
                if len(samples) < 12: samples.append((rel, prop, " ".join(val.split())[:70]))
            elif "background" in prop:
                raw_white_bg += 1
print("component-layer colour/background/border declarations scanned:", total_color)
print("raw WHITE colour declarations (not routed through --text-*):", raw_white_color)
print("raw WHITE background declarations:", raw_white_bg)
print()
for f, n in per_file.most_common():
    print(f"  {n:>4}  {f}")
print()
print("samples:")
for s in samples: print("   ", s)

# token usage vs raw
tok = 0
for rel in FILES:
    p = os.path.join(UI, rel.replace("/", os.sep))
    css = re.sub(r"/\*.*?\*/", " ", open(p, encoding="utf-8").read(), flags=re.S)
    tok += len(re.findall(r"var\(\s*--", css))
print()
print("var(--token) references in the component layer:", tok)

# important count per file (non-macOS)
print()
imp = 0
for rel in FILES:
    p = os.path.join(UI, rel.replace("/", os.sep))
    css = re.sub(r"/\*.*?\*/", " ", open(p, encoding="utf-8").read(), flags=re.S)
    n = css.count("!important")
    imp += n
    print(f"  {n:>4}  {rel}")
print("  component-layer !important total:", imp)
