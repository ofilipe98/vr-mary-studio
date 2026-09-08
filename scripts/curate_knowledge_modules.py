from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from vrsoft_extractor.mary.classifier import classify, load_product_catalog
from vrsoft_extractor.mary.db import MaryDatabase
from vrsoft_extractor.mary.indexer import export_catalog
from vrsoft_extractor.mary.paths import resolve_portable_path


CONCRETE_MODULES = {"Fiscal", "ADM_FIN_ESTOQUE", "PDV"}
MANUAL_CORRECTIONS = {
    ("wiki", "35"): (
        "Multimodulo",
        "índice geral do VRMaster com links para ADM, Fiscal e PDV",
    ),
    ("wiki", "137"): (
        "Multimodulo",
        "notas de versão do produto híbrido VRCaixa",
    ),
    ("wiki", "181"): (
        "Multimodulo",
        "notas de versão do produto híbrido VRCaixa",
    ),
    ("wiki", "370"): (
        "Fiscal",
        "nota fiscal com validação de inscrição estadual no Sintegra",
    ),
    ("wiki", "4488"): (
        "ADM_FIN_ESTOQUE",
        "importação e conciliação de custódia bancária",
    ),
    ("wiki", "5184"): (
        "Multimodulo",
        "centro de custo usado em Financeiro, Fiscal e despesas",
    ),
    ("wiki", "7080"): (
        "Multimodulo",
        "DRO combina resultados Financeiros com apuração Fiscal",
    ),
    ("wiki", "8734"): (
        "Multimodulo",
        "DRO combina resultados Financeiros com apuração Fiscal",
    ),
    ("wiki", "9057"): (
        "Multimodulo",
        "DRO combina resultados Financeiros com apuração Fiscal",
    ),
    ("wiki", "1431"): (
        "Multimodulo",
        "notas gerais do VRMaster abrangem múltiplos módulos",
    ),
    ("wiki", "1905"): (
        "Multimodulo",
        "notas de versão do produto híbrido VRAdm",
    ),
    ("wiki", "2797"): (
        "Multimodulo",
        "notas de versão do produto híbrido VRAdm",
    ),
    ("wiki", "6553"): (
        "Multimodulo",
        "Carteira Digital possui integração administrativa e operação no PDV",
    ),
}


def _reason_kind(reasons: list[str]) -> str:
    if any("hierarquia do titulo" in reason for reason in reasons):
        return "title_hierarchy"
    if any("modulo explicito na categoria" in reason for reason in reasons):
        return "explicit_category"
    if any("categoria com modulos conflitantes" in reason for reason in reasons):
        return "conflicting_category"
    return "classifier_ambiguity"


def build_changes(database_path: Path) -> tuple[list[dict[str, Any]], dict[str, int]]:
    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row
    try:
        rows = connection.execute(
            """SELECT id,source,source_id,title,module,category,product,markdown,
                      local_path,classification_confidence
               FROM documents
               WHERE status='active' AND source IN ('wiki','kb')
               ORDER BY id"""
        ).fetchall()
    finally:
        connection.close()

    catalog = load_product_catalog()
    changes: list[dict[str, Any]] = []
    skipped = Counter()
    for row in rows:
        result = classify(
            str(row["title"]),
            str(row["markdown"] or ""),
            str(row["category"] or ""),
            str(row["product"] or ""),
            catalog,
        )
        current = str(row["module"])
        suggested = result.module
        manual = MANUAL_CORRECTIONS.get((str(row["source"]), str(row["source_id"])))
        if manual:
            destination, note = manual
            confidence = max(float(result.confidence), 0.95)
            reason_kind = "manual_content_validation"
            reasons = [note]
        elif suggested == current:
            continue
        elif (
            current == "Multimodulo"
            and suggested in CONCRETE_MODULES
            and any("modulo explicito na categoria" in reason for reason in result.reasons)
        ):
            destination = suggested
            confidence = float(result.confidence)
            reason_kind = "explicit_category"
            reasons = list(result.reasons)
        elif (
            current != "Multimodulo"
            and suggested in CONCRETE_MODULES
            and any("hierarquia do titulo" in reason for reason in result.reasons)
        ):
            destination = suggested
            confidence = float(result.confidence)
            reason_kind = "title_hierarchy"
            reasons = list(result.reasons)
        else:
            skipped[f"{current} -> {suggested}"] += 1
            continue

        if destination == current:
            continue
        changes.append(
            {
                "document_id": int(row["id"]),
                "source": str(row["source"]),
                "source_id": str(row["source_id"]),
                "title": str(row["title"]),
                "current_module": current,
                "destination_module": destination,
                "old_confidence": float(row["classification_confidence"] or 0.0),
                "confidence": confidence,
                "reason_kind": reason_kind,
                "reasons": reasons,
                "local_path": str(row["local_path"]),
            }
        )
    return changes, dict(skipped)


def _backup(
    project: Path,
    database_path: Path,
    changes: list[dict[str, Any]],
) -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    target = project / ".state" / "backups" / f"module-curation-{timestamp}"
    target.mkdir(parents=True, exist_ok=False)
    shutil.copy2(database_path, target / database_path.name)
    for index_name in ("catalogo.jsonl", "INDEX.md"):
        source = project / "indice" / index_name
        if source.is_file():
            shutil.copy2(source, target / index_name)

    knowledge_root = (project / "conhecimento").resolve()
    for change in changes:
        source = resolve_portable_path(project, change["local_path"]).resolve()
        if not source.is_relative_to(knowledge_root) or not source.is_file():
            raise RuntimeError(f"Documento fora da base ou ausente: {source}")
        relative = source.relative_to(project)
        backup_file = target / "files" / relative
        backup_file.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, backup_file)

    (target / "manifest.json").write_text(
        json.dumps({"changes": changes}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return target


def apply_changes(project: Path, changes: list[dict[str, Any]]) -> Path:
    database_path = project / "indice" / "conhecimento.sqlite"
    backup_path = _backup(project, database_path, changes)
    database = MaryDatabase(
        database_path,
        root=project,
        backup_portable_migration=False,
    )

    review_ids: dict[str, list[int]] = defaultdict(list)
    for change in changes:
        database.queue_review(
            change["document_id"],
            change["destination_module"],
            change["confidence"],
            change["reasons"],
            change["current_module"],
            True,
        )
        with database.connect() as connection:
            connection.execute(
                "UPDATE documents SET classification_confidence=? WHERE id=?",
                (change["confidence"], change["document_id"]),
            )
            review = connection.execute(
                """SELECT id FROM classification_reviews
                   WHERE document_id=? AND status='pending'
                   ORDER BY id DESC LIMIT 1""",
                (change["document_id"],),
            ).fetchone()
        if review is None:
            raise RuntimeError(
                f"Revisão não criada para o documento {change['document_id']}"
            )
        review_ids[change["destination_module"]].append(int(review["id"]))

    for module, ids in review_ids.items():
        database.decide_reviews(
            ids,
            "approve",
            module=module,
            note="Curadoria automática baseada na hierarquia VRMaster validada.",
        )
    export_catalog(database, project / "indice")
    return backup_path


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Audita e corrige módulos seguros da base portátil VR."
    )
    parser.add_argument("--project", type=Path, default=Path("VRProject"))
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--details", action="store_true")
    args = parser.parse_args()
    project = args.project.resolve()
    database_path = project / "indice" / "conhecimento.sqlite"
    changes, skipped = build_changes(database_path)
    summary = {
        "mode": "apply" if args.apply else "dry-run",
        "project": str(project),
        "changes": len(changes),
        "by_transition": dict(
            Counter(
                f"{item['current_module']} -> {item['destination_module']}"
                for item in changes
            )
        ),
        "by_reason": dict(Counter(item["reason_kind"] for item in changes)),
        "skipped": skipped,
    }
    if args.details:
        summary["items"] = changes
    if args.apply:
        summary["backup"] = str(apply_changes(project, changes))
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
