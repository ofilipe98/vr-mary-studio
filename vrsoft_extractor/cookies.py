from __future__ import annotations

import json
from pathlib import Path


def write_netscape_cookie_file(storage_state_path: Path, cookiefile_path: Path) -> Path:
    data = json.loads(storage_state_path.read_text(encoding="utf-8"))
    cookies = data.get("cookies", [])
    cookiefile_path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# Netscape HTTP Cookie File", "# Generated from Playwright storage_state."]
    for cookie in cookies:
        domain = str(cookie.get("domain", ""))
        include_subdomains = "TRUE" if domain.startswith(".") else "FALSE"
        path = str(cookie.get("path", "/"))
        secure = "TRUE" if cookie.get("secure") else "FALSE"
        expires = int(cookie.get("expires") or 0)
        name = str(cookie.get("name", ""))
        value = str(cookie.get("value", ""))
        if not domain or not name:
            continue
        lines.append(
            "\t".join([domain, include_subdomains, path, secure, str(expires), name, value])
        )
    cookiefile_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return cookiefile_path

