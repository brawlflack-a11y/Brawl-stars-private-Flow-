# Генерирует обложки channel/posts/<имя>.png для текстовых постов (нужен Pillow: pip install pillow)
from pathlib import Path
from PIL import Image, ImageDraw, ImageFilter, ImageFont

POSTS = Path(__file__).resolve().parent.parent / "posts"
BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
REGULAR = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"

COVERS = {
    "01-privet": ("старт", "Добро пожаловать\nв Виртуальный бизнес"),
    "02-ideya-tg-kanal": ("#идея", "Telegram-канал\nкак бизнес"),
    "02b-razvod-keysy": ("#развод", "Кейс-сайты:\nпочему бонус к депозиту\nработает против тебя"),
    "04-razbor-cifrovye-tovary": ("#разбор", "Цифровые товары:\nсделал раз — продаёшь всегда"),
    "05-razvod-bez-vlozheniy": ("#развод", "5 признаков фейкового\n«заработка в интернете»"),
    "07-ideya-frilans": ("#идея", "Фриланс:\nстарт без вложений"),
    "08-oshibki-novichkov": ("#ошибки", "7 ошибок новичков\nв онлайн-бизнесе"),
    "09-instrumenty-besplatnye": ("#инструменты", "Бесплатный набор\nдля старта"),
    "10-razbor-pribyl": ("#разбор", "Выручка ≠ прибыль:\nсчитаем на примере"),
}
ACCENTS = {"#развод": (255, 82, 82), "#ошибки": (255, 159, 67)}
GREEN = (46, 213, 115)
W, H, SS = 1280, 720, 2


def draw_cover(tag, title, out):
    w, h = W * SS, H * SS
    img = Image.new("RGB", (w, h))
    d = ImageDraw.Draw(img)
    top, bot = (12, 20, 48), (30, 42, 100)
    for y in range(h):
        t = y / h
        d.line([(0, y), (w, y)], fill=tuple(int(top[i] + (bot[i] - top[i]) * t) for i in range(3)))
    accent = ACCENTS.get(tag, GREEN)

    # декоративный график справа
    glow = Image.new("L", (w, h), 0)
    ImageDraw.Draw(glow).ellipse([w * 0.62, h * 0.05, w * 1.15, h * 0.95], fill=90)
    glow = glow.filter(ImageFilter.GaussianBlur(120 * SS))
    img.paste(Image.new("RGB", (w, h), (40, 120, 110)), (0, 0), glow)
    d = ImageDraw.Draw(img)
    base = 600 * SS
    for i, bh in enumerate([120, 190, 260, 340]):
        x = (930 + i * 80) * SS
        d.rounded_rectangle([x, base - bh * SS, x + 54 * SS, base], radius=10 * SS, fill=(22, 160, 95))
    pts = [(915, 470), (1000, 400), (1080, 425), (1220, 250)]
    d.line([(x * SS, y * SS) for x, y in pts], fill=accent, width=16 * SS, joint="curve")

    # метка рубрики
    tag_font = ImageFont.truetype(BOLD, 34 * SS)
    tw = d.textlength(tag, font=tag_font)
    x0, y0 = 80 * SS, 90 * SS
    d.rounded_rectangle([x0, y0, x0 + tw + 48 * SS, y0 + 64 * SS], radius=32 * SS, fill=accent)
    d.text((x0 + 24 * SS, y0 + 12 * SS), tag, font=tag_font, fill=(12, 20, 48))

    # заголовок: подбираем размер, чтобы влез слева от графика
    size = 72
    while size > 40:
        font = ImageFont.truetype(BOLD, size * SS)
        if max(d.textlength(line, font=font) for line in title.split("\n")) <= 780 * SS:
            break
        size -= 2
    d.multiline_text((80 * SS, 210 * SS), title, font=font, fill=(240, 245, 255), spacing=18 * SS)

    # подпись канала
    d.rectangle([80 * SS, 600 * SS, 140 * SS, 606 * SS], fill=accent)
    d.text((80 * SS, 625 * SS), "Виртуальный бизнес · @VirtualBiznesChannel",
           font=ImageFont.truetype(REGULAR, 28 * SS), fill=(170, 182, 215))

    img.resize((W, H), Image.LANCZOS).save(out, optimize=True)


if __name__ == "__main__":
    for name, (tag, title) in COVERS.items():
        draw_cover(tag, title, POSTS / f"{name}.png")
        print(f"{name}.png")
