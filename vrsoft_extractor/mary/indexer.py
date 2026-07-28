from __future__ import annotations

import json
from pathlib import Path

from .db import MaryDatabase


def export_catalog(database: MaryDatabase, index_dir: Path) -> tuple[Path, Path]:
    index_dir.mkdir(parents=True, exist_ok=True)
    with database.connect() as connection:
        rows = connection.execute(
            """SELECT source,source_id,title,url,module,classification_confidence,
                      review_status,status,updated_at,local_path,assets_json
               FROM documents ORDER BY module,source,title"""
        ).fetchall()
    jsonl_path = index_dir / "catalogo.jsonl"
    with jsonl_path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            item = dict(row)
            item["assets"] = json.loads(item.pop("assets_json") or "[]")
            handle.write(json.dumps(item, ensure_ascii=False) + "\n")

    index_path = index_dir / "INDEX.md"
    counts: dict[str, int] = {}
    for row in rows:
        key = f"{row['module']} / {row['source'].upper()}"
        counts[key] = counts.get(key, 0) + 1
    lines = [
        "# Índice da base Mary",
        "",
        "Gerado automaticamente. Use `conhecimento.sqlite` para pesquisa FTS5.",
        "",
        "| Módulo / fonte | Documentos |",
        "|---|---:|",
    ]
    lines.extend(f"| {key} | {value} |" for key, value in sorted(counts.items()))
    lines.extend(["", f"Total: **{len(rows)}** documentos.", ""])
    index_path.write_text("\n".join(lines), encoding="utf-8")
    return jsonl_path, index_path
