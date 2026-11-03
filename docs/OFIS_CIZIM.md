# Ofis çizimleri — kendi karakterlerini koy (pixel stil, Adım 21)

Ofis (sol menü → **Ofis**) önden-üstten bir **pixel** ofis. Hazır çizimler free-office-pixel-art paketinden (arlantr,
"free to use any way you want", `ui/public/office/pixel/LICENSE.txt`). Kendi çizdiğin her resim hazır çizimin yerine
geçer; çizmediklerin hazır kalır. Yani istediğin kadarını, istediğin sırayla çizebilirsin.

## Nereye?

`data\ofis\` klasörü (kayaAI klasörünün içinde). Yoksa oluştur. Dosyayı koy → Ofis → **🎨 Çizimler → Yenile**.
Arayüzü yeniden derlemek gerekmez; güncellemeler (`git pull`) bu klasöre dokunmaz.

## Hangi adla?

Küçük harf, Türkçe karakter yok, `.png`, en çok 5 MB.

| Kim | Masada oturan (arkadan) | İsteğe bağlı durumlar | Yürüyen |
| --- | --- | --- | --- |
| Genel / Veri / Belge / Kod / Görsel / Denetçi | `genel.png`, `veri.png`, `belge.png`, `kod.png`, `gorsel.png`, `denetci.png` | `veri-calisiyor.png`, `-bekliyor`, `-hata`, `-bitti`, `-bosta` | `veri-yuruyor.png` ya da yönlü `veri-yuruyor-asagi.png`, `-yukari`, `-sol`, `-sag` |
| Şef | `sef.png` | aynı ekler | `sef-yuruyor.png` … |
| Sen | `sen.png` (masanda arkadan) | `sen-bekliyor.png` (onay bekleyen iş varken) | `sen-yuruyor-…` (işi Şef'e götürürken) |
| Adı olmayan (geçici) ajanlar | `ajan.png` | aynı ekler | `ajan-yuruyor.png` |
| Boş masa (ajan kalkınca) | `masa.png` | | |
| Zemin karosu | `zemin.png` (16×16, döşenir) | | |

Durum resmi yoksa genel resim, o da yoksa hazır çizim kullanılır. Tek `-yuruyor.png` aşağı bakan yürüme olarak
kullanılır, sola giderken yansıtılır; yön yön çizersen her yön kendi resmini kullanır.

## Ölçüler (pixel)

- **Her kare 64×64 piksel**, arka plan şeffaf.
- **Masada oturan:** masa + arkadan oturan kişi tek resimde. Masanın/sandalyenin en alt satırı **61. satır**
  (hazır `worker1.png` ile aynı). Kişinin başı ekranın önünde, yaklaşık 13–30. satırlar arasında.
- **Yürüyen:** kişi karenin ortasında, **ayakları 48. satırda** (hazır `Julia_walk_Foward.png` ile aynı).
- **Animasyon:** kareleri **yan yana** diz. 4 karelik yürüme → 256×64, 2 karelik "yazıyor" → 128×64. Kare sayısını
  kayaAI resmin genişliği / yüksekliğinden anlar.
- **Zemin:** 16×16 karo, kenarları birbirine uyacak şekilde.
- Ekranda 2 kat büyütülür ve bulanıklaşmaz (pixel kalır).

## Büyük ya da yapay zekâyla üretilmiş resimler: `kayaai ofis ice-aktar`

Yapay zekâ araçları "pixel art"ı büyük çözünürlükte verir (ör. 2688×1152, her piksel ~20 gerçek piksel). Bu komut
resmi sahnenin pixel çizimine çevirip doğru adla `data\ofis\`'e yazar:

- Pixel ızgarasını kendisi bulur ve asıl çözünürlüğe indirir (yüz, sakal gibi ayrıntılar korunur).
- Karakter sayfasındaki figürleri (saydam boşluklarla ayrılmış) kare kare dizer; `--sec N` ile tek figür seçilir.
- Yürüyeni ayak 48. satıra, oturanı 61. satıra, masayı 48. satıra hizalar; yarı saydam kenarları temizler.
- Hazır `worker1/2/4.png`'den türettiğin oturan çizimden masayı çıkarır (yalnız kişi kalır, masan ayrıca çizilir);
  istemezsen `--masayi-koru`.

```powershell
kayaai ofis ice-aktar mertkaya_walking.png sen-yuruyor-asagi          # 4 kare yürüme
kayaai ofis ice-aktar mertkaya_character.png sen-yuruyor-sag --sec 2   # karakter sayfasının 2. figürü
kayaai ofis ice-aktar mertkaya_character.png sen-yuruyor-yukari --sec 3
kayaai ofis ice-aktar mertkaya_character.png sen-yuruyor-sol --sec 4
kayaai ofis ice-aktar worker1.png sen                                 # masada oturan (masası çıkarılır)
kayaai ofis ice-aktar damacana.png su                                 # eşya
kayaai ofis                                                            # klasörde ne var, kaç kare
```

Sonra Ofis → 🎨 Çizimler → **Yenile**. Resmin arka planı **saydam** olmalı (PNG).

## Masa ve zemin

- **Masa (`masa.png`)**: bütün ajan masalarının yerine geçer; oturan kişi masanın **önüne/üstüne** çizilir (arkadan
  görünen kişi, monitöre bakar). Kalıp: `ui\public\office\pixel\desk-with-pc.png` — 64×64 tuval, masanın alt
  kenarı **48. satırda**, ortada; monitör üst ortada (kişinin başı onun önüne gelir). Çizip doğrudan `masa.png` olarak
  koyabilirsin ya da büyük bir resmi `kayaai ofis ice-aktar masam.png masa` ile çevirirsin. Çalışırken ekranı oynayan
  hazır masa yalnız masa.png yokken kullanılır.
- **Zemin (`zemin.png`)**: 16×16 karo, döşenir. Kenarları birbirine uymalı (soldaki sütun sağdakinin devamı). Büyük
  bir doku resmini `kayaai ofis ice-aktar zeminim.png zemin` 16×16'ya indirir.
- **Eşyalar**: `su.png` (su sebili), `dolap.png`, `kahve.png`, `yazici.png`, `bitki.png` (iki bitki), `cop.png`,
  `lavabo.png` — hazırın yerine geçer, alt ortasından yere oturur; çok büyükse hazır eşyanın 1,5 katına sığdırılır.

## En kolay yol: hazır çizimi kalıp yap

1. `ui\public\office\pixel\` klasöründeki `worker1.png` (masada) ve `Julia_walk_Foward.png` (yürüme) dosyalarını
   kopyala.
2. Ücretsiz bir pixel programında aç: **Piskel** (tarayıcıda, piskelapp.com), **LibreSprite**; ücretli ve en rahatı
   **Aseprite**.
3. Saçı, kıyafeti, ten rengini değiştir (ör. Veri yeşil gömlek, Kod pembe kapüşon). Kare boyutunu ve hizayı bozma.
4. `kayaai ofis ice-aktar worker1-veri.png veri` (masayı çıkarır) ya da doğrudan `data\ofis\veri.png` → **Yenile**.

İpuçları: Önce tek ajanla dene, sahnede nasıl durduğunu gör, sonra diğerlerini çiz. "Çalışıyor" için 2 kare yeter;
"bekliyor" için el kaldırmış bir kare. Panelde **Tanınmayan ad** ya da **Atlandı** uyarısı çıkarsa adı/biçimi kontrol et.
Gerçek bir markanın logosu/etiketi (ör. su şişesi markası) satacağımız üründe kullanılmamalı; kendi bilgisayarında
sorun değil, ama ürüne koyacağın çizimlerde etiketi genel yap.

## Lisans

Hazır çizimler: arlantr, free-office-pixel-art ("Free to use any way you want"). Başka bir paket eklersen yalnız
**CC0** ya da açıkça "ticari kullanım serbest" yazanları kullan ve lisans dosyasını yanına koy (ürünü satacağız).
Dosyaların tek tek dağıtılmasını yasaklayan paketleri (ör. ModernOffice2DProps) depoya koyma.
