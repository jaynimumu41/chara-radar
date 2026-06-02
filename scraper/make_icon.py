"""產生可愛的 App 圖示（純 PIL 繪製，不需 SVG）。
圓角粉嫩漸層底 + 中央胖胖閃亮星星 + 周圍小星點。
輸出多種尺寸 PNG 到專案根目錄。"""
import math
from pathlib import Path
from PIL import Image, ImageDraw, ImageFilter

ROOT = Path(__file__).parent.parent
SS = 4  # 超取樣倍率（抗鋸齒）

def lerp(a, b, t):
    return tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3))

def quad_bezier(p0, p1, p2, n=24):
    pts = []
    for i in range(n + 1):
        t = i / n
        x = (1 - t) ** 2 * p0[0] + 2 * (1 - t) * t * p1[0] + t * t * p2[0]
        y = (1 - t) ** 2 * p0[1] + 2 * (1 - t) * t * p1[1] + t * t * p2[1]
        pts.append((x, y))
    return pts

def sparkle(cx, cy, R, pinch=0.18, rot=0.0):
    """4 點閃亮星：四尖角 + 凹入弧邊（凹向中心）。"""
    tips = []
    for k in range(4):
        a = rot + k * math.pi / 2
        tips.append((cx + R * math.cos(a), cy + R * math.sin(a)))
    ctrl = (cx, cy)  # 控制點放中心 → 弧邊凹向中心
    poly = []
    for k in range(4):
        A = tips[k]
        B = tips[(k + 1) % 4]
        # 控制點稍微往中心收，pinch 越小越尖
        c = (cx + (ctrl[0] - cx), cy + (ctrl[1] - cy))
        # 用兩段：尖角→近中心→下一尖角，讓凹邊柔順
        mid = (cx + pinch * (A[0] + B[0] - 2 * cx),
               cy + pinch * (A[1] + B[1] - 2 * cy))
        poly += quad_bezier(A, mid, B, n=20)
    return poly

def make(size):
    W = size * SS
    img = Image.new("RGB", (W, W), (255, 255, 255))
    d = ImageDraw.Draw(img)

    # 1) 垂直漸層底（粉紅 → 奶油桃）
    top = (255, 214, 232)     # 柔粉
    bot = (255, 244, 222)     # 奶油桃
    for y in range(W):
        d.line([(0, y), (W, y)], fill=lerp(top, bot, y / W))

    # 2) 圓角遮罩（squircle）
    radius = int(W * 0.235)
    mask = Image.new("L", (W, W), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, W - 1, W - 1], radius=radius, fill=255)

    cx = cy = W / 2

    # 3) 周圍小星點（白色，半透明感用淺色）
    small = [(0.26, 0.30, 0.052), (0.76, 0.26, 0.040),
             (0.78, 0.74, 0.058), (0.24, 0.76, 0.038)]
    for fx, fy, fr in small:
        poly = sparkle(W * fx, W * fy, W * fr, pinch=0.16, rot=math.pi / 4)
        d.polygon(poly, fill=(255, 255, 255))

    # 4) 主星陰影（柔和）
    sh = Image.new("RGBA", (W, W), (0, 0, 0, 0))
    ImageDraw.Draw(sh).polygon(
        sparkle(cx, cy + W * 0.018, W * 0.30), fill=(214, 140, 60, 90))
    sh = sh.filter(ImageFilter.GaussianBlur(W * 0.02))
    img.paste(Image.new("RGB", (W, W), (240, 170, 90)), (0, 0),
              Image.eval(sh.split()[3], lambda a: a))

    # 5) 主星（金色）
    d.polygon(sparkle(cx, cy, W * 0.30), fill=(246, 183, 60))
    # 內層亮金
    d.polygon(sparkle(cx, cy, W * 0.205), fill=(250, 207, 110))
    # 白色高光小星（偏左上）
    d.polygon(sparkle(cx - W * 0.055, cy - W * 0.06, W * 0.085),
              fill=(255, 255, 255))
    # 右上角小圓亮點
    rr = W * 0.026
    d.ellipse([cx + W * 0.17 - rr, cy - W * 0.20 - rr,
               cx + W * 0.17 + rr, cy - W * 0.20 + rr], fill=(255, 255, 255))

    # 套圓角遮罩 + 縮回目標尺寸
    out = Image.new("RGBA", (W, W), (0, 0, 0, 0))
    out.paste(img, (0, 0), mask)
    out = out.resize((size, size), Image.LANCZOS)
    return out

for s, name in [(512, "icon-512.png"), (192, "icon-192.png"),
                (180, "apple-touch-icon.png"), (32, "favicon-32.png")]:
    make(s).save(ROOT / name)
    print("已產生", name)
