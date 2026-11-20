import re, os, collections

ROOT = r"C:\Users\Артур\NeDotify\AURA_Music_backup\AURA_Music_main"
UI = os.path.join(ROOT, "ui")

SHARED = [
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
    "web_new_v2/css/components/ui-style-picker.css",
]
MACOS = ["MACos_ui/tokens.css","MACos_ui/interface.css","MACos_ui/settings.css","MACos_ui/library.css"]

def strip_comments(css):
    return re.sub(r"/\*.*?\*/", " ", css, flags=re.S)

def parse(css):
    css = strip_comments(css)
    out = []
    i = 0; n = len(css); buf = ""
    while i < n:
        ch = css[i]
        if ch == "{":
            sel = " ".join(buf.split()); buf = ""
            i += 1; start = i; d = 1
            while i < n and d > 0:
                if css[i] == "{": d += 1
                elif css[i] == "}":
                    d -= 1
                    if d == 0: break
                i += 1
            body = css[start:i]
            decls = []
            for m in re.finditer(r"([-a-zA-Z]+)\s*:\s*([^;{}]+)(;|(?=\}))", body):
                decls.append((m.group(1).strip(), " ".join(m.group(2).split())))
            for s in sel.split(","):
                s = " ".join(s.split())
                if s: out.append((s, decls))
            i += 1; continue
        if ch == ";": buf = ""; i += 1; continue
        buf += ch; i += 1
    return out

def load(files):
    rules = {}
    for p in files:
        fp = os.path.join(UI, p.replace("/", os.sep))
        rules[p] = parse(open(fp, encoding="utf-8").read())
    return rules

shared = load(SHARED)
macos = load(MACOS)

# --- selectors shared between base.css and any other shared sheet
base = {s for s, _ in shared["web_new_v2/css/components/base.css"]}
print("base.css distinct selectors:", len(base))
sel_files = collections.defaultdict(set)
for p, rs in shared.items():
    for s, _ in rs:
        sel_files[s].add(p)
dup_selectors = {s: fs for s, fs in sel_files.items() if len(fs) > 1}
print("selectors defined in >1 shared stylesheet:", len(dup_selectors))
by_pair = collections.Counter()
for s, fs in dup_selectors.items():
    for p in fs:
        by_pair[p] += 1
for p, n in by_pair.most_common():
    print(f"   {n:>4} selectors also defined elsewhere: {p}")

# --- conflicting (selector, property) pairs, shared layer only
bysel = collections.defaultdict(list)
for p, rs in shared.items():
    for s, decls in rs:
        for prop, val in decls:
            bysel[s].append((p, prop, val))
conf = []
for s, lst in bysel.items():
    files = {e[0] for e in lst}
    if len(files) < 2: continue
    pm = collections.defaultdict(list)
    for f, prop, val in lst: pm[prop].append((f, val))
    for prop, vals in pm.items():
        if len({v for _, v in vals}) > 1 and len({f for f, _ in vals}) > 1:
            conf.append((s, prop, vals))
print()
print("SHARED-LAYER cross-file conflicting (selector, property) pairs:", len(conf))
print("SHARED-LAYER selectors with >=1 conflict:", len({c[0] for c in conf}))
pairc = collections.Counter()
for s, prop, vals in conf:
    pairc[tuple(sorted({v[0] for v in vals}))] += 1
for fs, n in pairc.most_common(20):
    print(f"   {n:>4}  {fs}")

print()
print("=== the 30 biggest shared-layer conflicts (selector | property | values) ===")
conf.sort(key=lambda r: (r[1], r[0]))
for s, prop, vals in conf[:30]:
    print(f"  {s}")
    print(f"      {prop}: " + " || ".join(f"{v[0].split('/')[-1]}={v[1]}" for v in vals))

# --- token overlap between tokens.css and base.css
def toks(p):
    fp = os.path.join(UI, p.replace("/", os.sep))
    css = strip_comments(open(fp, encoding="utf-8").read())
    return collections.defaultdict(list, {})
tdecl = collections.defaultdict(list)
bdecl = collections.defaultdict(list)
for p, acc in (("web_new_v2/css/tokens.css", tdecl), ("web_new_v2/css/components/base.css", bdecl)):
    fp = os.path.join(UI, p.replace("/", os.sep))
    css = strip_comments(open(fp, encoding="utf-8").read())
    for m in re.finditer(r"(--[\w-]+)\s*:\s*([^;{}]+)", css):
        acc[m.group(1)].append(" ".join(m.group(2).split()))
overlap = set(tdecl) & set(bdecl)
print()
print("=== custom properties declared in BOTH tokens.css and base.css ===")
for k in sorted(overlap):
    same = set(tdecl[k]) == set(bdecl[k])
    print(f"  {k:26s} tokens.css={tdecl[k]}  base.css={bdecl[k]}  {'same' if same else 'DIFFERENT'}")
print("  count:", len(overlap), " disagreeing:", sum(1 for k in overlap if set(tdecl[k]) != set(bdecl[k])))

# --- redeclaration of the same token inside base.css
print()
print("=== tokens declared more than once inside base.css ===")
for k, v in sorted(bdecl.items()):
    if len(v) > 1:
        print(f"  {k:26s} {v}")
