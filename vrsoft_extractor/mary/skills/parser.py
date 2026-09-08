from __future__ import annotations

import re
from pathlib import Path
from typing import Any


FRONTMATTER_RE = re.compile(r"^---\r?\n(.*?)\r?\n---\r?\n?(.*)$", re.DOTALL)


def parse_frontmatter_text(text: str) -> tuple[dict[str, Any], str]:
    """Parse YAML-like frontmatter from markdown text without external dependencies."""
    match = FRONTMATTER_RE.match(text.lstrip())
    if not match:
        return {}, text

    yaml_block, body = match.groups()
    metadata: dict[str, Any] = {}

    current_key = None
    multiline_buf = []

    def parse_value(val: str) -> Any:
        if val.lower() in ("true", "yes", "on"):
            return True
        elif val.lower() in ("false", "no", "off"):
            return False
        elif val.startswith('"') and val.endswith('"') and len(val) >= 2:
            return val[1:-1]
        elif val.startswith("'") and val.endswith("'") and len(val) >= 2:
            return val[1:-1]
        return val

    for line in yaml_block.splitlines():
        trimmed = line.strip()
        if not trimmed or trimmed.startswith("#"):
            continue

        if ":" in line and not line.startswith(" ") and not line.startswith("\t"):
            if current_key and multiline_buf:
                metadata[current_key] = " ".join(multiline_buf).strip()
                multiline_buf = []
            key, _, val = line.partition(":")
            key = key.strip()
            val = val.strip()
            current_key = key
            if val in (">", ">-", "|", "|-"):
                multiline_buf = []
            elif val == "":
                metadata[key] = {}
            else:
                metadata[key] = parse_value(val)
        elif current_key and (line.startswith(" ") or line.startswith("\t")):
            if ":" in trimmed and isinstance(metadata.get(current_key), dict):
                sub_k, _, sub_v = trimmed.partition(":")
                metadata[current_key][sub_k.strip()] = parse_value(sub_v.strip())
            else:
                multiline_buf.append(trimmed)

    if current_key and multiline_buf and current_key not in metadata:
        metadata[current_key] = " ".join(multiline_buf).strip()

    return metadata, body.strip()


def parse_skill_markdown_file(file_path: Path) -> tuple[dict[str, Any], str]:
    """Read a SKILL.md file and return (metadata_dict, body_instructions)."""
    try:
        content = file_path.read_text(encoding="utf-8", errors="replace")
        return parse_frontmatter_text(content)
    except Exception:
        return {}, ""


def serialize_skill_markdown(metadata: dict[str, Any], instructions: str) -> str:
    """Format metadata and instructions into a clean SKILL.md string."""
    lines = ["---"]
    for k, v in metadata.items():
        if isinstance(v, bool):
            lines.append(f"{k}: {'true' if v else 'false'}")
        elif isinstance(v, (int, float)):
            lines.append(f"{k}: {v}")
        elif isinstance(v, dict):
            lines.append(f"{k}:")
            for sub_k, sub_v in v.items():
                if isinstance(sub_v, bool):
                    lines.append(f"  {sub_k}: {'true' if sub_v else 'false'}")
                else:
                    lines.append(f'  {sub_k}: "{sub_v}"')
        else:
            text_val = str(v).replace('"', '\\"')
            if "\n" in text_val:
                lines.append(f"{k}: >-")
                for sub in text_val.splitlines():
                    lines.append(f"  {sub.strip()}")
            else:
                lines.append(f'{k}: "{text_val}"')
    lines.append("---")
    lines.append("")
    lines.append(instructions.strip())
    lines.append("")
    return "\n".join(lines)
