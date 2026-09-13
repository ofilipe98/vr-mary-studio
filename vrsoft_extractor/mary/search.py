from __future__ import annotations

import math
import re
import unicodedata
from typing import Iterable


# Keep this list in sync with data/vr-search.ps1. Search behavior is part of
# the portable project contract and must not depend on the selected provider.
SEARCH_STOPWORDS = frozenset(
    {
        "a",
        "ao",
        "aos",
        "as",
        "com",
        "como",
        "da",
        "das",
        "de",
        "do",
        "dos",
        "e",
        "em",
        "eu",
        "mas",
        "mary",
        "na",
        "nas",
        "no",
        "nos",
        "o",
        "os",
        "para",
        "por",
        "qual",
        "que",
        "um",
        "uma",
    }
)

MODULE_HINTS: dict[str, frozenset[str]] = {
    "PDV": frozenset(
        {
            "autorizador",
            "caixa",
            "cmos",
            "concentrador",
            "cupom",
            "ecf",
            "funcao",
            "operador",
            "pdv",
            "pinpad",
            "sitef",
            "tef",
            "venda",
            "vrcaixa",
            "vrpdv",
        }
    ),
    "Fiscal": frozenset(
        {
            "cfop",
            "fiscal",
            "icms",
            "nf",
            "nfe",
            "nfce",
            "nota",
            "sped",
            "tributacao",
            "xml",
        }
    ),
    "ADM_FIN_ESTOQUE": frozenset(
        {
            "cadastro",
            "contas",
            "estoque",
            "financeiro",
            "fornecedor",
            "produto",
            "vradm",
            "vrmaster",
        }
    ),
}

_VR_PREFIX = re.compile(r"^\s*(?:vr|mary)\s*:\s*", flags=re.IGNORECASE)


def strip_optional_vr_prefix(value: str) -> str:
    """Strip the current VR prefix and the legacy Mary prefix."""
    return _VR_PREFIX.sub("", str(value or ""), count=1).strip()


def normalize_search_text(value: str) -> str:
    decomposed = unicodedata.normalize("NFD", str(value or "").casefold())
    without_marks = "".join(
        character
        for character in decomposed
        if unicodedata.category(character) != "Mn"
    )
    return " ".join(re.findall(r"[\w-]+", without_marks, flags=re.UNICODE))


def search_terms(value: str, *, limit: int = 12) -> list[str]:
    normalized = normalize_search_text(strip_optional_vr_prefix(value))
    terms = [
        word
        for word in normalized.split()
        if len(word) >= 2 and word not in SEARCH_STOPWORDS
    ]
    return list(dict.fromkeys(terms))[:limit]


def matched_search_terms(terms: Iterable[str], *values: str) -> list[str]:
    haystack = normalize_search_text(" ".join(str(value or "") for value in values))
    return [term for term in terms if term in haystack]


def term_coverage(terms: Iterable[str], matched: Iterable[str]) -> float:
    unique_terms = tuple(dict.fromkeys(terms))
    if not unique_terms:
        return 0.0
    matched_set = set(matched)
    return len([term for term in unique_terms if term in matched_set]) / len(unique_terms)


def minimum_term_matches(term_count: int) -> int:
    return max(1, math.ceil(max(0, term_count) * 0.60))


def infer_search_module(terms: Iterable[str]) -> str:
    scores = module_search_scores(terms)
    best_module, best_score = max(scores.items(), key=lambda item: item[1])
    if best_score <= 0:
        return ""
    tied = [module for module, score in scores.items() if score == best_score]
    return best_module if len(tied) == 1 else ""


def module_search_scores(terms: Iterable[str]) -> dict[str, int]:
    term_set = set(terms)
    return {
        module: len(term_set.intersection(hints))
        for module, hints in MODULE_HINTS.items()
    }


def infer_search_modules(terms: Iterable[str]) -> tuple[str, ...]:
    scores = module_search_scores(terms)
    best_score = max(scores.values(), default=0)
    if best_score <= 0:
        return ()
    # A module with meaningful evidence (>= half of the strongest score)
    # participates: explicit multi-module questions must not collapse to a
    # single winner just because one side scored higher.
    threshold = max(1, -(-best_score // 2))
    ranked = sorted(
        scores.items(),
        key=lambda item: (-item[1], list(MODULE_HINTS).index(item[0])),
    )
    return tuple(
        module for module, score in ranked if score >= threshold
    )


def search_excerpt(markdown: str, terms: Iterable[str], *, limit: int = 360) -> str:
    text = re.sub(r"\A---\s*.*?\s*---\s*", "", str(markdown or ""), flags=re.DOTALL)
    text = re.sub(r"!\[[^]]*]\([^)]*\)", " ", text)
    text = re.sub(r"\[([^]]+)]\([^)]*\)", r"\1", text)
    text = re.sub(r"[`#>*_|]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return ""
    normalized = normalize_search_text(text)
    positions = [normalized.find(term) for term in terms]
    positions = [position for position in positions if position >= 0]
    # The normalized and original offsets can differ around accents. The
    # approximate offset is sufficient for a readable evidence window.
    center = min(positions) if positions else 0
    start = max(0, center - 90)
    excerpt = text[start : start + limit].strip()
    if start:
        excerpt = "… " + excerpt
    if start + limit < len(text):
        excerpt += " …"
    return excerpt


def results_are_ambiguous(results: list[dict]) -> bool:
    if len(results) < 2:
        return False
    first = float(results[0].get("score") or 0.0)
    second = float(results[1].get("score") or 0.0)
    if first <= 0:
        return True
    return (first - second) / first < 0.10
