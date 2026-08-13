"""
Generates icon.ico / icon.png for the NeDotify_v1.5.1 build
from the user-provided source image (full background preserved).
Run: python make_icon_v151.py
"""
import os
import sys

try:
    from PIL import Image
except ImportError:
    os.system(f"{sys.executable} -m pip install pillow -q")
    from PIL import Image

SRC = r"C:\Users\valee\Videos\icon.jpg"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUT_ICO = os.path.join(BASE_DIR, "icon.ico")
OUT_PNG = os.path.join(BASE_DIR, "icon.png")


def make_ico(src_path, out_ico, out_png):
    # Keep full image background intact (Screen 1)
    img = Image.open(src_path).convert("RGBA")

    # 256px PNG (used as app icon source where needed)
    img_png = img.resize((256, 256), Image.LANCZOS)
    img_png.save(out_png, "PNG")
    print(f"PNG saved: {out_png}")

    # Multi-size ICO (Windows standard sizes)
    sizes = [16, 24, 32, 48, 64, 128, 256]
    icons = [img.resize((s, s), Image.LANCZOS) for s in sizes]
    icons[0].save(
        out_ico,
        format="ICO",
        sizes=[(s, s) for s in sizes],
        append_images=icons[1:],
    )
    print(f"ICO saved: {out_ico}")
    print(f"Sizes: {sizes}")


if __name__ == "__main__":
    make_ico(SRC, OUT_ICO, OUT_PNG)
    print("\nDone! icon.ico ready for PyInstaller builds.")