# kayaAI — Kurulum, güncelleme, yedekleme ve sorun giderme

Bu belge kayaAI'yi GitHub'dan **sıfırdan** kurmayı, güncel tutmayı, verini yedeklemeyi ve kaldırmayı anlatır.
Hepsi tek bir Windows bilgisayarda çalışır. İnternet yalnız ilk kurulumda (paketler ve modeller) ve isteğe bağlı
Claude modu için gerekir; sonrası tamamen yerel.

## 1. Gereksinimler

| Ne | Neden | Not |
|---|---|---|
| Windows 10/11 (64 bit) | çalışma ortamı | Görev Zamanlayıcı, OCR ve Edge Windows'un kendi parçaları |
| NVIDIA ekran kartı + güncel sürücü | yerel modeller GPU'da | RTX 50 serisi için CUDA 12.8+ destekli sürücü. GPU'suz da çalışır ama yavaş |
| Python 3.11 veya 3.12 | kayaAI | python.org — kurarken **"Add python.exe to PATH"** işaretli |
| Git | kodu indirmek/güncellemek | git-scm.com |
| Node.js LTS (isteğe bağlı) | arayüzü derlemek | yoksa arayüz derlenmez, CLI/API çalışır |
| Ollama | yerel modelleri çalıştırır | setup.ps1 sorarak kurar (winget) |
| Microsoft Edge | tarayıcı otomasyonu | Windows'ta kurulu gelir |
| Disk | | tüm modellerle ~25 GB (aşağıda) |

Modeller ve yaklaşık boyutları (hepsi isteğe bağlı sorulur, yalnız `qwen3:8b` temel):

| Model | Boyut | Ne için |
|---|---|---|
| qwen3:8b | 5,2 GB | genel sohbet, planlama, çeviri, belge/veri ajanları |
| qwen2.5-coder:7b | 4,7 GB | kod ajanı |
| bge-m3 | 1,2 GB | hafıza ve belge araması |
| qwen2.5vl:7b | 6 GB | ekranı okuma |
| whisper large-v3-turbo | 1,6 GB | bas-konuş, canlı altyazı |
| NVIDIA cuBLAS + cuDNN (pip) | 1,3 GB | ses tanımanın GPU'da çalışması |

## 2. Sıfırdan kurulum

PowerShell aç (Başlat → "PowerShell"). **Yönetici yetkisi gerekmez.**

```powershell
cd $HOME\Documents
git clone https://github.com/mertkaya01/KayaAI.git
cd KayaAI
powershell -ExecutionPolicy Bypass -File scripts\windows\setup.ps1
```

`main` dalı Windows'ta doğrulanmış son sürümdür. `setup.ps1` her adımı doğrular ve **indirme/kurulum öncesi sorar**:
Python sanal ortamı (`.venv`) ve paketler → birim testleri → arayüz derlemesi (Node varsa) → Ollama → modeller (her biri
ayrı sorulur) → ses modeli ve GPU kütüphaneleri → `kayaai doctor`. Testlerden biri düşerse kurulum durur ve hatayı gösterir.
`-ExecutionPolicy Bypass` yalnız o komut için geçerlidir; sistem ayarını değiştirmez.

Modelleri sonra indirmek istersen: `.\scripts\windows\setup.ps1 -SkipModel` (modelsiz kurar), sonra
`ollama pull qwen3:8b`, `kayaai speech download` ya da arayüzde **Modeller → Yeni model indir**.

### İlk çalıştırma

```powershell
.venv\Scripts\activate
kayaai api        # yerel API + arayüz (yalnız bu bilgisayardan: 127.0.0.1:8765) — pencere açık kalsın
kayaai ui         # tarayıcıda arayüzü erişim anahtarıyla açar (ikinci pencerede)
```

Durum kontrolü: `kayaai doctor` (Ollama, modeller, OCR, ses, tarayıcı).

### Doğrulama betikleri (isteğe bağlı, gerçek modellerle)

| Komut | Ölçer |
|---|---|
| `powershell -ExecutionPolicy Bypass -File scripts\windows\smoke.ps1` | temel kabul testleri, hız |
| `python scripts\agents_check.py` | ajan ekibi, gözden geçirme |
| `python scripts\memory_check.py` | hafıza ve belge araması |
| `python scripts\business_check.py` | Excel analizi, fatura, PDF özeti, raporlar |
| `python scripts\perception_check.py --screen --browser` | ekran okuma, ses, altyazı, tarayıcı |
| `python scripts\schedule_check.py` | Görev Zamanlayıcı'nın kayaAI'yi kendiliğinden çalıştırması |
| `kayaai bench` | sohbet/embedding/görsel/Whisper hızları, VRAM tepe |

Hepsi ayrı bir klasörde (`data\checks\…`) çalışır; gerçek geçmişin ve dosyaların değişmez. Sonuçlar `data\*.json`.

### Claude modu (isteğe bağlı)

Claude Pro + Claude Code kullanıyorsan: `powershell -ExecutionPolicy Bypass -File scripts\windows\mcp_setup.ps1`, sonra
`kayaai claude on` ve `kayaai claude sync`. Claude kapalıyken her şey yerelde çalışmaya devam eder.

## 3. Güncelleme

```powershell
cd $HOME\Documents\KayaAI
git pull
powershell -ExecutionPolicy Bypass -File scripts\windows\setup.ps1
```

`setup.ps1` yeni paketleri kurar, testleri çalıştırır, eksik modelleri sorar; mevcut verine (`data\`) dokunmaz.
Zamanlanmış görevler aynı klasörü gösterdiği için yeniden kayıt gerekmez. Klasörü taşıdıysan `kayaai schedule sync`
eksikleri gösterir (bkz. §5).

## 4. Yedekleme ve geri yükleme

**Neyin nerede olduğu:**

| Yer | İçerik | Özel mi? |
|---|---|---|
| `data\kayaai.db` | görev geçmişi, sohbetler, onaylar, anlaşmazlıklar, hafıza, belge dizini, zamanlanmış görevler | **evet** |
| `data\attachments\` | sohbet ekleri (ekran görüntüleri dahil) | **evet** |
| `data\api_token` | arayüz/API erişim anahtarı | **gizli** |
| `data\agents\`, `data\agent_overrides.yaml`, `data\models.local.yaml` | sonradan oluşturulan ajanlar, model atamaları, eklenen modeller | |
| `data\browser_profile\` | tarayıcı ajanının ayrı Edge profili (gezdiği sitelerin çerezleri) | **evet** |
| `data\models\whisper\` | ses modeli (yeniden indirilebilir) | |
| `data\model_compare\`, `data\checks\`, `data\*.json` | ölçüm sonuçları | |
| `config\settings.local.yaml` | senin ayar değişikliklerin (varsa) | |
| `~\kayaAI-files\` | ajanların dosya klasörü: raporlar, altyazı dökümleri | senin dosyaların |

**Yedek almak** (kayaAI kapalıyken — `kayaai api` penceresini kapat):

```powershell
Compress-Archive -Path data, config\*.local.yaml -DestinationPath "$HOME\kayaAI-yedek-$(Get-Date -Format yyyyMMdd).zip"
```

Ses modelini yedeğe katmak istemezsen önce `data\models` klasörünü dışarıda bırak (yeniden indirilebilir).
Yedek dosyası özel bilgi içerir: güvenli bir yerde tut, paylaşma. `~\kayaAI-files` ayrıca yedeklenir.

**Geri yüklemek / başka bilgisayara taşımak:** yeni kurulumu yap (§2), kayaAI'yi kapat, yedekteki `data\` klasörünü
proje klasörüne çıkar. Sonra:

```powershell
kayaai doctor
kayaai schedule sync     # zamanlanmış görevler Windows'ta yoksa listeler
```

Eksik görevler için Zamanlama sekmesinde görevi silip yeniden ekle (Windows kaydı yeni klasörün Python'unu göstermeli).
Claude modu kullanıyorsan `scripts\windows\mcp_setup.ps1` ve `kayaai claude sync`.

## 5. Kaldırma

1. Zamanlanmış görevleri sil: Zamanlama sekmesinde her görev için **Sil** (ya da `kayaai schedule rm <id>`).
   Görevleri kayaAI'den önce sildiysen Windows'ta kalanları temizlemek için:
   `schtasks /Query /FO LIST | findstr kayaAI` ile bak, `schtasks /Delete /TN "\kayaAI\<id>" /F` ile sil.
2. Modelleri istersen kaldır: `ollama rm qwen3:8b` (diğerleri için de). Ollama'yı Windows "Uygulamalar"dan kaldırabilirsin.
3. Proje klasörünü sil (içindeki `data\` ile birlikte — **önce yedek al**). `~\kayaAI-files` ayrıca silinir.

kayaAI sistemde başka iz bırakmaz: hizmet kurmaz, kayıt defterine yazmaz, yönetici yetkisi kullanmaz.

## 6. Sorun giderme

| Belirti | Çözüm |
|---|---|
| `kayaai doctor`: Ollama erişilemiyor | Ollama'yı başlat (Başlat → Ollama); `ollama list` çalışmalı |
| Modeller yavaş, Görev Yöneticisi'nde GPU boş | NVIDIA sürücüsünü güncelle (RTX 50: CUDA 12.8+); `ollama ps` "100% GPU" göstermeli |
| VRAM dolu uyarısı | kayaAI boştaki modelleri kendisi boşaltır; yine de yetmezse GPU kullanan oyun/programları kapat. `kayaai bench` VRAM tepe kullanımını gösterir |
| Ses tanıma işlemcide (`kayaai speech status` → cpu) | setup.ps1'de "GPU kütüphaneleri" sorusuna evet de; nedeni `/api/speech/status` → `gpu_error` |
| `kayaai speech download` indiremiyor | internet/huggingface.co erişimi; tekrar dene |
| OCR "dil yok" | Ayarlar → Saat ve dil → Dil ve bölge → Türkçe → Dil seçenekleri → "Optik karakter tanıma" |
| 🔊 Oku devre dışı (Türkçe) | Ayarlar → Saat ve dil → Konuşma → Ses ekle → Türkçe |
| Altyazıda ses gelmiyor | paylaşım penceresinde bir ekran/sekme seç ve **"Sistem sesini paylaş"** kutusunu işaretle |
| Küçük altyazı penceresi açılmıyor | Edge/Chrome 116+ gerekli |
| Tarayıcı ajanı Edge'i açamıyor | Edge kurulu mu; başka bir kayaAI tarayıcı işi açık mı (aynı anda tek iş) |
| Zamanlanmış görev çalışmadı | Zamanlama sekmesinde "son çalışma" ve hata; Windows'un başlattığı her çalışmanın çıktısı `data\schedule\<id>.log`; Görev Zamanlayıcı → `kayaAI` klasörü → görev → Geçmiş ("Son Sonuç" 0 = başarılı). Görev yalnız oturum açıkken çalışır; Ollama kapalıysa "başarısız" kaydedilir ve sonraki zamanında yeniden dener |
| Kurulumda test düştü | çıktıyı geliştirme oturumuna yapıştır; kurulum o adımda güvenle durur |
| Arayüz "anahtar geçersiz" | `kayaai ui` ile aç (anahtarı kendisi verir) ya da `kayaai api token` |

Kayıtlar: `logs\kayaai.log`. Olaylar: Kontrol Merkezi → Olay akışı.

## 7. Güvenlik özeti ve çok cihaz

- API ve arayüz yalnız **bu bilgisayardan** erişilir (`127.0.0.1`); ağa açmak sahibin kararıdır ve şu an desteklenmez.
- Riskli her işlem onay merkezinden geçer (dosya üzerine yazma, ajan modeli değiştirme, model indirme, tarayıcıda form/
  gönderme, zamanlanmış görev ekleme/silme). Ayrıntı: [`SECURITY.md`](../SECURITY.md).
- Ekran görüntüleri, ses ve özel hafıza Claude'a gönderilmez.
- Birden çok cihaz: şimdilik tek PC. Başka bir bilgisayara geçmek için §4'teki taşıma yeterli; aynı anda iki
  bilgisayarda aynı `data\` klasörünü (ör. bulut eşitleme) kullanma — SQLite veritabanı bozulabilir.
