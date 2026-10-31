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

## Henüz uygulanmayanlar (ilgili fazda)

Kimlik doğrulama (Faz 4), dosya yükleme doğrulaması (Faz 4/9), hız sınırlama (Faz 4), sandbox'lı kod
çalıştırma (Faz 3/7), eylem önizleme (Faz 7), hafıza hassasiyet kontrolleri (Faz 8).

## Güvenlik sorunu bildirimi

Depo sahibine doğrudan bildirin; herkese açık issue açmayın.
