import re, os, json, collections

ROOT = r"C:\Users\Артур\NeDotify\AURA_Music_backup\AURA_Music_main"
UI = os.path.join(ROOT, "ui")

js = open(os.path.join(UI, "web_new_v2", "js", "settings.js"), encoding="utf-8").read()
# grab the WORKSHOP_ITEMS array block
i = js.index("export const WORKSHOP_ITEMS = [")
j = js.index("\n];", i)
block = js[i:j]
ids = re.findall(r"id:\s*'([^']+)'", block)
previews = re.findall(r"preview:\s*'([^']+)'", block)
urls = re.findall(r"\n\s*url:\s*'([^']+)'", block)
print("WORKSHOP_ITEMS count:", len(ids))
for k, (pid, prev) in enumerate(zip(ids, previews)):
    print(f"  {k:>3} {pid:<18} {prev}")

assets = open(os.path.join(UI, "web_new_v2", "js", "appearance-assets.js"), encoding="utf-8").read()
photos = set(re.findall(r'"(photo-[0-9a-z\-]+)"', assets.split("const themes")[0]))
print("\nlocal photos set size:", len(photos))

def resolve(v):
    m = re.match(r"https?://([^/]+)/(.*)", v)
    if not m:
        return v, "not-remote"
    host = m.group(1); rest = m.group(2)
    if host in ("wsrv.nl", "www.wsrv.nl"):
        q = re.search(r"[?&]url=([^&]+)", rest)
        if q:
            import urllib.parse
            inner = urllib.parse.unquote(q.group(1))
            return resolve(inner)
        return v, "wsrv-noparam"
    if host != "images.unsplash.com":
        return v, "remote-other-host"
    pid = rest.split("?")[0]
    if pid == "photo-1511497584788-876761c1298b":
        pid = "photo-1511497584788-876760111969"
    if pid in photos:
        return f"assets/backgrounds/{pid}.jpg", "local"
    return v, "REMOTE-unsplash-not-in-set"

local = set(); remote = []
for pid, prev in zip(ids, previews):
    p, kind = resolve(prev)
    if kind == "local":
        local.add(p)
    elif kind.startswith("REMOTE") or kind == "remote-other-host":
        remote.append((pid, p, kind))
print("\nWORKSHOP preview resolution:")
print("  distinct local:", len(local))
print("  still remote  :", len(remote))
for pid, p, kind in remote:
    print(f"    {pid:<18} {kind:<32} {p}")

# theme preview paths
themes_block = assets.split("const themes = {")[1].split("};")[0]
theme_map = dict(re.findall(r'"([a-z]+)":\s*"([0-9\-a-z]+)"', themes_block))
print("\nappearance-assets themes map entries:", len(theme_map))
base = os.path.join(UI, "web_new_v2", "assets", "backgrounds")
tot = 0
missing = []
for tid, pid in sorted(theme_map.items()):
    fp = os.path.join(base, f"photo-{pid}.jpg")
    if os.path.exists(fp):
        tot += os.path.getsize(fp)
    else:
        missing.append((tid, fp))
print("distinct theme-preview JPEGs total bytes:", f"{tot:,}", f"({tot/1024/1024:.2f} MB)")
print("missing:", missing)

# files in backgrounds folder not referenced anywhere
allfiles = {f"assets/backgrounds/{f}" for f in os.listdir(base) if f.endswith(".jpg")}
referenced = set(local)
for pid in theme_map.values():
    referenced.add(f"assets/backgrounds/photo-{pid}.jpg")
unused = sorted(allfiles - referenced)
print("\nbackground JPEGs never referenced by workshop or theme map:", len(unused))
for u in unused:
    print("   ", u, os.path.getsize(os.path.join(UI, "web_new_v2", u.replace("/", os.sep))))

# font file sizes
fdir = os.path.join(UI, "web_new_v2", "assets", "fonts")
print("\nfonts:")
for f in sorted(os.listdir(fdir)):
    print(f"   {f:<40} {os.path.getsize(os.path.join(fdir, f)):>9,}")

# theme-previews dead?
tp = os.path.join(UI, "web_new_v2", "assets", "theme-previews")
print("\ntheme-previews PNGs:", len(os.listdir(tp)), "bytes:", sum(os.path.getsize(os.path.join(tp,f)) for f in os.listdir(tp)))
