# Fine-tuning değerlendirmesi (2026-11-01)

Sahip sorusu: "kayaAI'nin yerel modellerini kendi verimle eğitsek (fine-tuning) daha iyi olur mu?"

## Kısa cevap

**Şimdilik hayır; önce ölç.** Fine-tuning ancak belirli bir ajanın belirli bir işte *ölçülebilir şekilde* düştüğü ve
istem/model değişikliğinin düzeltmediği durumda değer. Karar için `kayaai quality` eklendi: bu bilgisayardaki görev
kayıtlarından ajan × model başına ilk denemede geçerli çıktı oranını çıkarır. Bir ajan "aday" çıkarsa sıradaki adımlar
aşağıda.

## Fine-tuning neyi çözer, neyi çözmez

| İhtiyaç | Fine-tuning? | kayaAI'de bugün ne çözüyor |
| --- | --- | --- |
| Senin belgelerin, müşterilerin, fiyatların (bilgi) | **Hayır** — model ezberler, güncellenmez, yanlış hatırlar | Hafıza + belge dizini (RAG, Adım 8) |
| Güncel bilgi (kur, tatil) | Hayır | Dış veri kaynakları (Adım 14c) |
| Belirli bir JSON biçimine her seferinde uyma | **Evet, en iyi kullanım** | Şema zorlaması + 3 deneme + doğrulayıcı |
| Sabit bir üslup / Türkçe ifade tarzı | Evet (ama örnekle istem çoğu zaman yeter) | Ajan istemleri, Türkçe kontrolü |
| Dar bir sınıflandırma (ör. isteği hangi ajana yollamak) | Evet | Şef planlayıcı + kurallar |
| Genel zekâ, akıl yürütme | Hayır — küçük veriyle düşer bile | Daha büyük model / Claude modu |

## Donanım ve araçlar (bu PC: RTX 5070 Ti 16 GB)

- **Yöntem:** QLoRA (4-bit taban + küçük LoRA katmanları). 7–8B model 16 GB'a sığar (kısa bağlamla); 14B sınırda,
  denenmeden söz verilmez. Tam ağırlıklı eğitim bu kartta mümkün değil.
- **Araç:** Unsloth (açık kaynak; Windows'ta ve RTX 50 / Blackwell'de çalıştığını belirtiyor). PyTorch ile birlikte
  birkaç GB eder → **kayaAI'nin ortamına kurulmaz**, ayrı bir klasör/ortam olur; kayaAI ona bağımlı olmaz.
- **Ollama'ya alma:** LoRA tabana birleştirilip GGUF'a çevrilir, `Modelfile` içinde `FROM ./model.gguf` ile
  `ollama create` yapılır (Ollama GGUF içe aktarmayı belgeliyor). Sonra kayaAI'de **Modeller** sayfasında aday olarak
  kaydedilir, `kayaai models compare` ile mevcut modelle karşılaştırılır, ancak kazanırsa aktif edilir (Adım 11).
- **Lisans:** Qwen3 (Apache-2.0) türevlerine izin verir. Llama türevleri Meta lisansına bağlıdır.
- **Maliyet:** 0 TL (yerel GPU). Süre: birkaç yüz örnekle 8B için onlarca dakika–birkaç saat (ölçülecek).

## Riskler

- **Veri:** Eğitim verisi senin sohbetlerinden/görevlerinden gelir. Bilgisayardan çıkmaz ama kişisel bilgi modelin
  içine "gömülür" → hangi kayıtların kullanılacağını **sen seçersin**, hafızadaki gizli kayıtlar hiç kullanılmaz.
- **Gerileme:** Dar veriyle eğitilen model başka işlerde kötüleşebilir (özellikle Türkçe genel sohbet). Bu yüzden
  yalnız ilgili ajana atanır; taban model yerinde kalır, geri dönüş tek tık.
- **Bakım:** Taban model güncellenince (ör. Qwen3 → sonraki sürüm) eğitim tekrarlanmalı.
- **Az veri:** Birkaç düzine örnekle anlamlı iyileşme beklenmez; tipik alt sınır birkaç yüz temiz örnek.

## Karar sırası (bir ajan "aday" çıkarsa)

1. `kayaai quality` → hangi ajan, hangi hata türü (şema mı, doğrulama mı, kesilme mi, zaman aşımı mı).
2. **İstem düzeltmesi:** başarısız örneklere bakıp ajan istemine örnek/kural eklemek (en ucuz, çoğu zaman yeter).
3. **Model değişikliği:** `kayaai models compare <ajan> <aday>` — başka/büyük bir yerel model (Adım 11).
4. Hâlâ hedefin altındaysa **dar LoRA:** yalnız o ajanın başarılı görevlerinden (sen onaylarsın) eğitim seti →
   ayrı ortamda eğitim → GGUF → aday model → karşılaştırma → kazanırsa yalnız o ajana atama.

## `kayaai quality` kuralları

- Yalnız yerel modelin ürettiği çıktılar sayılır; şef/tarayıcı üst görevleri ve Claude görevleri sayılmaz.
- Ölçülen biçim ve doğrulamadır; cevabın *doğruluğu* `kayaai models compare` ve gözden geçiren ajanla izlenir.
- Sayılanlar: biten görevler (başarılı, geçersiz çıktı, zaman aşımı, diğer hata). İptal/ret/bekleyen sayılmaz.
- Ollama bağlantı hatası gibi altyapı hataları modelin kalitesine sayılmaz ("değerlendirilen" sayıdan düşülür).
- **Aday:** en az 30 değerlendirilen görevde ilk-deneme oranı < %85 ya da geçersiz çıktı > %5.
- Çıktı: ekranda tablo + `data/quality.json`. Model çağrılmaz, hiçbir şey dışarı gönderilmez.

## İlk ölçüm — sahibin bilgisayarı (2026-11-01)

Tüm geçmiş, yerel model çıktıları (yalnız modelin ürettikleri):

| Ajan | Model | Görev | İlk deneme | Geçersiz | Karar |
| --- | --- | ---: | ---: | ---: | --- |
| general | qwen3:8b | 77 | %100 | %0 | gerek yok |
| planner | qwen3:8b | 33 | %100 | %0 | gerek yok |
| coder | qwen2.5-coder:7b | 19 | %100 | %0 | yetersiz veri |
| browser.step | qwen3:8b | 12 | %100 | %0 | yetersiz veri |
| reviewer | qwen3:8b | 10 | %100 | %0 | yetersiz veri |
| data, vision, diğerleri | — | 1'er | %100 | %0 | yetersiz veri |

Hiçbir görevde şema ya da doğrulama hatası, zaman aşımı veya kesilen cevap yok; hız 126–149 token/sn.
**Sonuç: fine-tuning gerekmiyor.** Şema hatasının hiç olmaması beklenen bir şey: Ollama çıktıyı JSON şemasıyla
kısıtlıyor. Asıl sinyal doğrulama hataları ve cevabın doğruluğu olacak. Kullanım arttıkça `kayaai quality --days 30`
ara sıra yeniden bakılır; bir ajan "aday" olursa yukarıdaki karar sırası uygulanır.

