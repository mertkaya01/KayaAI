# Referans repolar — inceleme notları

Sahibin önerdiği referans repolar (2026-10-31). **Hiçbirinden kod kopyalanmadı**; yalnızca tasarım fikirleri alındı
ve aşağıda kaynak gösterildi. Bir repodan kod alınacaksa önce lisansı kontrol edilir ve bu dosyaya yazılır.

## Adım 7 (ajan sistemi) için incelenenler

| Repo | Lisans | Alınan fikir | kayaAI'deki karşılığı |
|---|---|---|---|
| [Donchitos/Claude-Code-Game-Studios](https://github.com/Donchitos/Claude-Code-Game-Studios) | MIT | Anlaşmazlıklar adlandırılmış bir karar verene yükselir; titizlik seviyesi (full/lean/solo); kanıta dayalı tamamlama; ajan tanımlarının kendilerinin test edilmesi | Anlaşmazlık → Claude şef (açıksa) ya da sahip; `conductor.review` + ajan başına `review.required`; gözden geçirici her sorun için cevaptan alıntı vermek zorunda; `load_definitions` doğrulaması ve ajan testleri |
| [cobusgreyling/loop-engineering](https://github.com/cobusgreyling/loop-engineering) | MIT | Doğrulayıcı kapısı (güvenilirlik kanıtlanmadan özerklik yok); bütçe sınırı; her koşunun kaydı | Geçici ajan en az bir başarılı kullanım + sahip onayı olmadan kalıcı olamaz; `conductor.time_budget_s`; `decision.summary` olayı ve `scripts/agents_check.py` raporu |
| [arturitu/the-delegation](https://github.com/arturitu/the-delegation) | Kod MIT, 3B varlıklar CC BY-NC 4.0 | Ajan başına insan onayı kapısı; rol başına model seçimi; görsel takım akışı | Onay merkezi (Adım 5–6, zaten vardı); ajan tanımında `local_model`/`claude_tier`; görsel iş akışı Adım 11'e not edildi. Kod (Three.js/Gemini) kullanılmadı |
| [SeloGPT/selogpt-prompt-labs](https://github.com/SeloGPT/selogpt-prompt-labs) | **Lisans dosyası yok** | — | **Kullanılmadı.** İçerik, modellerin güvenlik sınırlarını aşmaya yönelik "manipülasyon" analizleri; ajan talimatları için uygun değil ve lisanssız içerik kopyalanamaz |

## Yol haritası sonrası tam inceleme (2026-11-01)

Sahibin "her şey bitince" notu üzerine tüm liste yeniden incelendi (repolar `--depth 1` indirildi, yalnız okundu, hiçbir
şey çalıştırılmadı). Kod kopyalanmadı.

| Repo | Lisans | kayaAI için ne var | Karar |
|---|---|---|---|
| [cobusgreyling/loop-engineering](https://github.com/cobusgreyling/loop-engineering) (güncel, v1.5) | MIT | "10 anti-pattern" listesi otomasyon için kontrol listesi: aynı ajanın kendini doğrulaması, deneme sınırı yok, şemasız ortak durum, her şeye yazabilen MCP, **kill switch yok**, çalışma kaydı yok; yeni otomasyon önce "yalnız rapor" kipinde; yol/dosya yasak listesi (`.env`, `secrets/`, `payments/`…) | kayaAI 10 maddenin 9'unu zaten karşılıyor (ayrı gözden geçirici, deneme sınırları, pydantic şemalar, onaysız MCP, çalışma geçmişi). **Eksik: genel "otomasyonu duraklat" anahtarı** → öneri 1. Dosya yazma için yasak liste → öneri 2 |
| [sindresorhus/awesome](https://github.com/sindresorhus/awesome) | CC0 | Meta liste. İlgili alt listeler: Prompt Injection, Web Accessibility (a11y), Windows, Playwright, FastAPI, Home Assistant (yerel kontrol) | Prompt injection: tarayıcı ajanı ve belge özeti güvenilmez metin okuyor — kayaAI'de metin "veri" olarak işaretli, riski kod belirliyor, istenmeyen R3 kodla reddediliyor (v0.12.4). a11y → öneri 4 |
| [public-apis/public-apis](https://github.com/public-apis/public-apis) | MIT | Anahtarsız ücretsiz API'ler: **Frankfurter** (ECB döviz kurları), **Nager.Date** (Türkiye dahil resmi tatiller), **Nominatim** (adres↔konum; 1 istek/sn, atıf), **Open-Meteo** (hava — yalnız ticari olmayan kullanım), Wikipedia | Yerel-öncelik ilkesi: her dış çağrı bilgisayardan veri çıkarır → yalnız sahip açarsa ve kayda geçerek. Döviz kuru (satış raporunda TL dönüşümü) ve tatil takvimi (zamanlanmış görevlerde "tatilde çalışma") en faydalıları → öneri 3. Open-Meteo'nun ticari olmayan şartı not edildi |
| [donnemartin/system-design-primer](https://github.com/donnemartin/system-design-primer) | CC BY 4.0 | Tutarlılık/erişilebilirlik, tek yazıcı veritabanı, önbellek, kuyruk ve geri basınç | Bugün tek PC + SQLite WAL doğru seçim. Çok cihaz gündeme gelirse (sahip kararı): tek "ana" bilgisayar yazar, diğerleri API üzerinden okur — `data\` klasörünü bulutla eşitlemek SQLite'ı bozar (DEPLOYMENT.md §7'de uyarı var) |
| [ripienaar/free-for-dev](https://github.com/ripienaar/free-for-dev) | lisans dosyası yok (liste) | Bulut hizmetlerinin ücretsiz katmanları | Kullanılmadı: kayaAI 0 TL ve yerel; özel veri buluta gitmez. İleride yalnız şifreli yedek hedefi aranırsa bakılabilir |
| [sdmg15/Best-websites-a-programmer-should-visit](https://github.com/sdmg15/Best-websites-a-programmer-should-visit) | MIT | Öğrenme kaynakları listesi | Ürüne katkı yok; sahibin öğrenmesi için |
| [microsoft/Web-Dev-For-Beginners](https://github.com/microsoft/Web-Dev-For-Beginners) | MIT | Web geliştirme müfredatı; erişilebilirlik dersi | Ürüne doğrudan katkı yok; a11y dersi öneri 4'te kullanılabilir |
| Donchitos/Claude-Code-Game-Studios, arturitu/the-delegation | MIT / kod MIT | Adım 7'de incelendi (yukarıda) | Görsel iş akışı fikri Adım 11'de yapıldı (Akış sekmesi) |
| SeloGPT/selogpt-prompt-labs | lisans yok | Adım 7'de incelendi | Kullanılmadı (yukarıda) |

### Öneriler (sahip seçer)

1. **Otomasyonu duraklat anahtarı** (loop-engineering "kill switch"): Kontrol Merkezi'nde tek düğme ve `kayaai pause|resume`;
   duraklatılınca zamanlanmış görevler "duraklatıldı" diye atlanır, tarayıcı işi başlamaz, sürenler güvenle durur.
   Küçük iş, yüksek güven kazancı.
2. **Dosya yazma yasak listesi**: izinli klasörde bile `.env`, `*.key`, `*.pem`, `id_rsa*`, `*secret*` gibi adlara yazma/
   üzerine yazma kodla reddedilir (belge dizinindeki gizli dosya kuralının yazma tarafı).
3. **İsteğe bağlı dış veri kaynakları** (sahip açarsa): Frankfurter döviz kuru (satış raporunda TL/EUR/USD), Nager.Date
   Türkiye tatilleri (zamanlanmış görev "resmi tatilde çalışma" seçeneği). Her çağrı kayda geçer; varsayılan kapalı.
4. **Erişilebilirlik geçişi**: Control Center'da klavye ile tüm akışlar, odak görünürlüğü, renk kontrastı, ekran okuyucu
   etiketleri (awesome-a11y kontrol listesi).

## Sonraki adımlarda bakılacaklar


| Repo | Ne zaman | Not |
|---|---|---|
| sindresorhus/awesome, ripienaar/free-for-dev, public-apis/public-apis | ihtiyaç doğdukça | Kaynak listeleri; ücretsiz/yerel araç ararken |
| donnemartin/system-design-primer | Adım 13 (ölçekleme, çoklu cihaz) | Mimari referans |
| sdmg15/Best-websites-a-programmer-should-visit, microsoft/Web-Dev-For-Beginners | Adım 8/11 arayüz işleri | Öğrenme kaynakları |
