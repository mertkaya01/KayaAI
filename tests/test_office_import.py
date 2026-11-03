"""Adım 21b: sahibin (yapay zekâyla büyük çözünürlükte üretilmiş) çizimlerini sahnenin pixel çizimine çevirme."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from kayaai.office_assets import scan
from kayaai.office_import import DEFAULT_DESK, ImportError_, estimate_block, import_image, kind_for

PIX = DEFAULT_DESK.parent


def figure(w: int, h: int, color: tuple[int, int, int], step: int) -> np.ndarray:
    """Basit pixel karakter: gövde + 'bacak adımı' (step) farkı, saydam arka plan."""
    a = np.zeros((h, w, 4), dtype=np.uint8)
    a[: h // 3, 3: w - 3] = (*color, 255)            # baş
    a[h // 3: h - 6, 2: w - 2] = (30, 30, 30, 255)   # gövde
    a[h - 6:, 3 + step: 7 + step] = (10, 10, 10, 255)  # bacak
    a[h - 6:, w - 7 - step: w - 3 - step] = (10, 10, 10, 255)
    # gerçek çizimlerdeki gibi 1 piksellik ayrıntılar (göz, kemer, fermuar) — blok boyu böylece tek anlamlı
    a[h // 6, 6] = a[h // 6, w - 7] = (250, 250, 250, 255)
    a[h // 2, 2: w - 2] = (140, 100, 40, 255)
    a[h // 3: h - 6, w // 2] = (200, 200, 200, 255)
    a[h // 3 + 2, 4: 9] = (90, 90, 160, 255)
    return a


def ai_sheet(tmp: Path, n: int = 4, block: int = 20, halo: bool = True) -> Path:
    """Yapay zekâ çıktısı gibi: kareler arası boşluklu, her piksel block×block, kenarda görünmez yarı saydam hale."""
    frames = [figure(20, 35, (120, 80, 50), i % 2) for i in range(n)]
    gap = np.zeros((35, 10, 4), dtype=np.uint8)
    small = np.concatenate(sum(([f, gap] for f in frames), [])[:-1], axis=1)
    big = np.kron(small, np.ones((block, block, 1), dtype=np.uint8))
    big = np.pad(big, ((60, 60), (40, 40), (0, 0)))
    if halo:  # alfa 1'lik görünmez kenar (gerçek dosyalarda vardı): boyut hesabını bozmamalı
        big[20:40, :, 3] = np.maximum(big[20:40, :, 3], 1)
    p = tmp / "sheet.png"
    Image.fromarray(big).save(p)
    return p


def test_kind_for_names():
    assert [kind_for(n) for n in ["sen", "veri-calisiyor", "sen-yuruyor-sol", "masa", "zemin.png", "su", "dolap"]] == \
        ["seat", "seat", "walk", "desk", "floor", "prop", "prop"]
    for bad in ["patron", "veri-ucuyor", "Sen"]:
        with pytest.raises(ImportError_):
            kind_for(bad.lower() if bad != "Sen" else "Sen-yuruyor-xyz")


def test_walk_sheet_is_reduced_to_native_pixels_and_aligned(tmp_path):
    src = ai_sheet(tmp_path)
    r = import_image(src, "sen-yuruyor-asagi", tmp_path / "data")
    assert r["frames"] == 4 and r["frame"] == 64 and r["size"] == [256, 64] and 19 <= r["block"] <= 21
    assert r["figure_sizes"] == [[16, 35]] * 4  # dolu kısım (kenar sütunları saydam)
    out = np.array(Image.open(r["path"]))
    assert set(np.unique(out[:, :, 3])) <= {0, 255}  # pixel stil: yarı saydam yok
    for i in range(4):
        fr = out[:, i * 64:(i + 1) * 64, 3]
        ys, xs = np.where(fr > 0)
        assert ys.max() == 47 and abs((xs.min() + xs.max()) / 2 - 31.5) <= 1  # ayak 48. satırda, ortada
    one = import_image(src, "sen-yuruyor-sol", tmp_path / "data", pick=2)
    assert one["frames"] == 1 and one["size"] == [64, 64]
    with pytest.raises(ImportError_, match="figür var"):
        import_image(src, "sen-yuruyor-sag", tmp_path / "data", pick=9)


def test_big_figures_get_bigger_frames(tmp_path):
    big = np.kron(figure(30, 60, (200, 50, 50), 0), np.ones((10, 10, 1), dtype=np.uint8))
    Image.fromarray(np.pad(big, ((20, 20), (20, 20), (0, 0)))).save(tmp_path / "tall.png")
    r = import_image(tmp_path / "tall.png", "veri-yuruyor", tmp_path / "data")
    assert r["frame"] == 96 and r["size"] == [96, 96]  # sahne orantılı küçültür


def test_seat_from_template_keeps_person_and_drops_desk(tmp_path):
    w = np.array(Image.open(PIX / "worker1.png").convert("RGBA"))
    desk = np.array(Image.open(PIX / "desk-with-pc.png").convert("RGBA"))
    hair = (w[:, :, 3] > 0) & (np.abs(w.astype(int) - desk.astype(int)).sum(axis=2) > 0) & (np.arange(64)[:, None] < 40)
    edited = w.copy()
    edited[hair] = (90, 55, 35, 255)                  # saç kahverengi (masa rengine yakın!)
    edited[:, :, :3] = np.clip(edited[:, :, :3].astype(int) + 2, 0, 255)  # yeniden üretilmiş: renkler hafif kaymış
    Image.fromarray(edited).save(tmp_path / "worker1.png")
    r = import_image(tmp_path / "worker1.png", "sen", tmp_path / "data")
    person = np.array(Image.open(r["path"]).convert("RGBA"))
    assert r["block"] == 1.0 and r["size"] == [64, 64]
    kept = person[:, :, 3] > 0
    assert kept[hair].mean() > 0.95                   # saç korunur
    desk_only = (desk[:, :, 3] > 0) & ~((w[:, :, 3] > 0) & (np.abs(w.astype(int) - desk.astype(int)).sum(axis=2) > 0))
    assert kept[desk_only].mean() < 0.05              # masa atılır
    keep = import_image(tmp_path / "worker1.png", "veri", tmp_path / "data", keep_desk=True)
    assert (np.array(Image.open(keep["path"]))[:, :, 3] > 0).sum() == (edited[:, :, 3] >= 128).sum()


def test_prop_floor_and_assets_scan(tmp_path):
    bottle = np.zeros((1400, 1100, 4), dtype=np.uint8)
    bottle[100:1350, 300:800] = (120, 180, 230, 255)
    Image.fromarray(bottle).save(tmp_path / "su_buyuk.png")
    r = import_image(tmp_path / "su_buyuk.png", "su", tmp_path / "data")
    assert r["size"][1] <= 34 and r["kind"] == "prop"
    tile = np.kron(np.array([[[90, 70, 50, 255], [100, 80, 60, 255]], [[100, 80, 60, 255], [90, 70, 50, 255]]], dtype=np.uint8),
                   np.ones((160, 160, 1), dtype=np.uint8))
    Image.fromarray(tile).save(tmp_path / "zemin_buyuk.png")
    f = import_image(tmp_path / "zemin_buyuk.png", "zemin", tmp_path / "data")
    assert f["size"] == [16, 16]
    out = scan(tmp_path / "data")
    assert out["props"]["water"].startswith("/ofis/su.png") and out["floor"].startswith("/ofis/zemin.png")
    assert out["sizes"][out["props"]["water"]] == r["size"]


def test_estimate_block_small_images_are_real_pixel_art():
    w = np.array(Image.open(PIX / "worker1.png").convert("RGBA"))
    assert estimate_block(w) == 1.0


def test_cli(tmp_path, monkeypatch, capsys):
    from kayaai.cli import main

    monkeypatch.setenv("KAYAAI_DATA_DIR", str(tmp_path / "data"))
    src = ai_sheet(tmp_path)
    assert main(["ofis", "ice-aktar", str(src), "sen-yuruyor-asagi"]) == 0
    assert "4 kare, kare 64×64" in capsys.readouterr().out
    assert main(["ofis", "ice-aktar", str(src), "patron"]) == 1
    assert "Bilinmeyen ad" in capsys.readouterr().out
    assert main(["ofis"]) == 0
    assert "walk_down" in capsys.readouterr().out


def test_desk_is_aligned_like_the_default_desk(tmp_path):
    desk = np.zeros((900, 1200, 4), dtype=np.uint8)
    desk[100:700, 100:1100] = (110, 70, 40, 255)      # büyük, yapay zekâ boyutunda bir masa
    desk[700:800, 120:180] = desk[700:800, 1020:1080] = (60, 40, 20, 255)
    desk[300:310, 500:505] = (250, 250, 250, 255)     # 1 pikselden küçük ayrıntı yok: blok tahmini 1 kalabilir
    Image.fromarray(desk).save(tmp_path / "masam.png")
    r = import_image(tmp_path / "masam.png", "masa", tmp_path / "data")
    out = np.array(Image.open(r["path"]))
    ys, xs = np.where(out[:, :, 3] > 0)
    assert r["kind"] == "desk" and r["frame"] == 64 and ys.max() == 47 and ys.max() - ys.min() + 1 <= 36
