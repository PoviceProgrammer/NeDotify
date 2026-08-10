"""
Конвертирует иконку NeDotify в .ico с множеством размеров.
Запуск: python make_icon.py
"""
import sys, os

try:
    from PIL import Image
except ImportError:
    os.system(f"{sys.executable} -m pip install pillow -q")
    from PIL import Image

# Путь к исходному изображению (чистая иконка на белом фоне)
SRC = r"C:\Users\valee\.gemini\antigravity\brain\94cdb901-f1d1-43f2-bc45-5c3486c491d2\nedotify_icon_clean_1786351184568.jpg"
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icon.ico")
OUT_PNG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icon.png")

def make_ico(src_path, out_path, out_png):
    img = Image.open(src_path).convert("RGBA")

    # Make white background transparent for better icon look
    data = img.getdata()
    new_data = []
    for r, g, b, a in data:
        # If pixel is very close to white — make transparent
        if r > 240 and g > 240 and b > 240:
            new_data.append((255, 255, 255, 0))
        else:
            new_data.append((r, g, b, a))
    img.putdata(new_data)

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
