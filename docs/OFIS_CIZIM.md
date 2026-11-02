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
| Sen | `sen.png` (masanla birlikte) | `sen-bekliyor.png` (onay bekleyen iş varken) | — |
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

## En kolay yol: hazır çizimi kalıp yap

1. `ui\public\office\pixel\` klasöründeki `worker1.png` (masada) ve `Julia_walk_Foward.png` (yürüme) dosyalarını
   kopyala.
2. Ücretsiz bir pixel programında aç: **Piskel** (tarayıcıda, piskelapp.com), **LibreSprite**; ücretli ve en rahatı
   **Aseprite**.
3. Saçı, kıyafeti, ten rengini değiştir (ör. Veri yeşil gömlek, Kod pembe kapüşon). Kare boyutunu ve hizayı bozma.
4. `veri.png` ve `veri-yuruyor.png` adıyla `data\ofis\`'e kaydet → **Yenile**.

İpuçları: Önce tek ajanla dene (`veri.png`), sahnede nasıl durduğunu gör, sonra diğerlerini çiz. "Çalışıyor" için
2 kare yeter (eller klavyede, bir kare yukarı); "bekliyor" için el kaldırmış bir kare. Panelde **Tanınmayan ad** ya da
**Atlandı** uyarısı çıkarsa dosya adını/biçimini kontrol et.

## Lisans

Hazır çizimler: arlantr, free-office-pixel-art ("Free to use any way you want"). Başka bir paket eklersen yalnız
**CC0** ya da açıkça "ticari kullanım serbest" yazanları kullan ve lisans dosyasını yanına koy (ürünü satacağız).
Dosyaların tek tek dağıtılmasını yasaklayan paketleri (ör. ModernOffice2DProps) depoya koyma.
