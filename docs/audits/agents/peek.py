import json, os
b = r"C:\Users\Артур\NeDotify\AURA_Music_backup\AURA_Music_main\tools\bench\results"
for name in ("css_blur_map.json", "backdrop_nesting.json", "optimization-before-20261015-154303.json"):
    p = os.path.join(b, name)
    d = json.load(open(p, encoding="utf-8"))
    print("=====", name, type(d).__name__)
    if isinstance(d, dict):
        for k in list(d.keys())[:14]:
            v = d[k]
            s = json.dumps(v, ensure_ascii=False)
            print("  ", k, "->", (s[:800] + ("..." if len(s) > 800 else "")))
    else:
        print(json.dumps(d, ensure_ascii=False)[:1200])
    print()
