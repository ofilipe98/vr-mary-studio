from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class SchemaColumnRecord:
    name: str
    data_type: str = ""
    nullable: bool = True
    primary_key: bool = False
    default_value: str = ""
    description: str = ""


@dataclass(frozen=True)
class SchemaRelationRecord:
    from_schema: str
    from_table: str
    from_column: str
    to_schema: str
    to_table: str
    to_column: str
    evidence: str


@dataclass(frozen=True)
class SchemaTableRecord:
    schema_name: str
    table_name: str
    description: str
    approximate_rows: str
    columns: tuple[SchemaColumnRecord, ...]
    relations: tuple[SchemaRelationRecord, ...]


TABLE_HEADING = re.compile(
    r"^##\s+`([^`]+)`\.`([^`]+)`\s*$", flags=re.MULTILINE
)
ROW_COUNT = re.compile(r"\*Registros aproximados:\s*([^*]+)\*", flags=re.I)
RELATION = re.compile(
    r"-\s+`?([a-z0-9_]+)\.([a-z0-9_]+)`?\s*->\s*"
    r"`?([a-z0-9_]+)\.([a-z0-9_]+)\.([a-z0-9_]+)`?",
    flags=re.I,
)


def parse_schema_markdown(markdown: str) -> list[SchemaTableRecord]:
    text = str(markdown or "")
    headings = list(TABLE_HEADING.finditer(text))
    records: list[SchemaTableRecord] = []
    for index, match in enumerate(headings):
        schema_name, table_name = match.group(1), match.group(2)
        end = headings[index + 1].start() if index + 1 < len(headings) else len(text)
        section = text[match.end() : end]
        row_match = ROW_COUNT.search(section)
        approximate_rows = row_match.group(1).strip() if row_match else ""
        columns = tuple(_parse_columns(section))
        relations = tuple(
            SchemaRelationRecord(
                from_schema=schema_name,
                from_table=from_table,
                from_column=from_column,
                to_schema=to_schema,
                to_table=to_table,
                to_column=to_column,
                evidence=evidence,
            )
            for (
                from_table,
                from_column,
                to_schema,
                to_table,
                to_column,
                evidence,
            ) in _parse_relations(section)
        )
        description = _section_description(section)
        records.append(
            SchemaTableRecord(
                schema_name=schema_name,
                table_name=table_name,
                description=description,
                approximate_rows=approximate_rows,
                columns=columns,
                relations=relations,
            )
        )
    return records


def _parse_columns(section: str) -> list[SchemaColumnRecord]:
    columns: list[SchemaColumnRecord] = []
    inside_table = False
    for raw_line in section.splitlines():
        line = raw_line.strip()
        if line.startswith("| Coluna |"):
            inside_table = True
            continue
        if not inside_table:
            continue
        if not line.startswith("|"):
            if columns:
                break
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if len(cells) < 6 or set(cells[0]) <= {"-", ":", " "}:
            continue
        name = cells[0].strip("`")
        if not name or name.casefold() == "coluna":
            continue
        columns.append(
            SchemaColumnRecord(
                name=name,
                data_type=cells[1].strip("`"),
                nullable=cells[2].casefold() in {"sim", "yes", "true"},
                primary_key="pk" in cells[3].casefold(),
                default_value=cells[4].strip("`"),
                description=cells[5],
            )
        )
    return columns


def _parse_relations(section: str):
    for line in section.splitlines():
        match = RELATION.search(line)
        if match:
            yield (*match.groups(), line.strip())


def _section_description(section: str) -> str:
    lines = []
    for line in section.splitlines():
        cleaned = line.strip()
        if not cleaned or cleaned.startswith(("|", "*Registros", "**")):
            continue
        if cleaned == "---":
            continue
        lines.append(cleaned)
        if len(" ".join(lines)) >= 300:
            break
    return " ".join(lines)[:500]
