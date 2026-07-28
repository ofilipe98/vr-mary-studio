from __future__ import annotations

import re
import unicodedata
from collections import defaultdict

from .models import Classification


KEYWORDS: dict[str, dict[str, float]] = {
    "Fiscal": {
        "fiscal": 2.0,
        "tribut": 1.8,
        "sped": 2.0,
        "nf-e": 1.8,
        "nfe": 1.5,
        "icms": 2.0,
        "pis": 1.7,
        "cofins": 1.7,
        "contabil": 1.6,
        "efd": 1.8,
        "xml": 1.0,
        "nota fiscal": 1.5,
    },
    "PDV": {
        "pdv": 2.0,
        "caixa": 1.7,
        "checkout": 2.0,
        "venda": 1.2,
        "frente de loja": 2.0,
        "tef": 2.0,
        "sitef": 2.0,
        "clisitef": 2.0,
        "pinpad": 1.8,
        "sat": 1.4,
        "nfce": 1.6,
        "nfc-e": 1.6,
        "totem": 1.7,
        "self-checkout": 2.0,
    },
    "ADM_FIN_ESTOQUE": {
        "adm": 1.5,
        "administrativo": 1.6,
        "financeiro": 2.0,
        "estoque": 2.0,
        "produto": 1.1,
        "cadastro": 1.1,
        "pessoa": 1.0,
        "fornecedor": 1.4,
        "contas a pagar": 2.0,
        "contas a receber": 2.0,
        "wms": 2.0,
        "mobile": 1.3,
        "connect": 1.4,
        "e-commerce": 1.5,
        "monitoramento": 1.4,
        "etiqueta": 1.2,
    },
}


def normalize_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value or "")
    ascii_text = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", ascii_text.lower()).strip()


def classify(title: str, text: str, category: str = "", product: str = "") -> Classification:
    haystack = normalize_text(" ".join([title, title, category, category, product, text]))
    scores: dict[str, float] = defaultdict(float)
    reasons: dict[str, list[str]] = defaultdict(list)
    for module, keywords in KEYWORDS.items():
        for keyword, weight in keywords.items():
            token = normalize_text(keyword)
            occurrences = min(haystack.count(token), 3)
            if occurrences:
                contribution = weight * (1.0 + 0.25 * (occurrences - 1))
                scores[module] += contribution
                reasons[module].append(keyword)

    ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    if not ranked or ranked[0][1] < 1.5:
        return Classification("Revisar", 0.35, "pending", ["poucos indícios"])

    leader, leader_score = ranked[0]
    runner_score = ranked[1][1] if len(ranked) > 1 else 0.0
    total = sum(scores.values())
    dominance = leader_score / max(total, leader_score)
    margin = (leader_score - runner_score) / max(leader_score, 1.0)
    confidence = min(0.98, 0.52 + dominance * 0.27 + margin * 0.25)

    close_modules = [
        module for module, score in ranked if score >= leader_score * 0.72 and score >= 2.0
    ]
    if len(close_modules) > 1:
        combined_reasons = [f"{module}: {', '.join(reasons[module][:4])}" for module in close_modules]
        return Classification(
            "Multimodulo",
            max(0.68, min(0.92, confidence)),
            "approved" if confidence >= 0.85 else "pending",
            combined_reasons,
        )

    if confidence >= 0.85:
        status = "approved"
    elif confidence >= 0.60:
        status = "pending"
    else:
        return Classification("Revisar", confidence, "pending", reasons[leader][:6])
    return Classification(leader, confidence, status, reasons[leader][:6])
