import pytest

from kayaai.core.lang import detect_language, expected_answer_language

# Metinlerin çoğu kullanıcının gerçek smoke_report.json çıktısından.
CASES = [
    ("Give three short tips for writing readable Python code.", "en"),
    ("Summarize in one sentence: Local LLMs run on the user's own hardware, keeping data private.", "en"),
    ("1. İsimlerin anlamlı ve okunaklı olmasına dikkat et. 2. Gövdeyi girintili şekilde yaz.", "tr"),
    ("I will be late for the meeting tomorrow morning.", "en"),
    ("Python'da liste ile demet (tuple) arasındaki farkı iki cümleyle açıkla.", "tr"),
    ("Yerel LLM'ler, kullanıcıların kendi donanımlarında çalışır ve verilerin gizliliğini sağlar.", "tr"),
    ("What is 17 * 23? Reply with only the number.", "en"),
    ("İSTANBUL ÇOK GÜZEL", "tr"),
    ("Hello, who are you?", "en"),
    # belirsiz: kısa / tek kelime / sayı -> kontrol yapılmaz
    ("Ankara", "other"),
    ("Merhaba", "other"),
    ("391", "other"),
    ("", "other"),
    ("a", "other"),          # tek kısa kelime: karar verilmez (gerçek test hatası)
    ("the plan", "other"),
    ("Hello, who are you?", "en"),
]


@pytest.mark.parametrize("text,lang", CASES)
def test_detect_language(text, lang):
    assert detect_language(text) == lang


def test_code_blocks_ignored():
    text = "Listeyi şöyle sıralarsın:\n```python\nfor x in sorted(items):\n    print(x)\n```\nBu kadar."
    assert detect_language(text) == "tr"


def test_expected_language_skips_translation_and_target_language():
    assert expected_answer_language("Şu cümleyi İngilizceye çevir: Yarın geç kalacağım") == "other"
    assert expected_answer_language("Translate to Turkish: good morning") == "other"
    assert expected_answer_language("Bana Python hakkında bilgi ver, ama cevap English olsun") == "other"
    assert expected_answer_language("Give three tips for clean code") == "en"
    assert expected_answer_language("Bana temiz kod için üç ipucu ver") == "tr"
