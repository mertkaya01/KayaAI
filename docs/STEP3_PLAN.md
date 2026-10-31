# Adım 3 — İki Mod + Şef (ayrıntılı plan)

> Durum: **onaylandı (2026-10-31).** İlerleme: TASKS.md "Adım 3".
> Dayanak: MASTER_PROMPT v2 — D2 (Claude isteğe bağlı), D14 (tek kaynak kayaAI), D15 (her modda önce yerel),
> D16 (Claude kapalıyken uyarıyla yerelde yap), §4–§6.

## 1. Hedef

Adım sonunda:
1. **Claude kapalıyken** kayaAI çok adımlı bir isteği kendi başına **planlar, ajanlara dağıtır, sonuçları
   birleştirir, kontrol eder** ve gerekiyorsa "Claude ile daha iyi olurdu" uyarısı verir.
2. **Claude açıkken** Opus, ayrı bir çalışma klasöründe Claude Code ile açılır; kayaAI'nin ürettiği
   kuralları (`CLAUDE.md`) ve alt ajanları okur, işleri önce yerel ajanlara verir, sadece gerektiğinde
   kendisi yapar. kayaAI'nin "Claude kutusundaki" işleri alıp sonuçlarını geri yazar.
3. Claude'u **kapatmak hiçbir şey kaybettirmez**: kutudaki işler uyarıyla yerelde yapılır.
4. Bugün görülen "her mesajı yerel modele yollama" davranışı kurallarla düzelir.

## 2. Mevcut koddan yeniden kullanılacaklar

| Parça | Dosya | Nasıl kullanılacak |
|---|---|---|
| Görev nesnesi (`parent_id`, `depends_on`) | `kayaai/core/task.py` | Şefin bir "iş"i = üst görev; adımlar = alt görevler |
| Bağımlılıklı paralel çalıştırma | `Orchestrator.run_all` (v0.2.1'de düzeltildi) | Planın adımlarını sırayla/paralel yürütür |
| Şemalı çıktı + doğrulama + geri bildirimle tekrar | `kayaai/workers/base.py` `LLMWorker` | Planlayıcı, birleştirici ve gözden geçirici de bunu kullanır |
| İzin/onay | `Orchestrator` + `Permission` | Planın adımları izin kurallarından geçer |
| Dil tespiti | `kayaai/core/lang.py` | Birleştirilmiş cevabın dili kontrol edilir |
| Model kayıt defteri | `config/models.yaml` | Ajanların yerel modelleri buradan |
| MCP sunucusu | `kayaai/mcp_server.py` | Yeni araçlar eklenir |
| `.mcp.json` üretimi | `scripts/windows/mcp_setup.ps1` | Mantığı Python'a taşınır (test edilebilir) |

Yeniden yazılan bir şey yok; hepsi genişletme.

## 3. Alt adımlar (her biri ayrı commit + test)

### 3a. Modlar ve durum
- `config/settings.yaml` → `claude: { enabled: false }` (varsayılan **kapalı**).
- Aç/kapa durumu SQLite'ta saklanır (arayüzden değiştirilebilsin diye YAML'a yazılmaz); yeniden başlatmada korunur.
- Durum: `kapalı` / `açık — son temas yok` / `açık — son temas N dk önce`. "Son temas" = Claude Code'un
  MCP sunucusunu en son kullandığı an (canlı bağlantıyı kesin tespit etmek mümkün değil; dürüst etiket bu).
- Yeni görev durumu: `waiting_claude` (bitmemiş sayılır, yeniden başlatmada korunur).
- CLI: `kayaai claude status | on | off`. `kayaai doctor` ve `kayaai_health` modu gösterir.

### 3b. Ajan tanımları (tek kaynak)
- `config/agents/<ad>.yaml`: ad, açıklama, rol talimatı, tercih edilen katman
  (`local` / `claude-haiku` / `claude-sonnet` / `claude-opus`), yerel yedek model, izinler, sınırlar.
- Yükleyici bu tanımlardan yerel worker'ları oluşturur (kod yazmadan yeni ajan → MASTER_PROMPT D9 için zemin).
- İlk ajanlar:
  - `general` — mevcut genel worker (davranış değişmez)
  - `reviewer` — başka bir ajanın çıktısını isteğe göre kontrol eder: `ok / sorunlar / öneri`
  - `coder` — yerel modeli şimdilik `qwen3:8b`; `qwen2.5-coder:7b` bu adımda küçük bir kod
    benchmark'ından geçerse ona alınır (aday modeli benchmark'sız atamama kuralı korunur)
- CLI: `kayaai agents`.

### 3c. Yerel şef
`kayaai/conductor/` — akış:
1. **Yönlendirme kararı:** basit istek → tek ajana doğrudan (çoğu istek böyle; gereksiz parçalama yok).
   Karmaşık istek → plan.
2. **Plan** (şemalı JSON): en fazla 4 adım; her adım: ajan, amaç, bağımlılıklar. Ayrıca
   `needs_claude: evet/hayır + sebep`.
3. **Plan doğrulama (kodla):** ajanlar var mı, döngü yok mu, adım sınırı, izinler. Geçersiz plan →
   bir kez geri bildirimle yeniden plan → yine geçersizse tek ajana düş.
4. **Yürütme:** mevcut `run_all` ile; adım çıktıları sonraki adıma `<input_data>` olarak (güvenilmez veri).
5. **Birleştirme:** `general` ajanı adım sonuçlarından tek cevap yazar.
6. **Gözden geçirme:** `reviewer` cevabı isteğe göre kontrol eder; sorun varsa **bir** düzeltme turu
   (sınır ayarlanabilir), yine sorunluysa cevap uyarıyla döner.
7. **Claude kuralı:**
   - Claude **kapalı** + `needs_claude` → yerelde yapılır, cevaba **uyarı** eklenir (D16).
   - Claude **açık** + `needs_claude` → iş **Claude kutusuna** gider (D15: sadece gerçekten gerekirse).
     Kullanıcı isterse `--local` ile yine yerelde yaptırabilir.
   - Yerel sonuç iki kez doğrulamadan geçemezse ve Claude açıksa → kutuya; kapalıysa → uyarıyla hata.
   - Her karar **sebebiyle** kayda geçer (`routing.decision`).
- CLI: `kayaai do "istek"` (şef) — mevcut `kayaai ask` (tek ajan) kalır.
- MCP: `kayaai_do` — Claude da çok adımlı işi yerel ekibe devredebilsin.

### 3d. Claude kutusu (MCP)
- `kayaai_claude_inbox` — bekleyen işleri listeler (Claude modu kapalıysa bunu söyler).
- `kayaai_claude_complete(task_id, result, summary)` — Claude sonucunu geri yazar; görev geçmişinde
  `model: claude (Claude Code)` olarak görünür; boş/eksik sonuç reddedilir.
- `kayaai_claude_release(task_id)` — işi yerel ekibe geri verir.
- `claude off` → kutudaki işler uyarıyla yerelde yapılır (ya da `--keep` ile bekletilir).
- CLI: `kayaai inbox`.

### 3e. Claude çalışma alanı üreticisi
- **Önemli tasarım kararı:** şef olarak kullanılacak Claude Code oturumu **repo klasöründe değil, ayrı bir
  çalışma klasöründe** açılır (varsayılan `C:\Users\MERT\kayaAI-workspace`). Sebep: repo klasöründe
  açılan Claude Code aynı zamanda geliştirme oturumu (benim gibi); üretilen `CLAUDE.md` geliştirme
  oturumlarını da etkilerdi. Ayrı klasörle "geliştirme" ve "şef" karışmaz.
- `kayaai claude sync` bu klasöre üretir (hepsi "OTOMATİK ÜRETİLDİ — config/agents'ı düzenleyin" başlıklı):
  - `CLAUDE.md`: yönlendirme kuralları (önce yerel; ne zaman `kayaai_ask` / `kayaai_do`; kutu işleme;
    gizli veriyi onaysız işlememe; "bir kez araç dendi diye her mesajı araca yollama" kuralı)
  - `.claude/agents/<ad>.md`: Claude katmanlı ajanlar (model seçimiyle)
  - `.mcp.json`: kayaAI MCP sunucusu (mevcut `mcp_setup.ps1` mantığı Python'a taşınır)
- `kayaai claude on` = aç + sync. `mcp_setup.ps1` bu komutu çağıracak şekilde sadeleşir.
- **Doğrulanacak (resmi Claude Code dokümanından, üretici yazılmadan önce):** alt ajan dosya biçimi
  (frontmatter alanları, model seçimi), Pro planında alt ajanların hangi modelleri kullanabildiği.

## 4. Bu adıma bilerek alınmayanlar

| Konu | Neden sonra |
|---|---|
| Claude Code hook'ları → olay günlüğü | Olaylar Adım 4'teki olay yolu (event bus) ile birlikte anlamlı; şimdilik görev geçmişi yeterli |
| Arayüzdeki aç/kapa butonu | Arayüz Adım 6/8'de; buton o zaman bu adımdaki API'ye bağlanır |
| Kalıcı ajan ekleme onay akışı (D9) | Zemin bu adımda (tanım dosyaları); onay akışı Adım 5'teki izin motoruyla |
| Hafıza | Adım 9 |

## 5. Testler

**Burada (sahte Ollama ile):**
- Mod: aç/kapa, yeniden başlatmada korunma, durum etiketleri
- Ajan tanımları: geçerli/geçersiz YAML, bilinmeyen model, aday model ataması reddi
- Şef: basit istek tek ajana; 3 adımlı plan doğru sırada; geçersiz plan (bilinmeyen ajan, döngü,
  çok adım) → yeniden plan → tek ajana düşme; birleştirme; gözden geçirme sorun → 1 düzeltme turu
- Yönlendirme matrisi: {Claude kapalı/açık} × {needs_claude evet/hayır} × {doğrulama geçti/geçmedi}
- Kutu: kuyruğa alma, `complete` (boş sonuç reddi), `release`, kapatınca geri verme
- Üretici: dosyalar doğru klasöre, repo köküne yazılmıyor, başlık var, gizli bilgi yok, `.mcp.json` geçerli JSON
- MCP: yeni araçlar gerçek stdio alt süreciyle

**Senin PC'nde:**
- `scripts/conductor_check.py`: gerçek modelle 4–5 örnek istek → plan geçerlilik oranı, adım sayısı,
  toplam süre, gözden geçirme sonucu, uyarılar → `data\conductor_check.json`
- `qwen2.5-coder:7b` küçük kod benchmark'ı → `coder` ajanının modeli kararı
- Claude modu: `kayaai claude on` → çalışma klasöründe `claude` → "kutudaki işleri yap" →
  sonucun `kayaai tasks`'ta `claude` olarak görünmesi → `kayaai claude off` → kalan işlerin yerelde yapılması

## 6. Riskler

| Risk | Etki | Önlem |
|---|---|---|
| 8B model zayıf planlar yapar | Gereksiz/yanlış adımlar | En fazla 4 adım, kodla plan doğrulama, basit istekte plan yok, ölçüm (`conductor_check`) |
| `needs_claude` kararını 8B model verir, güvenilmez | Claude gereksiz/eksik kullanılır | Ek sinyaller: doğrulama başarısızlığı, kullanıcı bayrağı (`--claude` / `--local`); oran ölçülür |
| Gecikme: plan + adımlar + birleştirme + gözden geçirme | 3–8 sn | Basit istekte tek çağrı; gözden geçirme ayarlanabilir |
| Claude Code alt ajan biçimi / Pro model erişimi farklı çıkabilir | Üretici yanlış dosya yazar | Önce resmi dokümandan doğrulama; üretici şablonu tek yerde |
| Claude Code kutuyu kendiliğinden kontrol etmez | İşler bekler | `CLAUDE.md` kuralı + `kayaai inbox` uyarısı; kullanıcı "kutuyu işle" der |
| Geliştirme ve şef oturumlarının karışması | Yanlış talimat | Ayrı çalışma klasörü |
| Kapsam büyümesi | Adım uzar | 3a–3e ayrı commit; 3c sonunda ve 3e sonunda senin PC'nde ara doğrulama |

## 7. Teslimatlar

Kod: `kayaai/conductor/`, `kayaai/agents/`, `config/agents/*.yaml`, MCP araçları, CLI komutları,
`scripts/conductor_check.py`. Dokümanlar: ARCHITECTURE (şef + modlar), TASKS, CHANGELOG, SECURITY (kutu,
çalışma alanı), MODEL_REGISTRY (coder kararı). Sürüm: 0.3.0.

## 8. Varsayılanlar (değiştirmek istersen söyle)

- Claude modu varsayılan **kapalı**.
- Şef çalışma klasörü: `C:\Users\MERT\kayaAI-workspace`.
- Plan sınırı 4 adım, gözden geçirme 1 tur.
- Claude açık + `needs_claude` → kutuya (beklerken `--local` ile yerelde yaptırılabilir).
