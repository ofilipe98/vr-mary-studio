from __future__ import annotations

import os
import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Iterable, TypedDict

from .models import Classification


ADM_MODULE = "ADM_FIN_ESTOQUE"
MODULES = ("Fiscal", ADM_MODULE, "PDV")


class _GroupedProduct(TypedDict):
    product: str
    team: str
    modules: set[str]
    aliases: set[str]

CATEGORY_MODULE_SEGMENTS = {
    "fiscal": "Fiscal",
    "nota fiscal": "Fiscal",
    "contabilidade": "Fiscal",
    "ativo imobilizado": "Fiscal",
    "pdv": "PDV",
    "adm": ADM_MODULE,
    "administrativo": ADM_MODULE,
    "financeiro": ADM_MODULE,
    "estoque": ADM_MODULE,
    "crm": ADM_MODULE,
    "sistema": ADM_MODULE,
    "utilitario": ADM_MODULE,
    "adm fin estoque": ADM_MODULE,
    "adm_fin_estoque": ADM_MODULE,
    "adm financeiro estoque": ADM_MODULE,
}


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
        "ativo imobilizado": 2.0,
        "livro fiscal": 1.8,
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
        "selfcheckout": 2.0,
        "microterminal": 1.8,
        "autorizador": 1.5,
    },
    ADM_MODULE: {
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
        "ecommerce": 1.5,
        "monitoramento": 1.4,
        "etiqueta": 1.2,
        "cotacao": 1.5,
        "recebimento": 1.5,
        "balanca": 1.2,
        "coletor": 1.5,
        "central de compra": 1.7,
    },
}


# Nomes de funções exibidos nos menus do VRMaster. Esta camada complementa as
# palavras-chave gerais acima e usa correspondência por palavras inteiras para
# que siglas curtas, como DIME e GIA, não casem dentro de outras palavras.
MENU_KEYWORDS: dict[str, dict[str, float]] = {
    "Fiscal": {
        "contabilidade": 3.2,
        "encerramento contabil": 3.6,
        "fato contabil": 3.6,
        "lacs": 3.6,
        "lalur": 3.6,
        "plano conta referencial": 3.6,
        "ativo imobilizado": 3.6,
        "credito tributos": 3.2,
        "depreciacao": 3.2,
        "analise bonificacao": 3.2,
        "carta correcao": 3.6,
        "divergencia entrada": 3.2,
        "nota entrada": 3.6,
        "entrada conferencia": 3.2,
        "entrada produto": 3.2,
        "nota saida": 3.6,
        "servico saida": 3.2,
        "apuracao": 3.2,
        "arquivos magneticos": 3.2,
        "escrituracao": 3.6,
        "mapa resumo": 3.2,
        "mudanca tributacao": 3.6,
        "retencao tributo": 3.6,
        "efd reinf": 3.6,
        "dief": 3.6,
        "dime": 3.6,
        "dma": 3.6,
        "gia": 3.6,
        "nota fiscal paulista": 3.6,
        "sef": 3.2,
        "sintegra": 3.6,
        "sped contribuicoes": 3.6,
        "sped fiscal": 3.6,
        "fcp": 3.2,
        "credito outorgado": 3.6,
        "daicms antecipado": 3.6,
        "drcst": 3.6,
        "estorno icms": 3.6,
        "icms fronteira": 3.6,
        "operacao pag eletronico": 3.2,
        "outros valores icms": 3.6,
        "relatorio icms": 3.2,
        "credito presumido": 3.6,
        "simples nacional": 3.6,
        "substituicao estadual": 3.6,
        "uso e consumo": 3.2,
    },
    ADM_MODULE: {
        "centro custo": 3.6,
        "centro de custo": 3.6,
        "controle bancario": 3.6,
        "conciliacao bancaria": 3.6,
        "custodia cheque": 3.6,
        "fluxo de caixa": 4.0,
        "calendario financeiro": 3.6,
        "analise performance financeira": 3.6,
        "configuracao recebivel": 3.2,
        "credito rotativo": 3.6,
        "emissao boleto": 3.6,
        "outras receitas": 3.2,
        "venda prazo": 3.2,
        "venda a prazo": 3.2,
        "dda": 3.2,
        "relacao doc": 3.2,
        "doacao entidade": 3.2,
        "analise fornecedor": 3.2,
        "despesas e ajustes": 3.2,
        "acompanhamento estoque": 3.6,
        "cesta basica": 3.2,
        "comparativo lojas": 3.2,
        "estoque loja": 3.6,
        "estoque terceiro": 3.6,
        "estoque transito": 3.6,
        "extrato movimentacao": 3.2,
        "gerenciamento estoque": 3.6,
        "tabela estoque": 3.6,
        "transferencia interna": 3.2,
        "transferencia lojas": 3.2,
        "analise cliente": 3.2,
        "analise pesquisa": 3.2,
        "analise regiao": 3.2,
        "analise rfm": 3.6,
        "clientes sem compra": 3.6,
        "frequencia compra": 3.2,
        "mala direta": 3.2,
        "resumo promocao": 3.2,
        "venda cupom medio": 3.6,
        "parametro banco api": 3.2,
        "inf resp tecnico": 3.2,
        "licenca mobile": 3.2,
        "servicos web sefaz": 3.6,
        "atualizar tabelas": 3.2,
        "atualizacao pendencia": 3.2,
        "estoque online": 3.6,
        "log transacao custo": 3.6,
        "log transacao pedido": 3.6,
        "log workflow": 3.6,
        "peps": 3.6,
        "reposicao inteligente": 3.6,
    },
}


@dataclass(frozen=True)
class ProductRule:
    product: str
    team: str
    modules: tuple[str, ...]
    aliases: tuple[str, ...]

    @property
    def key(self) -> str:
        return product_key(self.product)


def normalize_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value or "")
    ascii_text = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", ascii_text.lower()).strip()


def product_phrase(value: str) -> str:
    value = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", value or "")
    value = re.sub(r"(?<=[A-Z])(?=[A-Z][a-z])", " ", value)
    normalized = normalize_text(value)
    normalized = re.sub(r"[^a-z0-9]+", " ", normalized)
    normalized = re.sub(
        r"\b(antigo|nova|novo|descontinuada|descontinuado)\b",
        " ",
        normalized,
    )
    return re.sub(r"\s+", " ", normalized).strip()


def product_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", product_phrase(value))


@lru_cache(maxsize=1)
def _menu_module_segments() -> dict[str, str]:
    candidates: dict[str, set[str]] = defaultdict(set)
    for module, keywords in MENU_KEYWORDS.items():
        for keyword in keywords:
            candidates[product_phrase(keyword)].add(module)
    return {
        segment: next(iter(modules))
        for segment, modules in candidates.items()
        if segment and len(modules) == 1
    }


def _explicit_segment_module(value: str) -> str | None:
    direct = CATEGORY_MODULE_SEGMENTS.get(normalize_text(value))
    if direct:
        return direct
    return _menu_module_segments().get(product_phrase(value))


def parse_product_catalog(markdown: str) -> tuple[ProductRule, ...]:
    heading = ""
    grouped: dict[str, _GroupedProduct] = {}
    for raw_line in (markdown or "").splitlines():
        line = raw_line.strip()
        if line.startswith("## "):
            heading = line[3:].strip()
            continue
        if not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if len(cells) < 2:
            continue
        product, team = cells[0], cells[1]
        if (
            not product
            or normalize_text(product) == "produto"
            or set(product) <= {"-", ":", " "}
        ):
            continue
        modules = _modules_for_team(f"{heading} {team}")
        key = product_key(product)
        if not key:
            continue
        entry = grouped.setdefault(
            key,
            {"product": product, "team": team, "modules": set(), "aliases": set()},
        )
        entry["modules"].update(modules)
        entry["aliases"].update(_aliases_for_product(product))

    rules = [
        ProductRule(
            product=str(entry["product"]),
            team=str(entry["team"]),
            modules=tuple(module for module in MODULES if module in entry["modules"]),
            aliases=tuple(
                sorted(
                    entry["aliases"],
                    key=lambda alias: (-len(product_key(alias)), alias),
                )
            ),
        )
        for entry in grouped.values()
    ]
    return tuple(sorted(rules, key=lambda rule: (-len(rule.key), rule.product)))


def _modules_for_team(value: str) -> tuple[str, ...]:
    normalized = normalize_text(value)
    has_fiscal = "fiscal" in normalized
    has_pdv = bool(re.search(r"\bpdv\b", normalized))
    has_adm = "adm" in normalized or "administrativo" in normalized
    if has_fiscal and has_adm:
        return ("Fiscal", ADM_MODULE)
    if has_pdv and has_adm:
        return (ADM_MODULE, "PDV")
    if has_fiscal:
        return ("Fiscal",)
    if has_pdv:
        return ("PDV",)
    return (ADM_MODULE,)


def _aliases_for_product(product: str) -> set[str]:
    phrase = product_phrase(product)
    aliases = {phrase}
    if phrase.startswith("vr "):
        without_prefix = phrase[3:]
        compact = product_key(without_prefix)
        generic = {
            "adm",
            "caixa",
            "connect",
            "financeiro",
            "integracao",
            "marketing",
            "master",
            "mobile",
            "monitor",
            "pdv",
            "portal",
            "recebimento",
            "set",
            "totem",
        }
        if len(compact) >= 8 and compact not in generic:
            aliases.add(without_prefix)
    return {alias for alias in aliases if alias}


def _catalog_candidates() -> Iterable[Path]:
    explicit = (
        os.environ.get("VR_PRODUCTS_FILE")
        or os.environ.get("MARY_PRODUCTS_FILE", "")
    ).strip()
    if explicit:
        yield Path(explicit)
    vr_root = (
        os.environ.get("VR_ROOT") or os.environ.get("MARY_ROOT", "")
    ).strip()
    if vr_root:
        yield Path(vr_root) / "agentes" / "produtos_filas.md"
    yield Path(__file__).resolve().parent / "data" / "produtos_filas.md"


@lru_cache(maxsize=12)
def _parse_catalog_file(path: str, mtime_ns: int) -> tuple[ProductRule, ...]:
    del mtime_ns
    return parse_product_catalog(Path(path).read_text(encoding="utf-8"))


def load_product_catalog() -> tuple[ProductRule, ...]:
    merged: dict[str, ProductRule] = {}
    for candidate in _catalog_candidates():
        try:
            resolved = candidate.resolve()
            if not resolved.is_file():
                continue
            rules = _parse_catalog_file(
                str(resolved),
                resolved.stat().st_mtime_ns,
            )
        except (OSError, UnicodeError):
            continue
        for rule in rules:
            merged.setdefault(rule.key, rule)
    return tuple(sorted(merged.values(), key=lambda rule: (-len(rule.key), rule.product)))


def classify(
    title: str,
    text: str,
    category: str = "",
    product: str = "",
    catalog: tuple[ProductRule, ...] | None = None,
) -> Classification:
    catalog = load_product_catalog() if catalog is None else catalog
    category_result = _classify_explicit_category(category)
    if category_result is not None:
        return category_result

    scores: dict[str, float] = defaultdict(float)
    reasons: dict[str, list[str]] = defaultdict(list)

    _score_product_field(
        product,
        "produto informado",
        9.0,
        4.5,
        catalog,
        scores,
        reasons,
        exact=True,
    )
    _score_product_field(
        title,
        "título",
        7.0,
        3.6,
        catalog,
        scores,
        reasons,
    )
    _score_product_field(
        category,
        "categoria",
        5.5,
        3.0,
        catalog,
        scores,
        reasons,
    )

    keyword_fields = [
        ("título", title, 1.45),
        ("categoria", category, 1.30),
        ("produto", product, 1.50),
        ("texto", text, 1.0),
    ]
    for field_name, value, field_weight in keyword_fields:
        haystack = (
            normalize_text(value)
            if field_name == "texto"
            else _keyword_haystack(value, catalog)
        )
        if not haystack:
            continue
        for module, keywords in KEYWORDS.items():
            for keyword, weight in keywords.items():
                token = normalize_text(keyword)
                occurrences = min(haystack.count(token), 3)
                if not occurrences:
                    continue
                contribution = (
                    weight
                    * field_weight
                    * (1.0 + 0.20 * (occurrences - 1))
                )
                scores[module] += contribution
                _append_reason(reasons[module], f"{keyword} ({field_name})")

        menu_haystack = product_phrase(value)
        for module, keywords in MENU_KEYWORDS.items():
            for keyword, weight in keywords.items():
                occurrences = _whole_phrase_occurrences(menu_haystack, keyword)
                if not occurrences:
                    continue
                contribution = (
                    weight
                    * field_weight
                    * (1.0 + 0.20 * (occurrences - 1))
                )
                scores[module] += contribution
                _append_reason(reasons[module], f"menu {keyword} ({field_name})")

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
        module
        for module, score in ranked
        if score >= leader_score * 0.72 and score >= 2.0
    ]
    if len(close_modules) > 1:
        combined_reasons = [
            f"{module}: {', '.join(reasons[module][:5])}"
            for module in close_modules
        ]
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
        return Classification(
            "Revisar",
            confidence,
            "pending",
            reasons[leader][:7],
        )
    return Classification(leader, confidence, status, reasons[leader][:7])


def explicit_module_category(segments: Iterable[str]) -> str:
    """Retorna somente os segmentos que identificam um módulo sem ambiguidade."""

    matches: list[str] = []
    for value in segments:
        for raw_segment in re.split(r"[/|>]+", value or ""):
            segment = raw_segment.strip()
            if (
                segment
                and _explicit_segment_module(segment) is not None
                and segment not in matches
            ):
                matches.append(segment)
    return " / ".join(matches)


def _classify_explicit_category(category: str) -> Classification | None:
    if not (category or "").strip():
        return None

    explicit_modules: dict[str, list[str]] = defaultdict(list)
    for raw_segment in re.split(r"[/|>]+", category):
        segment = normalize_text(raw_segment)
        module = _explicit_segment_module(raw_segment)
        if module and segment not in explicit_modules[module]:
            explicit_modules[module].append(segment)

    if not explicit_modules:
        return Classification(
            "Revisar",
            0.35,
            "pending",
            ["categoria sem modulo explicito"],
        )

    if len(explicit_modules) > 1:
        evidence = ", ".join(
            f"{module}: {'/'.join(segments)}"
            for module, segments in explicit_modules.items()
        )
        return Classification(
            "Revisar",
            0.35,
            "pending",
            [f"categoria com modulos conflitantes: {evidence}"],
        )

    module, segments = next(iter(explicit_modules.items()))
    return Classification(
        module,
        0.98,
        "approved",
        [f"modulo explicito na categoria: {'/'.join(segments)} -> {module}"],
    )


def _score_product_field(
    value: str,
    field_name: str,
    single_module_score: float,
    hybrid_module_score: float,
    catalog: tuple[ProductRule, ...],
    scores: dict[str, float],
    reasons: dict[str, list[str]],
    exact: bool = False,
) -> None:
    matches = _match_products(value, catalog, exact=exact)
    for rule in matches:
        score = (
            single_module_score
            if len(rule.modules) == 1
            else hybrid_module_score
        )
        module_label = "/".join(rule.modules)
        reason = f"produto {rule.product} -> {module_label} ({field_name})"
        for module in rule.modules:
            scores[module] += score
            _append_reason(reasons[module], reason)


def _match_products(
    value: str,
    catalog: tuple[ProductRule, ...],
    exact: bool = False,
) -> list[ProductRule]:
    if not value or not catalog:
        return []
    value_phrase = product_phrase(value)
    value_key = product_key(value)
    padded_value = f" {value_phrase} "
    token_keys = {
        product_key(token)
        for token in re.findall(r"[A-Za-zÀ-ÿ0-9]+", value)
    }
    matches: list[tuple[int, ProductRule]] = []
    for rule in catalog:
        if exact and value_key == rule.key:
            return [rule]
        best = 0
        for alias in rule.aliases:
            alias_key = product_key(alias)
            if exact:
                matched = value_key == alias_key
            else:
                matched = f" {alias} " in padded_value
                if not matched and alias_key:
                    matched = alias_key in token_keys
            if matched:
                best = max(best, len(alias_key))
        if best:
            matches.append((best, rule))
    if not matches:
        return []
    longest = max(length for length, _rule in matches)
    return [
        rule
        for length, rule in matches
        if length == longest
    ]


def _keyword_haystack(
    value: str,
    catalog: tuple[ProductRule, ...],
) -> str:
    phrase = product_phrase(value)
    padded = f" {phrase} "
    for rule in _match_products(value, catalog):
        for alias in rule.aliases:
            padded = padded.replace(f" {alias} ", " ")
    return normalize_text(padded)


def _append_reason(target: list[str], reason: str) -> None:
    if reason not in target:
        target.append(reason)


def _whole_phrase_occurrences(haystack: str, keyword: str) -> int:
    phrase = product_phrase(keyword)
    if not haystack or not phrase:
        return 0
    return min(f" {haystack} ".count(f" {phrase} "), 3)
