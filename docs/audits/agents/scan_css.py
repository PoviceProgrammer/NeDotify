import re, os, json, collections

ROOT = r"C:\Users\Артур\NeDotify\AURA_Music_backup\AURA_Music_main"
UI = os.path.join(ROOT, "ui")

LINKED = [
    "web_new_v2/css/fonts.css",
    "web_new_v2/css/tokens.css",
    "web_new_v2/css/components/base.css",
    "web_new_v2/css/components/player-bar.css",
    "web_new_v2/css/components/player-view.css",
    "web_new_v2/css/components/lyrics.css",
    "web_new_v2/css/components/home-view.css",
    "web_new_v2/css/components/track-table.css",
    "web_new_v2/css/themes.css",
    "web_new_v2/css/components/home-refresh.css",
    "web_new_v2/css/components/search-refresh.css",
    "web_new_v2/css/components/library-refresh.css",
    "web_new_v2/css/components/downloads-view.css",
    "web_new_v2/css/components/smart-playlists.css",
    "web_new_v2/css/components/feature-tools.css",
    "web_new_v2/css/components/settings-refresh.css",
    "web_new_v2/css/components/onboarding.css",
    "web_new_v2/css/components/profile-refresh.css",
    "web_new_v2/css/components/window-resize.css",
    "web_new_v2/css/components/visual-polish.css",
    "web_new_v2/css/components/ui-style-picker.css",
    "MACos_ui/tokens.css",
    "MACos_ui/interface.css",
    "MACos_ui/settings.css",
    "MACos_ui/library.css",
]

def strip_comments(css):
    css = re.sub(r"/\*.*?\*/", " ", css, flags=re.S)
    return css

def strip_strings(css):
    # remove url() contents and quoted strings for selector parsing
    return css

print("=== LINKED FILE SIZES ===")
total = 0
for p in LINKED:
    fp = os.path.join(UI, p.replace("/", os.sep))
    sz = os.path.getsize(fp)
    total += sz
    print(f"{p:55s} {sz:>9,}")
print(f"{'TOTAL LINKED CSS':55s} {total:>9,} bytes = {total/1024:.1f} KB")

# url() analysis
print()
print("=== url() OCCURRENCES ===")
allurls = []
for p in LINKED:
    fp = os.path.join(UI, p.replace("/", os.sep))
    css = open(fp, encoding="utf-8").read()
    for m in re.finditer(r"url\(\s*([^)]*)\)", css):
        allurls.append((p, m.group(1).strip()))
from collections import Counter
c = Counter(u for _, u in allurls)
for u, n in c.most_common():
    ext = u if u.startswith("http") or u.startswith("//") or u.startswith("data:") or u.startswith("javascript") else "<local>"
    print(f"  {n:>4}x  {u}   [{ext}]")

print()
print("=== DANGEROUS CSS VECTORS ===")
for p in LINKED:
    fp = os.path.join(UI, p.replace("/", os.sep))
    css = open(fp, encoding="utf-8").read()
    for pat in [r"expression\s*\(", r"behavior\s*:", r"javascript\s*:", r"-moz-binding", r"@import"]:
        for m in re.finditer(pat, css):
            line = css[:m.start()].count("\n") + 1
            print(f"  {p}:{line}  {pat}  -> {css[m.start():m.start()+70]!r}")

print()
print("=== RAW HEX / RGB LITERALS PER FILE (components + MACos_ui) ===")
hexpat = re.compile(r"#[0-9a-fA-F]{3,8}\b")
for p in LINKED:
    fp = os.path.join(UI, p.replace("/", os.sep))
    css = open(fp, encoding="utf-8").read()
    nocomment = strip_comments(css)
    hexes = hexpat.findall(nocomment)
    rgbs = re.findall(r"rgba?\(", nocomment)
    varrgb = re.findall(r"var\(\s*--[\w-]+\s*,\s*#", nocomment)
    print(f"{p:55s} hex={len(hexes):>4}  rgb()={len(rgbs):>4}  var-with-hex-fallback={len(varrgb):>4}")

print()
print("=== TOKENS DECLARED PER FILE (custom properties) ===")
for p in LINKED:
    fp = os.path.join(UI, p.replace("/", os.sep))
    css = open(fp, encoding="utf-8").read()
    decls = re.findall(r"(--[\w-]+)\s*:", css)
    dup = [k for k, v in Counter(decls).items() if v > 1]
    print(f"{p:55s} decls={len(decls):>4} distinct={len(set(decls)):>4} redeclared={len(dup)}")

print()
print("=== SELECTOR EXTRACTOR ===")
def selectors(css):
    css = strip_comments(css)
    out = []
    depth = 0
    buf = ""
    i = 0
    n = len(css)
    while i < n:
        ch = css[i]
        if ch == "{":
            sel = buf.strip()
            if sel and not sel.startswith("@"):
                for s in sel.split(","):
                    s = " ".join(s.split())
                    if s:
                        out.append(s)
            buf = ""
            depth += 1
            # skip block content
            d = 1
            i += 1
            while i < n and d > 0:
                if css[i] == "{":
                    d += 1
                elif css[i] == "}":
                    d -= 1
                i += 1
            continue
        if ch == ";":
            buf = ""
            i += 1
            continue
        buf += ch
        i += 1
    return out

sel_map = {}
for p in LINKED:
    fp = os.path.join(UI, p.replace("/", os.sep))
    css = open(fp, encoding="utf-8").read()
    sel_map[p] = selectors(css)

base = set(sel_map["web_new_v2/css/components/base.css"])
print("base.css distinct selectors:", len(base))
print()
print("=== SELECTORS ALSO DEFINED IN *-refresh.css / other component files ===")
for p in LINKED:
    if p in ("web_new_v2/css/components/base.css", "web_new_v2/css/fonts.css",
             "web_new_v2/css/tokens.css", "web_new_v2/css/themes.css",
             "MACos_ui/tokens.css"):
        continue
    s = set(sel_map[p])
    both = s & base
    print(f"{p:55s} total={len(s):>4}  also-in-base={len(both):>4}  ({100*len(both)/max(1,len(s)):.0f}%)")

print()
print("=== ALL pairwise overlaps among component files (top) ===")
comp = [p for p in LINKED if "components/" in p]
allsel = collections.defaultdict(set)
for p in comp:
    allsel[p] = set(sel_map[p])
pairs = []
for i in range(len(comp)):
    for j in range(i+1, len(comp)):
        inter = allsel[comp[i]] & allsel[comp[j]]
        if inter:
            pairs.append((len(inter), comp[i], comp[j], inter))
pairs.sort(reverse=True)
for n, a, b, inter in pairs[:25]:
    print(f"  {n:>4}  {a}  <->  {b}")
    if n <= 12:
        for s in sorted(inter):
            print(f"          {s}")
