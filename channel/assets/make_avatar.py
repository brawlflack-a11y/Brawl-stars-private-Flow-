# Генерирует channel/assets/avatar.png (нужен Pillow: pip install pillow)
from PIL import Image, ImageDraw, ImageFont, ImageFilter
S = 1024
SS = 2  # supersample
W = S * SS
img = Image.new("RGB", (W, W))
d = ImageDraw.Draw(img)
# radial-ish vertical gradient: deep navy -> indigo
top, bot = (12, 20, 48), (30, 42, 100)
for y in range(W):
    t = y / W
    d.line([(0, y), (W, y)], fill=tuple(int(top[i] + (bot[i] - top[i]) * t) for i in range(3)))
# soft glow in center
glow = Image.new("RGB", (W, W), (0, 0, 0))
gd = ImageDraw.Draw(glow)
gd.ellipse([W*0.18, W*0.18, W*0.82, W*0.82], fill=(40, 120, 110))
glow = glow.filter(ImageFilter.GaussianBlur(W * 0.12))
img = Image.blend(img, Image.composite(glow, img, glow.convert("L")), 0.35)
d = ImageDraw.Draw(img)

def P(x, y): return (x * SS, y * SS)
green, green2, white = (46, 213, 115), (22, 160, 95), (240, 245, 255)
# laptop base / screen frame
d.rounded_rectangle([*P(262, 300), *P(762, 640)], radius=28*SS, fill=(18, 26, 60), outline=white, width=14*SS)
d.rounded_rectangle([*P(200, 640), *P(824, 686)], radius=22*SS, fill=white)
d.rounded_rectangle([*P(452, 640), *P(572, 658)], radius=8*SS, fill=(180, 190, 215))
# bars on screen
bars = [(320, 540), (410, 490), (500, 430), (590, 370)]
for x, ytop in bars:
    d.rounded_rectangle([*P(x, ytop), *P(x + 60, 600)], radius=10*SS, fill=green2)
# rising line + arrow
pts = [P(300, 560), P(420, 470), P(510, 500), P(690, 345)]
d.line(pts, fill=green, width=22*SS, joint="curve")
for p in pts[:-1]:
    r = 14 * SS
    d.ellipse([p[0]-r, p[1]-r, p[0]+r, p[1]+r], fill=green)
# arrowhead at end
ax, ay = 690, 345
d.polygon([P(ax + 40, ay - 36), P(ax - 30, ay - 22), P(ax + 22, ay + 34)], fill=green)
# caption
font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 76 * SS)
text = "БИЗНЕС"
tw = d.textlength(text, font=font)
d.text(((W - tw) / 2, 735 * SS), text, font=font, fill=white)
img = img.resize((S, S), Image.LANCZOS)
img.save(str(__import__("pathlib").Path(__file__).with_name("avatar.png")), optimize=True)
