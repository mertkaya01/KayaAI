# Ofis çizimleri — kendi karakterlerini koy

Ofis (sol menü → **Ofis**) kendi çizimlerinle çalışır. Çizim koymadığın her şey için mevcut basit şekiller görünür; yani
istediğin kadarını, istediğin sırayla çizebilirsin.

## Nereye?

`data\ofis\` klasörü (kayaAI klasörünün içinde). Yoksa oluştur. Dosyayı koy → Ofis sayfasında **🎨 Çizimler → Yenile**.
Arayüzü yeniden derlemek gerekmez; güncellemeler (`git pull`) bu klasöre dokunmaz.

## Hangi adla?

Küçük harf, Türkçe karakter yok, `.png` (ya da `.svg`, `.webp`), en çok 5 MB.

| Kim | Genel resim | İsteğe bağlı durum resimleri |
| --- | --- | --- |
| Şef | `sef.png` | `sef-calisiyor.png`, `sef-bekliyor.png`, `sef-yuruyor.png`, `sef-hata.png`, `sef-bitti.png` |
| Sen | `sen.png` | aynı ekler (`sen-bekliyor.png` = onay bekleyen iş varken) |
| Genel / Veri / Belge / Kod / Görsel / Denetçi | `genel.png`, `veri.png`, `belge.png`, `kod.png`, `gorsel.png`, `denetci.png` | `veri-calisiyor.png` gibi |
| Claude | `claude.png` | |
| Adı olmayan (geçici) ajanlar | `ajan.png` | `ajan-yuruyor.png` gibi |
| Masa | `masa.png` | |
| Zemin karosu | `zemin.png` | |

Durum resmi yoksa karakterin genel resmi, o da yoksa şimdiki şekil kullanılır.

## Ölçüler (öneri)

- **Karakter:** 96×128 piksel, arka planı şeffaf, **ayakları resmin alt ortasında**. Masanın arkasında durur gibi düşün:
  alt kısmı masanın arkasında kalabilir.
- **Masa:** yaklaşık 160×140, izometrik (sol-ön ve sağ-ön yüzü görünen), alt ortası masanın önü.
- **Zemin karosu:** 96×48 elmas (izometrik); kenarları birbirine değecek şekilde.
- Piksel sanat, düz renk, çizgi — hepsi olur; resimler orana uyacak şekilde ölçeklenir.

## İpuçları

- Önce tek karakter (`veri.png`) ve `masa.png` dene; nasıl durduğunu gör, sonra diğerlerini çiz.
- "Çalışıyor" hâli için ekrana bakan ya da yazan bir poz; "bekliyor" için el kaldırmış; "yürüyor" için adım atan.
- Panelde **Tanınmayan ad** ya da **Atlandı** uyarısı çıkarsa dosya adını/biçimini kontrol et.
