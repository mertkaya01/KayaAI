"""kayaAI ofisinin kendi hazır çizimleri (Adım 21d). Çıktı: ui/public/office/pixel/kaya/ — çalıştır: python scripts/office_art.py

1. Ajan başına karakter: free-office-pixel-art (arlantr, "free to use any way you want") yürüyen kız (Julia) ve
   masada oturan çalışanlardan RENK DEĞİŞTİRİLEREK türetilir — her ajanın kendi saç rengi ve kendi renginde tişörtü
   olur, yürürken de masadaki hâliyle aynı görünür (önceden bütün ajanlar aynı kızla yürüyordu).
2. Eşyalar (sıfırdan, kod ile çizilir): kitaplık, kahve köşesi, fotokopi + koliler, devetabanı, çöp kovası, lavabo,
   su sebili. Malzeme başına 4 ton (dış çizgi, koyu, orta, açık): üst/sol kenar açık, alt/sağ kenar koyu.

Deterministik (sabit tohum): aynı betik aynı resimleri üretir.
"""

from __future__ import annotations

import random
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "ui" / "public" / "office" / "pixel"
OUT = SRC / "kaya"

RGBA = tuple[int, int, int, int]


def hexc(h: str, a: int = 255) -> RGBA:
    h = h.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), a


def mix(a: str, b: str, t: float) -> str:
    x, y = hexc(a), hexc(b)
    return "#" + "".join(f"{round(x[i] + (y[i] - x[i]) * t):02x}" for i in range(3))


# ----------------------------------------------------------------------------- tuval

class Canvas:
    def __init__(self, w: int, h: int):
        self.w, self.h = w, h
        self.im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        self.p = self.im.load()

    def px(self, x: int, y: int, c: str | RGBA) -> None:
        if 0 <= x < self.w and 0 <= y < self.h:
            self.p[x, y] = hexc(c) if isinstance(c, str) else c

    def rect(self, x0: int, y0: int, x1: int, y1: int, c: str | RGBA) -> None:
        for y in range(y0, y1 + 1):
            for x in range(x0, x1 + 1):
                self.px(x, y, c)

    def hline(self, x0: int, x1: int, y: int, c: str) -> None:
        self.rect(x0, y, x1, y, c)

    def vline(self, x: int, y0: int, y1: int, c: str) -> None:
        self.rect(x, y0, x, y1, c)

    def solid(self, mask: set[tuple[int, int]], mat: tuple[str, str, str, str]) -> None:
        """Maske → pixel cisim: dış çizgi, üst/sol açık, alt/sağ koyu, iç orta ton."""
        out, dark, mid, light = mat
        edge = {(x, y) for (x, y) in mask if any((x + dx, y + dy) not in mask for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)))}
        for (x, y) in mask:
            if (x, y) in edge:
                c = out
            elif (x, y - 1) in edge or (x - 1, y) in edge:
                c = light
            elif (x, y + 1) in edge or (x + 1, y) in edge:
                c = dark
            else:
                c = mid
            self.px(x, y, c)

    def box(self, x0: int, y0: int, x1: int, y1: int, mat: tuple[str, str, str, str]) -> None:
        self.solid({(x, y) for x in range(x0, x1 + 1) for y in range(y0, y1 + 1)}, mat)


def ellipse(cx: float, cy: float, rx: float, ry: float) -> set[tuple[int, int]]:
    return {(x, y) for x in range(int(cx - rx) - 1, int(cx + rx) + 2) for y in range(int(cy - ry) - 1, int(cy + ry) + 2)
            if ((x + 0.5 - cx) / rx) ** 2 + ((y + 0.5 - cy) / ry) ** 2 <= 1}


# Malzemeler (dış çizgi, koyu, orta, açık)
WOOD = ("#2a170b", "#5a3519", "#7a4a28", "#9c6537")
WOOD_DARK = ("#1e120a", "#3e2616", "#553420", "#6e4529")
METAL = ("#22262c", "#6c7480", "#a7b0ba", "#d9dfe5")
PLASTIC = ("#3a4048", "#aab2bb", "#d4dae0", "#f1f4f6")
CABINET = ("#3b342c", "#bdb4a5", "#ddd6c8", "#f0ebe1")
STONE = ("#262b31", "#4a525c", "#5f6873", "#7f8994")
CARDBOARD = ("#4f361c", "#a57c47", "#c49560", "#dcb683")
TERRACOTTA = ("#4a2212", "#8f4325", "#bf6038", "#dd8457")
LEAF = ("#103d24", "#1f6b42", "#2e8b57", "#45b36f")
WATER = ("#1d4a78", "#3d86c6", "#6fb2ea", "#b9e0ff")


# ----------------------------------------------------------------------------- 1) ajan karakterleri

# Hazır çizimlerdeki renkler: saç (açık, orta, koyu) ve tişört/omuz (açık, orta, koyu)
JULIA_HAIR = ("884625", "5f3520", "422110")
JULIA_SHIRT = ("e2d229", "ccad1b", "ad7814")
SEATED = {  # hazır oturan kişi: saç (açık, orta, koyu), omuz (açık, orta) — saç kalıbına ve omuz rengine göre
    "worker1-person.png": {"hair": ("525252", "373737", "212121"), "shirt": ("cecece", "a3a3a3")},
    "worker2-person.png": {"hair": ("d0c339", "c6b828", "a79a18"), "shirt": ("de2020", "be1a1a")},
    "worker4-person.png": {"hair": ("4c94e4", "3584c0", "185ca7"), "extra": {"2a82ba": 0, "ef6d28": "s", "ef2828": "s"}},
}
HAIR = {
    "black": ("#4a4a50", "#2e2e33", "#18181c"),
    "blond": ("#e3cf5a", "#c9b02c", "#9a8216"),
    "auburn": ("#c8693c", "#9c4524", "#6a2a14"),
    "brown": ("#7a5233", "#553620", "#382111"),
    "silver": ("#d7dae0", "#a9aeb8", "#7a808c"),
    "blue": ("#4c94e4", "#3584c0", "#185ca7"),
}
# ajan → (oturma kalıbı, saç, tişört rengi = ajanın rengi; arayüzdeki renklerle aynı)
AGENTS = {
    "general": ("worker1-person.png", "black", "#4f8cff"),
    "data": ("worker2-person.png", "blond", "#3fbf8f"),
    "document": ("worker4-person.png", "auburn", "#b07cf0"),
    "coder": ("worker2-person.png", "brown", "#f07ca8"),
    "reviewer": ("worker1-person.png", "silver", "#c9a227"),
    "vision": ("worker4-person.png", "blue", "#47c7d6"),
}
WALKS = {"down": "Julia_walk_Foward.png", "up": "Julia_walk_Up.png", "left": "Julia_walk_Left.png", "right": "Julia_walk_Rigth.png"}


def recolor(src: Image.Image, mapping: dict[str, str]) -> Image.Image:
    im = src.convert("RGBA").copy()
    p = im.load()
    table = {hexc(k)[:3]: hexc(v)[:3] for k, v in mapping.items()}
    for y in range(im.height):
        for x in range(im.width):
            c = p[x, y]
            if c[3] and c[:3] in table:
                p[x, y] = table[c[:3]] + (c[3],)
    return im


def shirt_tones(color: str) -> tuple[str, str, str]:
    return mix(color, "#ffffff", 0.35), color, mix(color, "#000000", 0.32)


def agent_sprites() -> list[str]:
    made = []
    for agent, (seat_src, hair_name, color) in AGENTS.items():
        hair, shirt = HAIR[hair_name], shirt_tones(color)
        walk_map = {JULIA_HAIR[i]: hair[i] for i in range(3)} | {JULIA_SHIRT[i]: shirt[i] for i in range(3)}
        for d, f in WALKS.items():
            recolor(Image.open(SRC / f), walk_map).save(OUT / f"{agent}-walk-{d}.png")
            made.append(f"{agent}-walk-{d}.png")
        s = SEATED[seat_src]
        seat_map = {s["hair"][i]: hair[i] for i in range(3)}
        if "shirt" in s:
            seat_map |= {s["shirt"][0]: shirt[0], s["shirt"][1]: shirt[1]}
        for k, v in s.get("extra", {}).items():
            seat_map[k] = hair[v] if isinstance(v, int) else shirt[1]
        recolor(Image.open(SRC / seat_src), seat_map).save(OUT / f"{agent}-person.png")
        made.append(f"{agent}-person.png")
    return made


# ----------------------------------------------------------------------------- 2) eşyalar

BOOKS = ["#c0392b", "#2e86c1", "#27ae60", "#f1c40f", "#8e44ad", "#e67e22", "#16a085", "#d35400", "#ecf0f1", "#34495e"]


def bookshelf(rng: random.Random) -> Canvas:
    c = Canvas(30, 50)
    # üstte saksı ve kutu
    c.solid({(x, y) for x in range(5, 11) for y in range(4, 9) if not (y == 8 and x in (5, 10))}, TERRACOTTA)
    c.solid(ellipse(7.5, 2.6, 3.6, 2.6) | ellipse(10.5, 3.2, 2.2, 1.6), LEAF)
    c.box(17, 4, 25, 8, CARDBOARD)
    c.hline(18, 24, 6, CARDBOARD[1])
    # gövde
    c.box(0, 9, 29, 49, WOOD)
    rows = [(12, 20), (23, 31), (34, 41)]
    for y0, y1 in rows:
        c.rect(3, y0, 26, y1, "#3e2414")
        c.hline(3, 26, y0, "#2a170b")
        c.hline(2, 27, y1 + 1, WOOD[3])
        c.hline(2, 27, y1 + 2, WOOD[1])
    for ri, (y0, y1) in enumerate(rows):
        x = 4
        while x <= 24:
            if ri == 1 and 15 <= x <= 19:  # ortada küçük çerçeveli resim
                c.box(15, y1 - 6, 20, y1, ("#2b2b2b", "#b08a3e", "#d4ac55", "#f0d27a"))
                c.rect(16, y1 - 5, 19, y1 - 1, "#7fb6e8")
                c.rect(16, y1 - 2, 19, y1 - 1, "#4f9a5a")
                x = 22
                continue
            if ri == 2 and x >= 18:  # yatay yığılmış kitaplar
                for k, yy in enumerate(range(y1 - 1, y1 - 7, -2)):
                    col = BOOKS[(k * 3 + 1) % len(BOOKS)]
                    c.rect(18 + (k % 2), yy - 1, 25 - (k % 2), yy, col)
                    c.hline(18 + (k % 2), 25 - (k % 2), yy, mix(col, "#000000", 0.35))
                break
            w = rng.choice([2, 2, 3])
            hgt = rng.randint(5, y1 - y0)
            col = rng.choice(BOOKS)
            c.rect(x, y1 - hgt + 1, x + w - 1, y1, col)
            c.vline(x + w - 1, y1 - hgt + 1, y1, mix(col, "#000000", 0.35))
            c.px(x, y1 - hgt + 2, mix(col, "#ffffff", 0.5))
            c.px(x, y1 - hgt + 3, mix(col, "#ffffff", 0.5))
            x += w + (1 if rng.random() < 0.25 else 0)
    # alt çekmeceler
    for x0 in (3, 16):
        c.box(x0, 43, x0 + 10, 47, WOOD)
        c.rect(x0 + 4, 45, x0 + 6, 45, "#d9b46a")
    return c


def coffee_corner(rng: random.Random) -> Canvas:
    c = Canvas(64, 46)
    # dolap + tezgâh
    c.box(2, 25, 61, 45, CABINET)
    for x in (21, 41):
        c.vline(x, 27, 43, CABINET[1])
    for x in (18, 24, 38, 44):
        c.rect(x, 33, x, 35, "#6b6155")
    c.hline(3, 60, 44, CABINET[1])
    c.box(0, 21, 63, 25, WOOD_DARK)
    c.hline(1, 62, 22, WOOD[3])
    # espresso makinesi
    c.box(5, 4, 22, 21, METAL)
    c.rect(6, 2, 21, 3, METAL[1])
    for x in (7, 11, 15, 19):  # üstte ısınan fincanlar
        c.rect(x, 1, x + 1, 2, "#f4f4f4")
    c.rect(8, 6, 19, 10, "#2b2f36")
    c.rect(9, 7, 12, 8, "#7cf2a0")
    c.px(15, 8, "#ff5d5d")
    c.px(17, 8, "#5dff8a")
    c.rect(11, 12, 16, 13, "#1c1f24")
    c.rect(16, 13, 21, 13, "#111111")
    c.rect(9, 19, 18, 20, "#3a3f46")
    for x in range(9, 19, 2):
        c.px(x, 19, "#1c1f24")
    c.box(12, 15, 15, 18, ("#7a7a7a", "#d0d0d0", "#ececec", "#ffffff"))
    c.hline(13, 14, 15, "#5a3a22")
    # kahve kavanozu
    c.solid({(x, y) for x in range(25, 31) for y in range(13, 21)}, ("#3a4048", "#8fb4c9", "#bcd9e8", "#e2f2fa"))
    for (x, y) in ((26, 17), (28, 18), (27, 19), (29, 16), (26, 19), (28, 16)):
        c.px(x, y, "#5a3a22")
    c.rect(25, 11, 30, 12, "#2b2f36")
    # kupalar
    for x0, body, stripe in ((33, "#d64541", None), (40, "#f2f2f2", "#2e86c1")):
        c.box(x0, 16, x0 + 4, 20, (mix(body, "#000000", 0.6), mix(body, "#000000", 0.25), body, mix(body, "#ffffff", 0.45)))
        c.px(x0 + 5, 17, mix(body, "#000000", 0.6))
        c.px(x0 + 6, 18, mix(body, "#000000", 0.6))
        c.px(x0 + 5, 19, mix(body, "#000000", 0.6))
        if stripe:
            c.hline(x0 + 1, x0 + 3, 18, stripe)
    # çaydanlık
    k = ellipse(51.5, 17.5, 4.6, 4.2) | {(x, y) for x in range(48, 56) for y in range(18, 21)}
    c.solid(k, ("#16323a", "#2f7f8f", "#45a5b8", "#8fd6e3"))
    c.rect(50, 11, 53, 12, "#16323a")
    c.px(56, 15, "#16323a"); c.px(57, 14, "#16323a"); c.px(58, 13, "#16323a")
    # sukulent
    c.box(57, 17, 62, 20, ("#4a4a4a", "#cfcfcf", "#ececec", "#ffffff"))
    c.solid(ellipse(59.5, 15.5, 3.0, 2.2), LEAF)
    return c


def copier(rng: random.Random) -> Canvas:
    c = Canvas(60, 36)
    # gövde
    c.box(3, 8, 38, 35, PLASTIC)
    c.box(4, 5, 37, 9, ("#3a4048", "#7f8892", "#98a1ab", "#b8c0c8"))
    c.box(8, 2, 26, 5, ("#3a4048", "#c9d0d7", "#e3e8ec", "#f7f9fb"))
    c.rect(10, 1, 24, 3, "#ffffff")  # besleyicideki kâğıt
    c.hline(11, 22, 2, "#d0d6dc")
    # kontrol paneli
    c.rect(27, 10, 36, 14, "#2f3540")
    c.rect(28, 11, 31, 12, "#5fd0ff")
    c.px(33, 11, "#5dff8a"); c.px(35, 11, "#ffb347"); c.px(33, 13, "#d9dfe5"); c.px(35, 13, "#d9dfe5")
    # çıkış tepsisi
    c.rect(0, 15, 3, 17, PLASTIC[1])
    c.rect(0, 14, 3, 14, "#ffffff")
    # çekmeceler
    for y0 in (18, 26):
        c.hline(5, 36, y0, PLASTIC[1])
        c.hline(5, 36, y0 + 6, PLASTIC[1])
        c.rect(17, y0 + 3, 24, y0 + 3, "#3a4048")
    c.hline(4, 37, 35, "#3a4048")
    # koliler
    c.box(40, 23, 58, 35, CARDBOARD)
    c.box(42, 13, 56, 23, CARDBOARD)
    for y0, y1, x0, x1 in ((23, 35, 40, 58), (13, 23, 42, 56)):
        mx = (x0 + x1) // 2
        c.vline(mx, y0 + 1, y1 - 1, CARDBOARD[3])
        c.rect(x0 + 2, y0 + 3, x0 + 6, y0 + 5, "#f4f1ea")
        c.hline(x0 + 3, x0 + 5, y0 + 4, "#9a9a9a")
    return c


def monstera(rng: random.Random) -> Canvas:
    c = Canvas(26, 36)
    leaves = [(13, 9, 6.2, 4.6), (7, 14, 5.4, 4.0), (19, 14, 5.6, 4.2), (10, 5, 4.4, 3.6), (17, 6, 4.2, 3.4), (13, 17, 5.2, 3.6)]
    mask: set[tuple[int, int]] = set()
    for cx, cy, rx, ry in leaves:
        mask |= ellipse(cx, cy, rx, ry)
    # yaprak yarıkları (devetabanı)
    for cx, cy, rx, ry in leaves[:3]:
        for side in (-1, 1):
            for k in range(2):
                x = int(cx + side * (rx - 1 - k))
                y = int(cy + (k - 0.5) * 2)
                mask.discard((x, y))
                mask.discard((x + side, y))
    c.solid(mask, LEAF)
    for cx, cy, rx, ry in leaves[:3]:  # damar
        for x in range(int(cx - rx + 2), int(cx + rx - 1)):
            if (x, int(cy)) in mask:
                c.px(x, int(cy), LEAF[1])
    # gövde ve saksı
    c.vline(13, 20, 24, "#2f5f2a")
    pot = {(x, y) for y in range(24, 36) for x in range(6 + (y - 24) // 4, 20 - (y - 24) // 4)}
    c.solid(pot, TERRACOTTA)
    c.box(5, 23, 20, 26, TERRACOTTA)
    c.hline(7, 18, 24, "#3b2416")
    return c


def trash(rng: random.Random) -> Canvas:
    c = Canvas(14, 16)
    for (x, y, r) in ((5, 3, 2.6), (9, 2.6, 2.2), (7, 1.6, 1.8)):
        c.solid(ellipse(x, y, r, r * 0.85), ("#8a8a8a", "#c9c9c9", "#e9e9e9", "#ffffff"))
    body = {(x, y) for y in range(4, 16) for x in range(1 + (y - 4) // 6, 13 - (y - 4) // 6)}
    c.solid(body, ("#22272d", "#4a545e", "#6c7782", "#97a2ad"))
    for x in range(3, 12, 2):
        c.vline(x, 6, 14, "#3c444d")
    c.hline(1, 12, 4, "#b7c0c9")
    return c


def sink(rng: random.Random) -> Canvas:
    c = Canvas(36, 30)
    c.box(1, 10, 34, 29, CABINET)
    c.vline(17, 12, 27, CABINET[1])
    c.px(15, 18, "#6b6155"); c.px(19, 18, "#6b6155")
    c.hline(2, 33, 28, CABINET[1])
    # havlu
    c.rect(4, 12, 10, 21, "#4fa3e0")
    c.vline(4, 12, 21, "#2f7fbf")
    c.hline(4, 10, 15, "#ffffff"); c.hline(4, 10, 18, "#ffffff")
    c.hline(3, 11, 11, "#9aa2ab")
    # tezgâh + evye
    c.box(0, 6, 35, 10, STONE)
    c.rect(11, 7, 24, 8, "#2a3038")
    c.hline(12, 23, 7, "#9aa4af")
    # musluk
    c.rect(17, 1, 18, 6, METAL[2])
    c.rect(17, 1, 22, 2, METAL[2])
    c.px(22, 3, METAL[1])
    c.vline(19, 2, 2, METAL[3])
    # sabun
    c.box(27, 2, 30, 6, ("#0f3d23", "#2e8b57", "#3fbf7f", "#8fe3b4"))
    c.rect(28, 0, 29, 1, "#dddddd")
    return c


def water_cooler(rng: random.Random) -> Canvas:
    c = Canvas(18, 36)
    c.solid(ellipse(9, 6.5, 6.4, 6.2) | {(x, y) for x in range(3, 16) for y in range(6, 12)}, WATER)
    c.vline(6, 3, 10, "#e6f6ff")
    c.rect(7, 12, 11, 13, "#1d4a78")
    c.box(2, 13, 16, 35, PLASTIC)
    c.rect(5, 17, 13, 22, "#3a4048")
    c.px(7, 20, "#e74c3c"); c.px(11, 20, "#3498db")
    c.rect(6, 23, 12, 24, "#7f8892")
    c.rect(14, 15, 16, 24, "#e8ecef")
    c.hline(14, 16, 15, "#9aa2ab")
    return c


PROPS = {"bookshelf": bookshelf, "coffee": coffee_corner, "copier": copier, "plant": monstera, "trash": trash,
         "sink": sink, "water": water_cooler}


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    made = agent_sprites()
    for name, fn in PROPS.items():
        fn(random.Random(f"kayaai-{name}")).im.save(OUT / f"{name}.png")
        made.append(f"{name}.png")
    (OUT / "LICENSE.txt").write_text(
        "kayaAI ofis çizimleri.\n"
        "- <ajan>-walk-*.png, <ajan>-person.png: free-office-pixel-art (arlantr, \"Free to use any way you want\") çizimlerinden\n"
        "  renk değiştirilerek türetildi (bkz. ../LICENSE.txt).\n"
        "- Eşyalar (bookshelf, coffee, copier, plant, trash, sink, water): kayaAI için kodla çizildi (scripts/office_art.py).\n",
        encoding="utf-8")
    print(f"{len(made)} çizim -> {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
