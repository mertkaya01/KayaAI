"""Kapsam kontrolü: cevap isteğin ana konularına değiniyor mu (Opus'un gerçek gözlemi, 2026-10-31)."""

from __future__ import annotations

import pytest

from kayaai.conductor import Conductor
from kayaai.conductor.coverage import missing_topics, topic_covered
from kayaai.workers.planner import RoutePlan, validate_plan

from .conductor_helpers import Script, answer, plan_direct, plan_steps, review
from .test_conductor import rt  # noqa: F401  (fixture)

SAAS_TOPICS = ["çok kiracılı / multi-tenant", "mikroservis mimarisi / microservice architecture",
               "veri izolasyonu / data isolation", "ölçekleme ödünleşimleri / scaling trade-offs"]
# Yerel ekibin gerçek cevabına benzer: genel mikroservis bilgisi, çok kiracılılık yok
GENERIC = ("Mikroservis mimarisi, uygulamaları küçük, bağımsız ve ölçeklenebilir bileşenlere bölerek geliştirme ve "
           "bakım süreçlerini kolaylaştırır. Her mikroservis kendi veri modelini ve veritabanını yönetir; bu yaklaşım "
           "veri izolasyonu sağlar. Ölçeklenebilirlik için her servis ayrı ölçeklenir; ödünleşim olarak iletişim artar.")
TENANT = " Çok kiracılı yapıda her kiracı için ayrı şema ya da paylaşılan tablo + tenant_id kullanılır."


def test_real_case_generic_answer_misses_multi_tenancy():
    assert missing_topics(SAAS_TOPICS, GENERIC) == ["çok kiracılı / multi-tenant"]
    assert missing_topics(SAAS_TOPICS, GENERIC + TENANT) == []


@pytest.mark.parametrize("topic,text,ok", [
    ("multi-tenant / çok kiracılı", "We use a tenant_id column in every multi tenant table", True),
    ("veri izolasyonu", "Kiracı verilerinin izolasyonu için ayrı şemalar ve veritabanı rolleri", True),
    ("ölçekleme", "Servisler yatay olarak ölçeklenebilir", True),
    ("faturalama / billing", "Kimlik doğrulama JWT ile yapılır", False),
    ("API", "herhangi bir metin", True),  # içerik kelimesi yok → değerlendirilemez
])
def test_topic_covered_turkish_suffixes_and_alternatives(topic, text, ok):
    assert topic_covered(topic, text) is ok


def test_short_answers_are_not_checked():
    assert missing_topics(["başkent"], "Ankara.") == []


def test_planner_topic_validation():
    too_many = RoutePlan(mode="direct", agent="general", key_topics=[f"k{i}" for i in range(7)])
    assert any("en fazla 6" in e for e in validate_plan(too_many, {"general"}))
    blank = RoutePlan(mode="direct", agent="general", key_topics=["  "])
    assert any("boş konu" in e for e in validate_plan(blank, {"general"}))


def test_uncovered_topic_triggers_addendum_even_if_reviewer_says_ok(rt, fake_ollama):  # noqa: F811
    s = Script(
        planner=[plan_steps([("s1", "general", "Mimariyi anlat", []), ("s2", "general", "Ölçeklemeyi anlat", ["s1"])],
                            topics=SAAS_TOPICS)],
        answers=[answer(GENERIC), answer("Ölçekleme ödünleşimleri: maliyet ve karmaşıklık artar."),
                 answer("Çok kiracılı (multi-tenant) yapıda her kiracı için ayrı şema kullanılır.")],
        reviews=[review("ok"), review("ok")],
    )
    fake_ollama.chat_replies = [s] * 50
    res = Conductor(rt).run("Çok kiracılı bir SaaS için mikroservis mimarisini anlat")
    assert res.status == "succeeded" and res.review.revised
    assert "kiracı" in res.answer and "### Ek" in res.answer
    assert "ele alınmamış konu: çok kiracılı" in s.user_messages["GeneralAnswer"][2]
    assert res.review.uncovered_topics == []
    assert not any("değinmiyor" in w for w in res.warnings)


def test_still_uncovered_after_revision_warns_once(rt, fake_ollama):  # noqa: F811
    s = Script(
        planner=[plan_steps([("s1", "general", "Mimariyi anlat", []), ("s2", "general", "Ölçeklemeyi anlat", [])],
                            topics=SAAS_TOPICS)],
        answers=[answer(GENERIC), answer("Ek bilgi yok."), answer("Yine genel bir ek açıklama.")],
        reviews=[review("ok"), review("ok")],
    )
    fake_ollama.chat_replies = [s] * 50
    res = Conductor(rt).run("Çok kiracılı bir SaaS için mikroservis mimarisini anlat")
    assert res.review.uncovered_topics == ["çok kiracılı / multi-tenant"]
    warns = [w for w in res.warnings if "çok kiracılı" in w]
    assert len(warns) == 1 and "kodla kontrol" in warns[0]


def test_direct_mode_warns_without_review(rt, fake_ollama):  # noqa: F811
    s = Script(planner=[plan_direct("general", topics=SAAS_TOPICS[:1])], answers=[answer(GENERIC)])
    fake_ollama.chat_replies = [s] * 10
    res = Conductor(rt).run("Çok kiracılı SaaS nedir, kısaca anlat")
    assert not res.review.performed and res.review.uncovered_topics == ["çok kiracılı / multi-tenant"]
    assert s.calls["ReviewResult"] == 0


def test_translation_requests_skip_coverage(rt, fake_ollama):  # noqa: F811
    s = Script(planner=[plan_direct("general", topics=["toplantı / meeting"])],
               answers=[answer("I will be late for the meeting tomorrow morning because of heavy traffic on the road "
                               "and I am very sorry about it, please start without me and I will join as soon as possible.",
                               language="en", task_type="translation")])
    fake_ollama.chat_replies = [s] * 10
    res = Conductor(rt).run("Şu cümleyi İngilizceye çevir: 'Yarın sabah toplantıya geç kalacağım.'")
    assert res.review.uncovered_topics == []


def test_code_only_answer_covers_topic_in_code():
    """Gerçek yanlış alarm (Windows conductor_check): cevap yalnızca kod bloğu, konu fonksiyon adında."""
    code = ("```javascript\nfunction debounce(func, wait) {\n  let timeout;\n  return function(...args) {\n"
            "    clearTimeout(timeout);\n    timeout = setTimeout(() => func.apply(this, args), wait);\n  };\n}\n"
            "const handleResize = debounce(() => console.log('Window resized'), 300);\n```")
    assert missing_topics(["debounce / debounce"], code) == []
    assert missing_topics(["throttle"], code) == ["throttle"]


def test_snake_case_identifiers_split():
    assert topic_covered("aylık satış / monthly sales", "def monthly_sales_total(rows): ...")
