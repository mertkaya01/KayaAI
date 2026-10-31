"""İsteğin karmaşıklığı için kodla hesaplanan sinyaller (Claude önerisi).

Neden: 8B planlayıcı kendi sınırını bilemiyor; gerçek ölçümde ağır bir mimari isteğine bile
"Claude gerekmez" dedi (2026-10-31, conductor_check). Bu sinyaller planlayıcının görüşüne EKLENİR;
sonuç ve sebepler kayda geçer. Claude kapalıyken tek etkisi bir kalite uyarısıdır (D16).
"""

from __future__ import annotations

import re

from ..workers.planner import RoutePlan

# Ağır analiz/tasarım işlerini işaret eden ifadeler (TR + EN). Kök eşleşmesi: "mimari", "mimarisini" ...
_KEYWORDS = [
    ("mimari", r"mimari"), ("architecture", r"architect"),
    ("tasarla", r"tasarla|tasarım"), ("design", r"\bdesign"),
    ("ödünleşim", r"ödünleşim|trade-?offs?"),
    ("ölçekleme", r"ölçekle|ölçeklen|scalab|\bscaling\b"),
    ("dağıtık", r"dağıtık|distributed"),
    ("güvenlik denetimi", r"güvenlik denetimi|security (audit|review)|tehdit modeli|threat model"),
    ("ayrıntılı", r"ayrıntılı|detaylı|kapsamlı|in-depth|comprehensive"),
    ("çok dosyalı", r"birden (çok|fazla) dosya|multi-?file|whole (codebase|project)|tüm proje"),
]
LONG_REQUEST_CHARS = 250
MANY_STEPS = 3


def complexity_signals(request: str, plan: RoutePlan | None = None) -> tuple[int, list[str]]:
    text = request.lower()
    reasons: list[str] = []
    score = 0
    if plan is not None and plan.mode == "plan" and len(plan.steps) >= MANY_STEPS:
        score += 1
        reasons.append(f"{len(plan.steps)} adımlı plan")
    hits = [label for label, pattern in _KEYWORDS if re.search(pattern, text)]
    if hits:
        score += min(len(hits), 2)
        reasons.append("ifadeler: " + ", ".join(f"'{h}'" for h in hits[:4]))
    if len(request) > LONG_REQUEST_CHARS:
        score += 1
        reasons.append(f"uzun istek ({len(request)} karakter)")
    return score, reasons
