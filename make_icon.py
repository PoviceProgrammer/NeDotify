"""
Конвертирует иконку NeDotify в .ico с сохранением полного фона.
Запуск: python make_icon.py
"""
import sys, os

try:
    from PIL import Image
except ImportError:
    os.system(f"{sys.executable} -m pip install pillow -q")
    from PIL import Image

SRC = r"C:\Users\valee\Videos\icon.jpg"
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icon.ico")
OUT_PNG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icon.png")

def make_ico(src_path, out_path, out_png):
    # Keep full image background intact (Screen 1)
    img = Image.open(src_path).convert("RGBA")

    # Save PNG copy (for PyInstaller --icon)
    img_png = img.resize((256, 256), Image.LANCZOS)
    img_png.save(out_png, "PNG")
    print(f"PNG saved: {out_png}")

    # Multi-size ICO (Windows standard sizes)
    sizes = [16, 24, 32, 48, 64, 128, 256]
    icons = [img.resize((s, s), Image.LANCZOS) for s in sizes]
    icons[0].save(
        out_path,
        format="ICO",
        sizes=[(s, s) for s in sizes],
        append_images=icons[1:]
    )
    print(f"ICO saved: {out_path}")
    print(f"Sizes: {sizes}")

if __name__ == "__main__":
    make_ico(SRC, OUT, OUT_PNG)
    print("\nDone! Use icon.ico in PyInstaller builds.")
