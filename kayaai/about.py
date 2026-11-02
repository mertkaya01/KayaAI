"""kayaAI'nin kendini tanıması (sahip videosu, 2026-11-02): "neler yapabilirsiniz?" sorusunda yerel model kayaAI'yi
bilmediği için uyduruyordu. Bu soru gelince modele GERÇEK ekip ve özellik listesi veri olarak verilir; ekip kayıtlı
ajanlardan (config/agents + sonradan eklenenler) okunur."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .runtime import Runtime

ABOUT_RE = re.compile(
    r"neler(i)? yapabil|ne(ler)? yapabil|neler yapıyor|yetenek|kendini(zi)? tanıt|sen kimsin|siz kimsiniz|"
    r"\bkimsin\b|\bnesin\b|özellikler(in|iniz)|ne işe yar|hangi ajan|ekibin(de|iz)|ajanların kim|"
    r"what can you do|who are you|your (features|capabilities)|introduce yourself",
    re.IGNORECASE)

LABELS = {"general": "Genel", "data": "Veri", "document": "Belge", "coder": "Kod", "vision": "Görsel",
          "planner": "Şef (planlayıcı)", "reviewer": "Denetçi"}

FEATURES: list[tuple[str, str]] = [
    ("Sohbet", "Türkçe/İngilizce soru-cevap, özet, çeviri, e-posta ve metin taslağı. 'Otomatik' seçiliyse şef isteği "
               "uygun ajana verir, çok parçalı işi ajanlara böler, cevabı denetçiye kontrol ettirir."),
    ("Tablo analizi", "Excel/CSV ekle: toplam, ortalama, oran, karşılaştırma, eğilim. Sayıları program hesaplar; "
                      "rapor olarak Excel, PDF, Word ya da Markdown verir."),
    ("Belge ve fatura", "PDF ya da metin özeti; faturadan bilgileri çıkarır ve tutarları hesapla kontrol eder."),
    ("Hafıza ve belge araması", "'Bunu hatırla' dediklerini ve izin verdiğin klasörlerdeki belgeleri bulur; "
                                "kullandığı kaynağı gösterir."),
    ("Kod", "Python, JavaScript/TypeScript, SQL yazar ve açıklar; gerekirse kodu internetsiz, izole bir Docker kum "
            "havuzunda çalıştırıp sonucu kontrol eder (Kod ve Veri ajanı)."),
    ("Ekranı okuma", "Ekran görüntüsünü yerel görsel modelle ve yazı tanımayla (OCR) okur."),
    ("Ses", "Bas-konuş (yerel Whisper), cevabı sesli okuma, canlı çeviri altyazı."),
    ("Tarayıcı", "Ayrı bir Edge profilinde web işleri; gönderme/ödeme gibi riskli adımlar senin onayınla."),
    ("Zamanlanmış görevler", "Belge klasörü özeti, haftalık satış raporu, dizin yenileme ya da serbest bir görev; "
                             "kayaAI kapalıyken de çalışır."),
    ("Bilgisayar durumu", "İşlemci, bellek, ekran kartı ve disk kullanımını okuyup yorumlayabilir (yalnız okur, "
                          "ayar değiştirmez)."),
    ("Ofis ve onaylar", "Ajanların canlı çalışmasını Ofis'te izleme; onay merkezi; ajan anlaşmazlıklarında karar senin."),
    ("Claude modu (isteğe bağlı)", "Zor işler Claude Code oturumuna devredilebilir."),
]

LIMITS = [
    "Her şey bu bilgisayarda çalışır; internete kendiliğinden çıkmaz (döviz/tatil verisi yalnız sen açarsan).",
    "Dosya yazma, tarayıcıda işlem gibi bilgisayarı değiştiren işler önce onayını ister.",
    "Yerel modeller küçük (8B): çok uzun ve zor işlerde hata yapabilir; böyle işlerde Claude modu ya da daha büyük "
    "bir model daha iyi sonuç verir.",
]


def wants_about(text: str) -> bool:
    return bool(ABOUT_RE.search(text or ""))


def about_kayaai(rt: "Runtime") -> dict[str, Any]:
    team = []
    for w in rt.workers.all():
        name = getattr(w, "name", "")
        if not name or "." in name:  # reviewer.check gibi iç alt işçiler
            continue
        role = "iç ajan (şef ve denetim)" if name in ("planner", "reviewer") else "uzman"
        team.append({"agent": LABELS.get(name, name), "id": name, "kind": role, "does": getattr(w, "description", "")})
    return {
        "name": "kayaAI",
        "what": "Bu bilgisayarda çalışan, yerel yapay zekâ modelleriyle çalışan çok ajanlı kişisel asistan.",
        "team": team,
        "features": [{"name": n, "does": d} for n, d in FEATURES],
        "limits": LIMITS,
    }
