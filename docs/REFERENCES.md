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

## Sonraki adımlarda bakılacaklar

| Repo | Ne zaman | Not |
|---|---|---|
| sindresorhus/awesome, ripienaar/free-for-dev, public-apis/public-apis | ihtiyaç doğdukça | Kaynak listeleri; ücretsiz/yerel araç ararken |
| donnemartin/system-design-primer | Adım 13 (ölçekleme, çoklu cihaz) | Mimari referans |
| sdmg15/Best-websites-a-programmer-should-visit, microsoft/Web-Dev-For-Beginners | Adım 8/11 arayüz işleri | Öğrenme kaynakları |
