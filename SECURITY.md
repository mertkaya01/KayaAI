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

## Adım 9'da uygulananlar (hafıza)

- [x] Tüm hafıza, belge parçaları ve vektörler yerelde (SQLite); vektörler yerel modelle (Ollama bge-m3)
- [x] **Gizli** öğeler: parola/anahtar/token/IBAN/kart/özel anahtar kalıpları kodla tespit edilir; açık izin olmadan
      saklanmaz; saklanırsa hiçbir bağlama otomatik girmez; API listesinde metin gönderilmez (tek tek "Göster",
      `memory.revealed` olayı); Claude gizli bilgi öneremez
- [x] **Özel** öğeler ve yerel belge parçaları Claude'a giden hiçbir bağlama girmez (devretme, `kayaai_memory_search`)
- [x] Claude/ajan önerileri `proposed` kalır, sahip onaylamadan kullanılmaz
- [x] Belge dizini yalnızca izinli kökler; yol doğrulaması; `.env`/anahtar dosyaları/ikili dosyalar ve gizli kalıp geçen
      parçalar dizine girmez; boyut ve dosya sayısı sınırı
- [x] Kurallar genişleyince (v0.14.2: Hugging Face/Stripe/GitLab/npm anahtarları, parolalı adresler, JWT) eski
      kayıtlar `kayaai memory scan --fix` ile yeniden taranır: öğe "gizli" yapılır, belge parçası dizinden çıkar
- [x] Hafıza ve belge içeriği modele güvenilmez VERİ olarak gider; kaynaklar uydurulmaz talimatı
- [x] Sahip her şeyi görebilir, düzenleyebilir, silebilir, dışa aktarabilir

## Adım 10'da uygulananlar (iş modülleri)

- [x] Dosya içeriği hiçbir zaman çalıştırılmaz: Excel formülleri hesaplanmaz (kayıtlı değerler), makrolar yok sayılır;
      analiz yalnızca sabit işlem kümesiyle (süz/grupla/topla…) programla yapılır
- [x] Model sayı üretmez: analiz sayıları kodla hesaplanır; yorumdaki sayılar ve fatura tutarları kodla denetlenir
- [x] Ekler: yalnızca PDF/.xlsx/.xlsm/CSV (ikili ekler base64, ≤10 MB); parola korumalı ve metinsiz PDF anlaşılır hatayla reddedilir
- [x] Raporlar yalnızca izinli kayaAI klasörüne; yeni dosya R1 (kayda geçer), üzerine yazma R2 (sahip onayı + yedek)
- [x] API/MCP iş araçları yalnızca izinli klasörlerdeki dosyalarla çalışır; MCP araç açıklamaları içeriğin Claude'a
      gideceğini belirtir (özel hafıza kuralları değişmez)
- [x] Yeni bağımlılıklar izin verici lisanslı: pypdf (BSD-3), openpyxl (MIT), python-docx (MIT), reportlab (BSD);
      PDF yazı tipi sistemden okunur (repoya font eklenmez)

## Adım 11'de uygulananlar (akış + model yönetimi)

- [x] Ajan modelini değiştirmek, model indirmek ve aday modeli aktif yapmak **R2 sahip onayı** ister (API/CLI talep
      eder, yalnızca sahip onaylar; MCP'de model yönetimi aracı yok). Yükle/boşalt yalnız VRAM'i etkiler: R1, kayda geçer
- [x] Model adı doğrulaması (`ad[:etiket]`, küçük harf, güvenli karakterler, uzunluk sınırı); yalnızca Ollama'nın kendi
      `/api/pull` ucu kullanılır (kabuk komutu çalıştırılmaz)
- [x] Aday modeller ajanlara atanamaz; aktif yapmak için o modelin karşılaştırma sonucu gerekir (doğrulayıcı kapısı)
- [x] Repo dosyaları değişmez: değişiklikler git dışı `data/models.local.yaml` ve `data/agent_overrides.yaml`'a yazılır
      (atomik yazma); geçersiz/aktif olmayan geçersiz kılma uyarıyla yok sayılır
- [x] Karşılaştırma ayrı geçici veritabanında çalışır (gerçek geçmiş kirlenmez), aynı anda yalnızca bir tane; sonuç
      kimliği yalnız harf/rakam (yol gezinmesi yok)
- [x] Akış grafiği yalnızca okuma; tüm yeni uçlar erişim anahtarı ister

## Adım 12a'da uygulananlar (ekranı okuma)

- [x] Ekran yalnızca sahibin açık eylemiyle yakalanır: tarayıcının `getDisplayMedia` seçim penceresi ve paylaşım
      göstergesi; **tek kare** alınır, akış hemen kapatılır (sürekli kayıt yok). CLI `kayaai screen` yalnız komutla tek kare
- [x] Ekran görüntüleri ve OCR metinleri Claude'a gitmez: vision ajanının Claude karşılığı yok, MCP aracı yok,
      Claude'a devirde görüntü ekleri ve metinleri çıkarılır (uyarı gösterilir)
- [x] Görüntüler doğrulanır (Pillow ile açılır; ≤10 MB, ≤40 MP); görev kaydına bayt değil dosya yolu yazılır; modele
      giden geçici kopyalar iş bitince silinir
- [x] Görsel modelin yazdığı sayılar OCR metnine karşı kodla denetlenir; OCR yoksa cevap "doğrulanmadı" olarak işaretlenir
- [x] Yeni bağımlılıklar izin verici lisanslı: Pillow (MIT-CMU), pypdfium2 (Apache-2.0/BSD), mss (MIT), pywinrt (MIT);
      görsel model qwen2.5vl:7b (Apache-2.0)

## Adım 12b'de uygulananlar (bas-konuş, sesli okuma)

- [x] Mikrofon yalnız sahip düğmeye bastığında açılır, kayıt bitince akış kapatılır; sayaç + tarayıcı göstergesi; 2 dk üst sınır
- [x] Ses diske yazılmaz ve saklanmaz (bellekte çözülür); olay kaydına tanınan metin değil yalnız süre/aygıt yazılır
- [x] Ses tanıma tamamen yerel (faster-whisper); model indirme sahip onayı ister (R2) ya da setup.ps1'de sahibe sorulur
- [x] Sesli okuma yalnız yerel Windows sesleriyle (`localService`); çevrim içi (bulut) sesler kullanılmaz
- [x] Bağımlılıklar: faster-whisper, ctranslate2 (MIT), PyAV (BSD-3; <19 — 19 faster-whisper'ı bozuyor);
      isteğe bağlı NVIDIA cuBLAS/cuDNN (NVIDIA lisansı, yalnız yerel çalıştırma için, yeniden dağıtılmaz)

## Adım 12c'de uygulananlar (canlı altyazı)

- [x] Sistem sesi / mikrofon yalnız "Başlat" ile, tarayıcının izin/paylaşım penceresiyle açılır; sürekli görünür
      "Dinleniyor" göstergesi; Durdur, paylaşımı durdurma ve 2 saat sınırı (sunucu da uygular) ile kapanır
- [x] Ses saklanmaz; altyazı metni olay kaydına yazılmaz; döküm yalnız sahip "Kaydet" derse izinli klasöre (yeni dosya R1)
- [x] WebSocket erişim anahtarıyla; ilk mesaj doğrulanır (dil/hedef beyaz liste); model yoksa anlaşılır hata ile kapanır
- [x] AudioWorklet aynı kökenden (`/pcm-worklet.js`), CSP değişmedi

## Adım 12d'de uygulananlar (tarayıcı otomasyonu)

- [x] Ayrı ve boş tarayıcı profili (`data/browser_profile`): sahibin çerezleri, oturumları, şifreleri kullanılmaz;
      görünür pencere; arka plan eşitleme/güncelleme bağlantıları kapalı bayraklarla başlatılır
- [x] Risk sınıfını KOD belirler (model değil): okuma R0, aynı sitede tıklama R1, form girişi / yeni site R2, gönderme /
      ödeme / satın alma / silme / yayınlama / kayıt R3 (her seferinde onay; toplu onay yok)
- [x] Reddedilenler: parola/kart/kimlik/IBAN/OTP alanına yazma, dosya yükleme ve indirme (indirme kapalı), `file://`,
      `javascript:`, yerel ağ ve bu bilgisayarın adresleri (ağ katmanında da engellenir)
- [x] Önizleme: hedef öğe kırmızı çerçeveli ekran görüntüsü + açıklama + ajanın gerekçesi; reddedilirse iş durur;
      onay 10 dk içinde verilmezse reddedilir; Durdur her an
- [x] R3 eylemi yalnızca hedef açıkça istiyorsa önerilebilir; hedefte olumsuzluk ("satın alma", "gönderme", "don't")
      varsa ya da hedef böyle bir eylem istemiyorsa kod sormadan reddeder (Windows gözlemi: model "Satın alma." hedefinde
      "Satın Al"a tıklamayı önermişti)
- [x] Döngü korumaları: en fazla 20 adım, aynı eylem tekrarı ve üst üste kural dışı adımlarda durur
- [x] Playwright (Apache-2.0); tarayıcı indirmez, kurulu Edge'i kullanır

## Adım 13a'da uygulananlar (zamanlanmış görevler)

- [x] Görev ekleme/silme Windows'un görev kayıtlarını değiştirdiği için R2 sahip onayı (önizleme: sıklık, ilk çalışma,
      tam komut); aç/kapat ve şimdi çalıştır R1 (kayda geçer); onaysız hiçbir `schtasks` çağrısı yapılmaz (test)
- [x] Görevler sahibin hesabıyla, yalnız oturum açıkken (InteractiveToken), EN DÜŞÜK yetkiyle; parola saklanmaz;
      ek paket yok (Windows'un `schtasks.exe` aracı); 2 saat süre sınırı, aynı görevin ikinci örneği başlamaz
- [x] Zamanlanmış görevler her zaman yerelde: serbest görev Claude açık olsa da şefe `force=local` ile gider; belge özeti
      gizli dosya kurallarına uyar (`.env`, anahtar, parola dosyaları okunmaz), içerik bilgisayardan çıkmaz
- [x] Satış raporu ve klasör yalnız izinli klasörlerden; raporlar yeni dosya (R1)

## Adım 14'te uygulananlar (referans incelemesinden)

- [x] **Kill switch**: otomasyonu duraklat — zamanlanmış görevler (Windows'un başlattığı süreç de görür) atlanır, tarayıcı
      işi başlamaz, süren durur; elle yapılanlar etkilenmez
- [x] **Yazma yasak listesi**: gizli bilgi / çalıştırılabilir dosya adları ve hassas klasörler izinli klasörde bile
      reddedilir; talepte ve onaydan sonra yürütmede (önceden oluşmuş onay da yazamaz)
- [x] **Dış veri**: varsayılan kapalı; açmak R2 (önizlemede site ve gönderilen veri), yalnız iki ana makine (kodla),
      yönlendirme izlenmez, her çağrı olay kaydına; kişisel veri/sohbet/dosya gönderilmez; sonuçlar önbellekte
- [x] **Prompt injection**: tarayıcı ajanı ve belge özeti güvenilmez metni "veri" olarak alır; riskli eylemleri kod
      sınıflandırır ve istenmeyen geri alınamaz eylemi reddeder (Adım 12d/v0.12.4)

## Henüz uygulanmayanlar (ilgili fazda)

Güncelleme (2026-11-01): dosya yükleme doğrulaması (tür izin listesi, base64 ve boyut kontrolü, Adım 9/12) ve hafıza
hassasiyet kontrolleri (public/personal/private/secret, gizli bilgi algılama, Adım 8) uygulandı.

- **Model ürettiği kodu çalıştırma:** bilinçli olarak YOK (ilke: açık onay olmadan çalıştırılmaz); sandbox ancak sahip
  böyle bir özellik isterse tasarlanır.
- **Hız sınırlama:** yok. API yalnız 127.0.0.1'de ve oturum anahtarıyla; ağa açılırsa (sahip kararı) zorunlu olur.
- **Masaüstü (tarayıcı dışı) eylemler:** yok; yalnız tarayıcı ajanı (Adım 12d) önizlemeli/onaylı eylem yapar.

## Güvenlik sorunu bildirimi

Depo sahibine doğrudan bildirin; herkese açık issue açmayın.
