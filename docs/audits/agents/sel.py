import os
BASE = r"C:\Users\Артур\NeDotify\AURA_Music_backup\AURA_Music_main\ui\web_new_v2\css"
targets = {
    "components/base.css": [508,514,520,589,828,907,997,1115,1579,1729,1742,2587,3050,3076,3360,3392,3559,3575,3685,3730,3774,3788,3810,3844,3924,3973,4053,4108,4268,4428,240],
    "components/player-bar.css": [50,61,77,452],
    "components/lyrics.css": [59,80,114,136,138,143,245,393,440,456,474],
    "components/player-view.css": [44,51,60,86],
    "components/visual-polish.css": [],
    "components/home-refresh.css": [],
    "components/settings-refresh.css": [],
    "components/search-refresh.css": [],
    "components/library-refresh.css": [],
    "components/profile-refresh.css": [],
}
for rel, lines in targets.items():
    if not lines: continue
    p = os.path.join(BASE, rel.replace("/", os.sep))
    src = open(p, encoding="utf-8").read().splitlines()
    print("=====", rel)
    for ln in lines:
        # find the selector: walk back to the nearest '{'
        i = ln - 1
        sel = "?"
        while i >= 0:
            if "{" in src[i]:
                sel = src[i].split("{")[0].strip()
                break
            i -= 1
        print(f"  {ln:>5}: {src[ln-1].strip()[:110]}")
        print(f"         ^ selector: {sel[:170]}")
