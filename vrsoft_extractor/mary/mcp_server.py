"""
Standard I/O MCP (Model Context Protocol) server for VR Mary Studio.

Provides unified access to local knowledge (Wiki, KB, Schema) and Java code
via JSON-RPC 2.0 stdio transport across all AI providers (Claude, Antigravity, OpenCode).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    __package__ = "vrsoft_extractor.mary"

from .knowledge_access import load_scope
from .config import load_vr_settings
from .db import MaryDatabase
from .knowledge_router import KnowledgeRouter
from .retrieval.service import RetrievalService
from .chat_tools import (
    all_vr_tools_specs,
    run_vr_sources,
    run_vr_search,
    run_vr_read,
    VR_SOURCES_TOOL_NAME,
    VR_SEARCH_TOOL_NAME,
    VR_READ_TOOL_NAME,
)


def read_message(stream: Any) -> dict[str, Any] | None:
    line = stream.readline()
    if not line:
        return None
    line_str = line.strip()
    if not line_str:
        return None
    if line_str.lower().startswith("content-length:"):
        length = int(line_str.split(":", 1)[1].strip())
        while True:
            header_line = stream.readline()
            if not header_line or not header_line.strip():
                break
        body = stream.read(length)
        return json.loads(body)
    return json.loads(line_str)


def write_message(stream: Any, payload: dict[str, Any]) -> None:
    body = json.dumps(payload, ensure_ascii=False)
    stream.write(body + "\n")
    stream.flush()


def run_mcp_server(root_path: Path | None = None, context_path: str = "") -> None:
    root = root_path or Path(os.environ.get("VR_STUDIO_ROOT", ".")).resolve()
    settings = load_vr_settings(root=root)
    database = MaryDatabase(settings.database_path, root=settings.root)
    router = KnowledgeRouter(
        database,
        settings.root,
        disabled_origins=("endoo",) if not settings.endoo_wiki_enabled else (),
    )
    service = RetrievalService(router)

    stdin = sys.stdin
    stdout = sys.stdout
    calls = 0
    output_chars = 0

    while True:
        try:
            req = read_message(stdin)
        except Exception:
            break
        if req is None:
            break

        req_id = req.get("id")
        method = req.get("method")
        params = req.get("params") or {}

        if method == "initialize":
            resp = {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {
                        "tools": {
                            "listChanged": False,
                        },
                    },
                    "serverInfo": {
                        "name": "vr-mary-studio",
                        "version": "1.0.0",
                    },
                },
            }
            write_message(stdout, resp)
        elif method == "notifications/initialized":
            pass
        elif method == "ping":
            if req_id is not None:
                write_message(stdout, {"jsonrpc": "2.0", "id": req_id, "result": {}})
        elif method == "tools/list":
            specs = all_vr_tools_specs()
            mcp_tools = [
                {
                    "name": s["name"],
                    "description": s["description"],
                    "inputSchema": s["inputSchema"],
                }
                for s in specs
            ]
            resp = {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {"tools": mcp_tools},
            }
            write_message(stdout, resp)
        elif method == "tools/call":
            tool_name = params.get("name")
            arguments = params.get("arguments") or {}
            try:
                scope = load_scope(context_path)
                if calls >= 24 or output_chars >= 96000:
                    raise ValueError("Limite de consultas deste turno atingido.")
                calls += 1
                if tool_name == VR_SEARCH_TOOL_NAME:
                    exec_res = run_vr_search(arguments, service, **scope)
                elif tool_name == VR_SOURCES_TOOL_NAME:
                    exec_res = run_vr_sources(arguments, service, **scope)
                elif tool_name == VR_READ_TOOL_NAME:
                    exec_res = run_vr_read(arguments, service, **scope)
                else:
                    raise ValueError(f"Tool desconhecida: {tool_name}")

                load_scope(context_path)  # Reject work completed after cancellation.
                if output_chars + len(exec_res.text) > 96000:
                    raise ValueError("Limite de resultados deste turno atingido; reduza limit.")
                output_chars += len(exec_res.text)
                if context_path and tool_name != VR_SOURCES_TOOL_NAME:
                    with open(context_path + ".events", "a", encoding="utf-8") as journal:
                        journal.write(json.dumps(exec_res.parsed, ensure_ascii=False) + "\n")

                resp = {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "content": [{"type": "text", "text": exec_res.text}],
                        "isError": bool(exec_res.parsed.get("error")),
                    },
                }
            except Exception as exc:
                resp = {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "content": [{"type": "text", "text": f"Erro na execução da tool {tool_name}: {exc}"}],
                        "isError": True,
                    },
                }
            write_message(stdout, resp)
        else:
            if req_id is not None:
                resp = {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {
                        "code": -32601,
                        "message": f"Método não suportado: {method}",
                    },
                }
                write_message(stdout, resp)


def main() -> None:
    if os.name == "nt" and (sys.stdin is None or sys.stdout is None):
        # PyInstaller's windowed executable still inherits the MCP pipe handles.
        import ctypes
        import msvcrt
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.GetStdHandle.restype = ctypes.c_void_p
        for attribute, handle, flags, mode in (
            ("stdin", -10, os.O_RDONLY, "r"), ("stdout", -11, os.O_WRONLY, "w")
        ):
            if getattr(sys, attribute) is None:
                fd = msvcrt.open_osfhandle(kernel.GetStdHandle(handle), flags)
                setattr(sys, attribute, os.fdopen(fd, mode, encoding="utf-8"))
    for stream in (sys.stdin, sys.stdout):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="VR Mary Studio MCP Server")
    parser.add_argument("--root", type=Path, default=None, help="Caminho raiz da base do VR Studio")
    parser.add_argument("--context", default="", help="Contexto imutavel do turno")
    args = parser.parse_args()
    run_mcp_server(args.root, args.context)


if __name__ == "__main__":
    main()
