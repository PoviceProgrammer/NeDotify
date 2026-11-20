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
    return re.sub(r"/\*.*?\*/", " ", css, flags=re.S)

def parse(css):
    """Return list of (selector, [(prop, value, line)]) in source order, plus @media context."""
    css = strip_comments(css)
    out = []
    stack = []  # media context
    i = 0
    n = len(css)
    buf = ""
    lineno = 1
    line_of = []  # index->line
    cur_line = 1
    while i < n:
        ch = css[i]
        if ch == "\n":
            cur_line += 1
        if ch == "{":
            sel = " ".join(buf.split())
            buf = ""
            i += 1
            start_line = cur_line
            # find matching close
            d = 1
            body_start = i
            while i < n and d > 0:
                if css[i] == "{":
                    d += 1
                elif css[i] == "}":
                    d -= 1
                    if d == 0:
                        break
                if css[i] == "\n":
                    cur_line += 1
                i += 1
            body = css[body_start:i]
            body_line = css[:body_start].count("\n") + 1
            if sel.startswith("@media"):
                stack.append(sel)
            elif sel.startswith("@"):
                pass  # @keyframes etc: skip declarations but track name
            else:
                decls = []
                for m in re.finditer(r"([-a-zA-Z]+)\s*:\s*([^;{}]+)(;|(?=\}))", body):
                    props = m.group(1).strip()
                    val = " ".join(m.group(2).split())
                    bl = body[:m.start()].count("\n") + body_line
                    decls.append((props, val, bl))
                for s in sel.split(","):
                    s = " ".join(s.split())
                    if s:
                        out.append((s, decls, list(stack), start_line))
            if sel.startswith("@media"):
                stack.pop()
            i += 1
            continue
        if ch == ";":
            buf = ""
            i += 1
            continue
        buf += ch
        i += 1
    return out

rules = {}
for p in LINKED:
    fp = os.path.join(UI, p.replace("/", os.sep))
    css = open(fp, encoding="utf-8").read()
    rules[p] = parse(css)

# Build: for each selector, ordered list of (file, prop, value, media)
bysel = collections.defaultdict(list)
for p, rs in rules.items():
    for sel, decls, media, line in rs:
        for prop, val, bl in decls:
            bysel[sel].append((p, prop, val, media, bl))

# Find selectors declared in >=2 distinct files, with conflicting values for the same prop
print("=== CROSS-FILE CONFLICTS (same selector, same property, different value, different file) ===")
conflict_rows = []
for sel, lst in bysel.items():
    files = {e[0] for e in lst}
    if len(files) < 2:
        continue
    propmap = collections.defaultdict(list)
    for f, prop, val, media, bl in lst:
        propmap[prop].append((f, val, media, bl))
    for prop, vals in propmap.items():
        distinct = {v for _, v, _, _ in vals}
        if len(distinct) > 1:
            # only if declared in different files
            vfiles = {f for f, _, _, _ in vals}
            if len(vfiles) > 1:
                conflict_rows.append((sel, prop, vals))

print(f"total cross-file conflicting (selector, property) pairs: {len(conflict_rows)}")
print(f"total selectors with any cross-file conflict: {len({r[0] for r in conflict_rows})}")
print()
# Group by file pair
pairs = collections.Counter()
for sel, prop, vals in conflict_rows:
    fs = tuple(sorted({v[0] for v in vals}))
    pairs[fs] += 1
for fs, n in pairs.most_common(30):
    print(f"  {n:>4}  {fs}")
print()
print("--- sample conflicts (first 40, deterministic order) ---")
conflict_rows.sort(key=lambda r: (r[1], r[0]))
for sel, prop, vals in conflict_rows[:40]:
    vtxt = " || ".join(f"{v[0].split('/')[-1]}:{v[1]}" + (f" @{v[2]}" if v[2] else "") for v in vals)
    print(f"  {sel}  {{ {prop} }}")
    print(f"      {vtxt}")

print()
print("=== !important USAGE ===")
tot = 0
for p in LINKED:
    fp = os.path.join(UI, p.replace("/", os.sep))
    css = open(fp, encoding="utf-8").read()
    n = len(re.findall(r"!important", css))
    tot += n
    if n:
        print(f"  {p:55s} {n}")
print(f"  TOTAL !important: {tot}")

print()
print("=== ANIMATION COUNT / INFINITE ===")
for p in LINKED:
    fp = os.path.join(UI, p.replace("/", os.sep))
    css = open(fp, encoding="utf-8").read()
    anims = re.findall(r"animation\s*:\s*([^;{}]+)", css)
    inf = [a for a in anims if "infinite" in a]
    print(f"  {p:55s} anim-decls={len(anims):>3} infinite={len(inf):>3}")

print()
print("=== will-change ===")
for p in LINKED:
    fp = os.path.join(UI, p.replace("/", os.sep))
    css = open(fp, encoding="utf-8").read()
    for m in re.finditer(r"will-change\s*:\s*([^;{}]+)", css):
        line = css[:m.start()].count("\n") + 1
        # find enclosing selector
        print(f"  {p}:{line}  will-change: {m.group(1).strip()}")
