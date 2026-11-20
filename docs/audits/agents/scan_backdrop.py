import re, os, collections

ROOT = r"C:\Users\Артур\NeDotify\AURA_Music_backup\AURA_Music_main"
UI = os.path.join(ROOT, "ui")

LINKED = [
    "web_new_v2/css/fonts.css","web_new_v2/css/tokens.css",
    "web_new_v2/css/components/base.css","web_new_v2/css/components/player-bar.css",
    "web_new_v2/css/components/player-view.css","web_new_v2/css/components/lyrics.css",
    "web_new_v2/css/components/home-view.css","web_new_v2/css/components/track-table.css",
    "web_new_v2/css/themes.css","web_new_v2/css/components/home-refresh.css",
    "web_new_v2/css/components/search-refresh.css","web_new_v2/css/components/library-refresh.css",
    "web_new_v2/css/components/downloads-view.css","web_new_v2/css/components/smart-playlists.css",
    "web_new_v2/css/components/feature-tools.css","web_new_v2/css/components/settings-refresh.css",
    "web_new_v2/css/components/onboarding.css","web_new_v2/css/components/profile-refresh.css",
    "web_new_v2/css/components/window-resize.css","web_new_v2/css/components/visual-polish.css",
    "web_new_v2/css/components/ui-style-picker.css","MACos_ui/tokens.css",
    "MACos_ui/interface.css","MACos_ui/settings.css","MACos_ui/library.css",
]

def strip_comments(css):
    return re.sub(r"/\*.*?\*/", " ", css, flags=re.S)

print("=== backdrop-filter / filter:blur DECLARATIONS (selector | value | file:line) ===")
rows = []
for p in LINKED:
    fp = os.path.join(UI, p.replace("/", os.sep))
    raw = open(fp, encoding="utf-8").read()
    css = strip_comments(raw)
    # find rule blocks
    i = 0; n = len(css); buf = ""
    while i < n:
        ch = css[i]
        if ch == "{":
            sel = " ".join(buf.split()); buf = ""
            start = i
            d = 1; i += 1
            while i < n and d > 0:
                if css[i] == "{": d += 1
                elif css[i] == "}":
                    d -= 1
                    if d == 0: break
                i += 1
            body = css[start:i]
            bl = raw[:start].count("\n") + 1
            for m in re.finditer(r"(?<!-)\bbackdrop-filter\s*:\s*([^;{}]+)", body):
                v = " ".join(m.group(1).split())
                rows.append((p, bl, sel, "backdrop-filter", v))
            for m in re.finditer(r"(?<!-webkit-)(?<!-moz-)\bfilter\s*:\s*([^;{}]+)", body):
                v = " ".join(m.group(1).split())
                if "blur" in v:
                    rows.append((p, bl, sel, "filter:blur", v))
            i += 1
            continue
        if ch == ";": buf = ""; i += 1; continue
        buf += ch; i += 1

macos = [r for r in rows if r[0].startswith("MACos_ui")]
nonmac = [r for r in rows if not r[0].startswith("MACos_ui")]
print(f"TOTAL backdrop/filter-blur decls: {len(rows)}  (MACos_ui-scoped: {len(macos)}, shared: {len(nonmac)})")
active = [r for r in nonmac if "none" not in r[4]]
print(f"shared declarations that are NOT `none`: {len(active)}")
print()
for p, bl, sel, kind, v in rows:
    tag = "MACOS" if p.startswith("MACos_ui") else "SHARED"
    print(f"  [{tag}] {p.replace('web_new_v2/css/components/','c/').replace('web_new_v2/css/','w/').replace('MACos_ui/','m/')}:{bl}  {kind}: {v}")
    print(f"        sel: {sel[:160]}")
