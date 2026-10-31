# Güvenlik ve Gizlilik

## İlkeler

1. **Yalnızca yerel varsayılan.** Ollama `127.0.0.1:11434` üzerinden kullanılır. Yerel olmayan bir adres
   yapılandırılırsa kayaAI uyarı verir. `OLLAMA_HOST=0.0.0.0` **kullanmayın**; denetim ve kurulum
   scriptleri bunu tespit edip uyarır.
2. **Ağa açık API yok.** Faz 1'de hiçbir ağ sunucusu açılmaz. Faz 4'teki API yalnızca `127.0.0.1`'e
   bağlanacak ve token ile kimlik doğrulama gerektirecek. Bilgisayar kontrolü yapan, kimlik doğrulamasız
   bir API asla internete açılmaz.
3. **İzin tabanlı yürütme.** Her görev ihtiyaç duyduğu izinleri bildirir. `config/settings.yaml` →
   `permissions.auto_approve` dışındaki izinler (`fs.write`, `net`, `exec`, `screen`, `audio`,
   `desktop.control`) **kullanıcı onayı** olmadan çalışmaz; onaylayıcı yoksa görev reddedilir.
4. **Onay gerektiren işlemler (Faz 7+):** dosya silme, önemli dosyanın üzerine yazma, mesaj/e-posta gönderme,
   yayınlama, satın alma, güvenlik ayarı değiştirme, yükseltilmiş yetkiyle komut, özel bilgi paylaşma.
   Bunlar için önce **eylem önizlemesi** gösterilecek.
5. **Dış veri güvenilmezdir.** Belgeler, web sayfaları, indirilen dosyalar ve diğer worker'ların
   çıktıları talimat değil veridir. Faz 1'de görev girdisi `<girdi_verisi>` etiketleriyle ayrılır ve
   modele içindeki talimatları uygulamaması söylenir. Bu tek başına yeterli bir savunma **değildir**;
   bu yüzden yüksek etkili işlemler her zaman insan onayına bağlıdır.
6. **Ekran ve ses yakalama (Faz 5–6):** yalnızca açık kullanıcı eylemiyle başlar, görünür gösterge
   vardır, anında durdurulabilir, varsayılan olarak yerel işlenir ve hiçbir yere otomatik yüklenmez.
7. **Hassas veri.** Hafıza (Faz 8) açık izin olmadan hassas bilgi saklamaz; kullanıcı düzenleyip silebilir.
8. **Sırlar.** API anahtarı vb. asla koda veya `config/*.yaml`'a yazılmaz; `config/settings.local.yaml`
   ve `.env` git'e girmez.
9. **Güvenilmeyen kod.** Host üzerinde doğrudan çalıştırılmaz (Faz 3+ kod çalıştırma: izole alt süreç,
   zaman aşımı, onay).

## Faz 1'de uygulananlar

- [x] Localhost-only Ollama varsayılanı + yerel olmayan adres uyarısı
- [x] İzin modeli + onaylayıcı + onaysız reddetme (testli)
- [x] Süreç zaman aşımları (görev ve HTTP)
- [x] Girdi verisinin talimattan ayrılması
- [x] Görev olay günlüğü (SQLite `task_events`) ve dönen dosya logları
- [x] Kurulum scriptleri: yönetici yetkisi istemez, kurulum/indirme öncesi sorar, sistem ayarı değiştirmez

## Faz 2'de uygulananlar (MCP)

- [x] MCP sunucusu yalnızca stdio: ağ portu açmaz, uzaktan erişilemez
- [x] Sadece `llm.inference` araçları; dosya/komut/ağ aracı yok; onaylayıcı olmadığından hassas izinler reddedilir
- [x] MCP istemcisinden gelen `context`/`input` modele `<input_data>` içinde veri olarak verilir
- [x] Girdi boyutu ve zaman aşımı sınırları
- [x] Başarısız/doğrulanmamış görevler hata olarak döner
- [x] `.mcp.json` makineye özgüdür ve git'e girmez; üzerine yazmadan önce sorulur, yedek alınır

**Not:** Claude Code, MCP araç sonuçlarını kendi bağlamına alır. Yerel modelin cevabı da güvenilmez
çıktıdır; Claude Code tarafında yüksek etkili işlemler yine kullanıcı onayına tabidir.

## Adım 3'te uygulananlar

- [x] Claude modu varsayılan kapalı; kayaAI Claude'a iş gönderemez (API yok), Claude Code kutuyu kendisi okur
- [x] Claude çalışma alanı repo dışında; üretici kullanıcı dosyalarının üzerine yazmaz (işaret kontrolü)
- [x] Claude'un `kayaai_claude_complete` cevabı boyut sınırlı (20.000 karakter) ve yalnızca bekleyen işe yazılır
- [x] Şef adımları arasında aktarılan sonuçlar `<input_data>` içinde güvenilmez veri olarak verilir
- [x] Model tarafından üretilen kod varsayılan olarak çalıştırılmaz (`coder_bench --execute` onay ister)

## Adım 4'te uygulananlar (yerel API)

- [x] Yalnızca 127.0.0.1; başka adres CLI'da reddedilir (ağa açmak ayrı bir sahip kararı)
- [x] Her HTTP isteği ve WebSocket bağlantısı erişim anahtarı ister (sabit zamanlı karşılaştırma)
- [x] CORS yalnızca localhost kökenleri; girdi boyutu sınırları (20.000 karakter)
- [x] Anahtar `data/api_token` (git'e girmez); not: düz dosya — çoklu cihaz aşamasında yeniden ele alınacak

## Adım 5'te uygulananlar (izin motoru + dosya araçları)

- [x] Risk sınıfları R0–R3; R2/R3 sahip onayı olmadan çalışmaz; R3 tek tek onaylanır (toplu onay yok)
- [x] Onay kuyruğu kalıcı; süresi dolan talep `expired` olur ve onaylanamaz
- [x] Onayı yalnızca sahip verir (CLI, anahtarlı API); MCP'de onay aracı yok — ajan kendi isteğini onaylayamaz
- [x] Dosya araçları yalnızca izinli klasörlerde; `..`/mutlak yol/sembolik bağlantı kaçışı yol çözümlendikten sonra reddedilir
- [x] Salt-okunur klasöre yazma onay istemeden reddedilir; üzerine yazmadan önce otomatik yedek; silme aracı yok
- [x] Her araç kullanımı ve onay kararı olay akışında (`tool.used`, `approval.*`)

## Adım 6'da uygulananlar (Control Center)

- [x] Arayüz yalnızca API ile aynı yerel kökenden sunulur (127.0.0.1); veriye her erişim yine anahtarlı `/api/*`
- [x] Anahtar adresin `#token=` parçasında verilir (sunucuya/kayıtlara gitmez), `sessionStorage`'a alınır ve adres
      çubuğundan/geçmişten silinir; sekme kapanınca unutulur; "Çıkış" siler
- [x] İçerik güvenlik politikası (CSP): `default-src 'self'`, dış betik/stil yok, `unsafe-inline`/`unsafe-eval` yok,
      `frame-ancestors 'none'` (+ `X-Frame-Options: DENY`), `connect-src` yalnızca kendi kökeni ve yerel WS;
      `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`. (`/docs` Swagger CDN kullandığından CSP dışında.)
- [x] Statik dosya sunumu `ui/dist` dışına çıkamaz (yol çözümlendikten sonra denetlenir)
- [x] Onay kararları arayüzden de yalnızca anahtarlı istekle; kararlar `decided_by=api` ile kaydedilir

## Adım 7'de uygulananlar (ajan sistemi)

- [x] Model tarafından üretilen kod **çalıştırılmaz**; yalnızca ayrıştırılır (Python `ast`, JSON, YAML)
- [x] Ajanlar birbirine körü körüne güvenmez: her sorun cevaptan alıntıyla kanıtlanmalı, kanıtsızlar kodla elenir;
      kontrol hatası (kanıt) üretici tarafından itiraz edilemez
- [x] Anlaşmazlık kararı yalnızca sahipte (CLI, anahtarlı API) ya da kutudaki işi tamamlayan Claude'da; MCP'de karar aracı yok
- [x] Geçici ajan izin tavanı kodla: dayandığı ajanın izinleri ∩ yaratıcının izinleri; geçici ajana dayanan geçici ajan yok;
      sayı sınırı (`max_temp_agents`); kalıcı yapmak için başarılı kullanım + sahip onayı (R2, YAML önizlemeli)
- [x] İç yardımcı worker'lar (`*.revise`, `*.check`) MCP'den çağrılamaz; bozuk/çakışan `data/agents` dosyaları atlanır,
      repo ajanlarını ezemez

## Adım 8'de uygulananlar (asistan)

- [x] Sohbet geçmişi, ekler ve bağlam yalnızca yerelde (SQLite + `data/attachments`, git'e girmez)
- [x] Ekler: yalnızca metin türleri, ≤ `files.max_read_mb`, ikili (NUL baytlı) içerik reddedilir, dosya adı temizlenir
      (yol parçaları atılır); klasörden ekleme mevcut kök kontrolünden geçer (izinli klasör dışı 403)
- [x] Ekler ve geçmiş modele `<input_data>` içinde güvenilmez VERİ olarak gider; boyut sınırlı
- [x] Claude'a devretme yalnızca sahibin açık eylemiyle (onay penceresi: neyin gideceği yazılı) ve Claude kutusu üzerinden;
      kayaAI Claude'u kendisi çağırmaz; Claude kapalıyken API 409
- [x] Model çıktısı HTML olarak işlenmez (Markdown → React öğeleri, `dangerouslySetInnerHTML` yok); bağlantılar tıklanamaz
- [x] Sohbet silme kalıcıdır ve onay ister; iç ajanlar (planner/reviewer) sohbetten doğrudan seçilemez

## Henüz uygulanmayanlar (ilgili fazda)

Dosya yükleme doğrulaması (Faz 9), hız sınırlama, sandbox'lı kod çalıştırma (Faz 7), masaüstü/tarayıcı eylem
önizlemesi (Faz 12), hafıza hassasiyet kontrolleri (Faz 9).

## Güvenlik sorunu bildirimi

Depo sahibine doğrudan bildirin; herkese açık issue açmayın.
