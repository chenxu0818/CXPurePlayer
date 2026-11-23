"""生成 CXPurePlayer 科技风 Logo：logo.png + 多尺寸 icon.ico。

设计：深空蓝圆角方块 + 电光蓝轨道环 + 白色播放三角，象征「纯净播放 + 流动媒体」。
只依赖 Pillow，生成的图片可随 PyInstaller 一起分发。
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "app" / "resources"
SIZE = 1024


def _rounded_mask(size: int, radius: int) -> Image.Image:
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, size - 1, size - 1), radius=radius, fill=255)
    return mask


def make_logo() -> Image.Image:
    img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))

    # 背景：深空蓝 → 电光蓝的斜向渐变
    grad = Image.new("RGBA", (SIZE, SIZE))
    draw = ImageDraw.Draw(grad)
    for y in range(SIZE):
        t = y / (SIZE - 1)
        r = int(11 + (38 - 11) * t)
        g = int(20 + (110 - 20) * t)
        b = int(42 + (235 - 42) * t)
        draw.line([(0, y), (SIZE, y)], fill=(r, g, b, 255))
    glow = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    gd.ellipse((-180, -260, 760, 520), fill=(96, 190, 255, 110))
    glow = glow.filter(ImageFilter.GaussianBlur(150))
    grad = Image.alpha_composite(grad, glow)
    img.paste(grad, (0, 0), _rounded_mask(SIZE, 220))

    d = ImageDraw.Draw(img)

    # 内描边，提升深色主题下的层次感
    d.rounded_rectangle((34, 34, SIZE - 34, SIZE - 34), radius=192,
                        outline=(255, 255, 255, 52), width=8)

    # 轨道环：两段弧线围住三角，暗示流媒体
    box = (176, 176, SIZE - 176, SIZE - 176)
    d.arc(box, start=198, end=342, fill=(120, 225, 255, 235), width=26)
    d.arc(box, start=18, end=162, fill=(255, 255, 255, 105), width=18)

    # 播放三角（带柔和投影）
    triangle = [(414, 326), (742, 512), (414, 698)]
    shadow = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).polygon(
        [(x + 18, y + 24) for x, y in triangle], fill=(4, 12, 34, 130)
    )
    shadow = shadow.filter(ImageFilter.GaussianBlur(20))
    img = Image.alpha_composite(img, shadow)
    d = ImageDraw.Draw(img)
    d.polygon(triangle, fill=(255, 255, 255, 255))
    # 左侧高光，营造玻璃质感
    d.polygon([(414, 326), (486, 366), (486, 658), (414, 698)],
              fill=(214, 240, 255, 255))

    return img


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    logo = make_logo()
    logo.resize((256, 256), Image.Resampling.LANCZOS).save(
        OUT_DIR / "logo.png", optimize=True
    )
    logo.save(
        OUT_DIR / "icon.ico", format="ICO",
        sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
    )
    for path in (OUT_DIR / "logo.png", OUT_DIR / "icon.ico"):
        print(path, path.stat().st_size, "bytes")


if __name__ == "__main__":
    main()
