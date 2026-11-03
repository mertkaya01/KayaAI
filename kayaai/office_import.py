"""Ofis çizimi içe aktarma (Adım 21b): sahibin resmini sahnenin beklediği pixel çizime çevirip `data/ofis/`'e yazar.

Neden: yapay zekâ araçları "pixel art"ı büyük çözünürlükte üretir (ör. 2688×1152, her piksel ~20 gerçek piksel) ve
kareleri 64×64 değildir. Bu araç:
1. Saydam sütunlarla ayrılmış figürleri bulur (karakter sayfası → kareler); `sec` ile tek figür seçilebilir.
2. Pixel ızgarasını (blok boyutu) kendisi bulur ve resmi asıl çözünürlüğüne indirir (blok ortasından örnek);
   yarı saydamlık temizlenir (pixel stil: tam saydam / tam dolu).
3. Türüne göre yerleştirir: yürüyen → ayak kare yüksekliğinin 48/64'ünde, masada oturan → masanın altı 61/64'te,
   kareler yan yana; eşya → sıkı kırpılmış tek resim; zemin → 16×16 karo.
   Kare 64×64'e sığmıyorsa 96, 128… seçilir (sahne bu kareleri orantılı küçülterek aynı boyda gösterir).
4. Masada oturan çizimde hazır masa (desk-with-pc) pikselleri varsa çıkarılır: kişi, senin ya da hazır masanın
   üstüne çizilir (masa.png değişince herkesin masası değişir).
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from .office_assets import ACTORS, NAME_RE, PROPS, SPECIAL, STATES, folder

DEFAULT_DESK = Path(__file__).resolve().parent.parent / "ui" / "public" / "office" / "pixel" / "desk-with-pc.png"
WALK_FEET, SEAT_BOTTOM, DESK_BOTTOM = 48 / 64, 61 / 64, 48 / 64  # hazır kalıplarla aynı hizalar
MAX_SIDE = 4096
FIT_HEIGHT = {"walk": 40, "seat": 48, "desk": 36}  # piksel: hazır Julia ~33, oturan ~48, masa ~35


class ImportError_(ValueError):
    pass


def kind_for(name: str) -> str:
    """Hedef ada göre tür: walk | seat | desk | floor | prop."""
    stem = name.lower().removesuffix(".png")
    if stem == "masa":
        return "desk"
    if stem == "zemin":
        return "floor"
    if stem in PROPS:
        return "prop"
    base, _, state = stem.partition("-")
    if base not in ACTORS or (state and state not in STATES):
        raise ImportError_(f"Bilinmeyen ad: {stem!r}. Örnek: veri, veri-yuruyor, sen-yuruyor-sol, masa, zemin, su")
    return "walk" if state.startswith("yuruyor") else "seat"


def _binarize(arr: np.ndarray) -> np.ndarray:
    out = arr.copy()
    solid = out[:, :, 3] >= 128
    out[:, :, 3] = np.where(solid, 255, 0)
    out[~solid] = 0
    return out


def split_figures(arr: np.ndarray, min_gap: int | None = None) -> list[tuple[int, int, int, int]]:
    """Saydam sütun boşluklarıyla ayrılmış figürlerin kutuları (x0, y0, x1, y1)."""
    solid = arr[:, :, 3] >= 128
    cols = solid.any(axis=0)
    gap = min_gap if min_gap is not None else max(2, arr.shape[1] // 100)
    runs: list[list[int]] = []
    x = 0
    w = arr.shape[1]
    while x < w:
        if cols[x]:
            start = x
            while x < w and cols[x]:
                x += 1
            if runs and start - runs[-1][1] < gap:
                runs[-1][1] = x  # küçük boşluk: aynı figür (bacak arası gibi)
            else:
                runs.append([start, x])
        else:
            x += 1
    boxes = []
    for x0, x1 in runs:
        rows = solid[:, x0:x1].any(axis=1)
        ys = np.where(rows)[0]
        if len(ys) and (x1 - x0) * len(ys) > 16:
            boxes.append((x0, int(ys[0]), x1, int(ys[-1]) + 1))
    return boxes


def estimate_block(arr: np.ndarray) -> float:
    """Büyütülmüş pixel art'ta bir pikselin gerçek boyu (gerçek pixel art'ta 1). Küçük resim (≤256 px) zaten
    pixel art sayılır. Yöntem: düz renk koşularının (yatay) uzunlukları blok boyunun katlarıdır; koşuların çoğunun
    tam katı olduğu EN BÜYÜK blok boyu seçilir (20,6 gibi kesirli boylar da: yapay zekâ çıktıları)."""
    if max(arr.shape[:2]) <= 256:
        return 1.0
    solid = arr[:, :, 3] >= 128
    rgb = arr[:, :, :3].astype(int)
    h = arr.shape[0]
    runs: list[int] = []
    for y in range(0, h, max(1, h // 160)):
        row, m = rgb[y], solid[y]
        diff = np.abs(np.diff(row, axis=0)).sum(axis=1) >= 24
        cut = np.where(diff | ~m[1:] | ~m[:-1])[0]
        edges = np.concatenate(([-1], cut, [row.shape[0] - 1]))
        for a, b in zip(edges[:-1], edges[1:]):
            n = int(b - a)
            if n >= 2 and m[a + 1]:
                runs.append(n)
    if len(runs) < 20:
        return 1.0
    r = np.array(runs, dtype=float)
    hi = min(96.0, float(np.percentile(r, 20)) * 1.1)
    best = 1.0
    for b in np.arange(2.0, max(2.0, hi) + 0.05, 0.1):
        q = r / b
        if np.mean((np.abs(q - np.round(q)) < 0.18) & (np.round(q) >= 1)) >= 0.8:
            best = float(b)
    if best <= 1.5:
        return 1.0
    q = np.round(r / best)
    fit = (np.abs(r / best - q) < 0.18) & (q >= 1)
    return float(np.mean(r[fit] / q[fit]))  # kesirli boyu incelt


def to_native(arr: np.ndarray, block: float) -> np.ndarray:
    """Blok ortalarından örnekleyerek asıl çözünürlük; sonra yarı saydamlık temizlenir."""
    if block <= 1.5:
        return _binarize(arr)
    h, w = arr.shape[:2]
    nw, nh = max(1, round(w / block)), max(1, round(h / block))
    xs = np.minimum(w - 1, ((np.arange(nw) + 0.5) * w / nw).astype(int))
    ys = np.minimum(h - 1, ((np.arange(nh) + 0.5) * h / nh).astype(int))
    return _binarize(arr[np.ix_(ys, xs)])


def _trim(arr: np.ndarray) -> np.ndarray:
    solid = arr[:, :, 3] > 0
    if not solid.any():
        raise ImportError_("resim tamamen saydam")
    ys, xs = np.where(solid)
    return arr[ys.min():ys.max() + 1, xs.min():xs.max() + 1]


def _person_core(desk: np.ndarray, art: np.ndarray) -> np.ndarray | None:
    """Çizimin türetildiği hazır kalıpta (worker1/2/4 — en çok benzeyeni) kişinin + sandalyenin bölgesi: kalıp − masa."""
    best: tuple[int, np.ndarray] | None = None
    a = art.astype(int)
    for name in ("worker1", "worker2", "worker4"):
        p = DEFAULT_DESK.parent / f"{name}.png"
        if not p.is_file():
            continue
        w = np.array(Image.open(p).convert("RGBA")).astype(int)
        diff = (w[:, :, 3] >= 128) & ((desk[:, :, 3] < 128) | (np.abs(w[:, :, :3] - desk[:, :, :3]).sum(axis=2) > 0))
        core = _main_blob(diff)  # masadaki kâğıt/fare gibi küçük farklar hariç
        same = ((w[:, :, 3] >= 128) == (a[:, :, 3] >= 128)) & (np.abs(w[:, :, :3] - a[:, :, :3]).sum(axis=2) <= 90)
        score = int((same & ~core).sum())  # kişi dışında kalıba ne kadar benziyor
        if best is None or score > best[0]:
            best = (score, core)
    return best[1] if best else None


def _dilate(mask: np.ndarray, r: int) -> np.ndarray:
    out = mask.copy()
    for dy in range(-r, r + 1):
        for dx in range(-r, r + 1):
            out |= np.roll(np.roll(mask, dy, axis=0), dx, axis=1)
    return out


def strip_default_desk(arr: np.ndarray, desk_path: Path = DEFAULT_DESK) -> np.ndarray:
    """64×64 oturan çizimden hazır masayı çıkar: geriye kişi + sandalye kalır.
    Konuma göre: hazır kalıplarda kişinin durduğu bölge korunur (saç masayla aynı renkte olsa da), 2 piksellik kenar
    şeridinde yalnız masa renginden farklı olanlar kalır, dışarısı (masa) silinir. Kalıp yoksa renge göre."""
    if arr.shape[:2] != (64, 64) or not desk_path.is_file():
        return arr
    desk = np.array(Image.open(desk_path).convert("RGBA")).astype(int)
    a = arr.astype(int)
    solid = a[:, :, 3] >= 128
    near = np.zeros(solid.shape, dtype=bool)  # masa pikseli: renk yakın, 1 piksel kaymaya izin
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            d = np.roll(np.roll(desk, dy, axis=0), dx, axis=1)
            near |= (d[:, :, 3] >= 128) & (np.abs(a[:, :, :3] - d[:, :, :3]).sum(axis=2) <= 90)
    core = _person_core(desk, arr)
    if core is None:
        keep = solid & ~near
    else:
        # Kişi bölgesinde yalnız AYNI yerdeki masa pikseliyle birebir yakın olanlar atılır (saç masa renginde olsa da kalır)
        same_spot = (desk[:, :, 3] >= 128) & (np.abs(a[:, :, :3] - desk[:, :, :3]).sum(axis=2) <= 12)
        ring = _dilate(core, 2) & ~core
        outside_desk = desk[:, :, 3] < 128  # masanın hiç olmadığı yer (ör. sandalyenin altı, başın üstü)
        keep = solid & ((core & ~same_spot) | (ring & ~near) | (outside_desk & ~_dilate(desk[:, :, 3] >= 128, 1)))
        for _ in range(2):  # kişinin içinde kalan tek tük delikleri doldur (dört komşusundan en az üçü dolu)
            n = sum(np.roll(keep, s, axis=ax).astype(int) for s in (-1, 1) for ax in (0, 1))
            keep |= solid & core & (n >= 3)
    keep = _main_blob(keep)
    out = arr.copy()
    out[~keep] = 0
    return out


def _main_blob(mask: np.ndarray, min_share: float = 0.2) -> np.ndarray:
    """Kişiyi bırak, masadan kalan kırıntıları at: en büyük parça ve ona göre büyük parçalar (8-komşuluk)."""
    h, w = mask.shape
    label = np.zeros((h, w), dtype=int)
    sizes = [0]
    for y in range(h):
        for x in range(w):
            if mask[y, x] and not label[y, x]:
                n = len(sizes)
                stack, size = [(y, x)], 0
                label[y, x] = n
                while stack:
                    cy, cx = stack.pop()
                    size += 1
                    for ny in (cy - 1, cy, cy + 1):
                        for nx in (cx - 1, cx, cx + 1):
                            if 0 <= ny < h and 0 <= nx < w and mask[ny, nx] and not label[ny, nx]:
                                label[ny, nx] = n
                                stack.append((ny, nx))
                sizes.append(size)
    if len(sizes) == 1:
        return mask
    biggest = max(sizes[1:])
    keep_ids = [i for i, s in enumerate(sizes) if i and s >= biggest * min_share]
    return np.isin(label, keep_ids)


def _frame_size(fig_h: int, fig_w: int, bottom: float, room: float) -> int:
    """Figürü sığdıran en küçük kare (64'ün katı değil, 32'nin katı): yükseklik payı `room`."""
    f = 64
    while fig_h > f * room or fig_w > f * 0.95:
        f += 32
    return f


def import_image(src: Path, name: str, data_dir: Path, *, pick: int | None = None, keep_desk: bool = False) -> dict[str, Any]:
    stem = name.lower().removesuffix(".png")
    if not NAME_RE.match(f"{stem}.png"):
        raise ImportError_("ad küçük harf, Türkçe karakter yok, ör. sen-yuruyor-sol")
    kind = kind_for(stem)
    with Image.open(src) as im:
        if max(im.size) > MAX_SIDE:
            raise ImportError_(f"resim çok büyük (en çok {MAX_SIDE} piksel kenar)")
        arr = np.array(im.convert("RGBA"))
    block = estimate_block(arr)
    if kind in ("prop", "desk", "floor") or (arr.shape[:2] == (64, 64) and pick is None):
        boxes = [(0, 0, arr.shape[1], arr.shape[0])]  # tek parça (buhar, ayrı parçalar bölünmesin)
    else:
        boxes = split_figures(arr)
        if not boxes:
            raise ImportError_("resimde figür bulunamadı (arka plan saydam mı?)")
        if pick is not None:
            if not 1 <= pick <= len(boxes):
                raise ImportError_(f"resimde {len(boxes)} figür var; --sec 1..{len(boxes)}")
            boxes = [boxes[pick - 1]]
    figs = []
    for x0, y0, x1, y1 in boxes:
        fig = to_native(arr[y0:y1, x0:x1], block)
        if kind == "seat" and fig.shape[:2] == (64, 64) and not keep_desk:
            fig = strip_default_desk(fig)  # aynı kalıptan: masa çıkar, yerleşimi koru
            figs.append(("as-is", fig))
            continue
        fig = _trim(fig)
        limit = FIT_HEIGHT.get(kind)
        if limit and fig.shape[0] > 2 * limit:  # pixel olmayan büyük resim: hazır çizim boyuna indir
            fig = np.array(_fit_height(Image.fromarray(fig), limit))
        figs.append(("trim", fig))
    out_dir = folder(data_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{stem}.png"
    if kind == "floor":
        f = figs[0][1]
        src_tile = Image.fromarray(f)
        tile = src_tile.resize((16, 16), Image.BOX if max(src_tile.size) > 16 else Image.NEAREST)
        tile = Image.fromarray(_binarize(np.array(tile)))
        tile.save(out_path)
        return {"name": out_path.name, "kind": kind, "block": round(block, 2), "size": [16, 16], "frames": 1, "path": str(out_path)}
    if kind == "prop":
        img = Image.fromarray(figs[0][1])
        img = _fit_height(img, PROPS[stem][1])
        img.save(out_path)
        return {"name": out_path.name, "kind": kind, "block": round(block, 2), "size": list(img.size), "frames": 1,
                "path": str(out_path)}
    # Masa: alt kenarı 48. satırda (desk-with-pc gibi) — oturanın sandalyesi önünde kalır
    bottom, room = {"walk": (WALK_FEET, 0.72), "desk": (DESK_BOTTOM, 0.74)}.get(kind, (SEAT_BOTTOM, 0.93))
    if all(mode == "as-is" for mode, _ in figs):
        frame = 64
    else:
        frame = max(_frame_size(f.shape[0], f.shape[1], bottom, room) for _, f in figs)
    sheet = Image.new("RGBA", (frame * len(figs), frame), (0, 0, 0, 0))
    for i, (mode, f) in enumerate(figs):
        img = Image.fromarray(f)
        if mode == "as-is":
            sheet.alpha_composite(img, (i * frame, 0))
            continue
        x = i * frame + (frame - img.width) // 2
        y = round(frame * bottom) - img.height
        sheet.alpha_composite(img, (x, max(0, y)))
    sheet.save(out_path)
    return {"name": out_path.name, "kind": kind, "block": round(block, 2), "frames": len(figs), "frame": frame,
            "figure_sizes": [[f.shape[1], f.shape[0]] for _, f in figs], "size": list(sheet.size), "path": str(out_path)}


def _fit_height(img: Image.Image, max_h: int) -> Image.Image:
    if img.height <= max_h:
        return img
    w = max(1, round(img.width * max_h / img.height))
    small = img.resize((w, max_h), Image.BOX)  # çok küçültmede ortalama daha temiz; sonra pixel stile döndür
    return Image.fromarray(_binarize(np.array(small)))


def frames_hint(width: int, height: int) -> int:
    return max(1, math.floor(width / height + 0.5))
