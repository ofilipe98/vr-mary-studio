"""Real Codex App Server smoke test for VR Mary chat integration.

This intentionally creates and deletes native test threads. Run it only in an
authenticated development environment; it is not part of the offline suite.
"""

from __future__ import annotations

import json
import tempfile
import threading
from pathlib import Path

from vrsoft_extractor.mary.models import APPROVAL_PRESETS, ConversationOptions, RuntimeEvent
from vrsoft_extractor.mary.providers import CodexProvider


def main() -> int:
    provider = CodexProvider()
    native_threads: list[str] = []
    try:
        models = provider.list_models()
        modes = provider.list_collaboration_modes()
        mcp_tools = provider.list_mcp_tools()
        if not models:
            raise RuntimeError("model/list não retornou modelos.")
        model = str(
            next((item for item in models if item.get("isDefault")), models[0]).get("id")
            or models[0].get("model")
            or ""
        )
        if not model:
            raise RuntimeError("O modelo retornado não possui ID.")
        mcp_selection = next(
            (
                {"server": item["server"], "tool": item["tool"]}
                for item in mcp_tools
                if item.get("server") == "node_repl" and item.get("tool") == "js"
            ),
            None,
        )
        print(json.dumps({"model": model, "modes": modes, "mcp": mcp_selection}, ensure_ascii=False))

        with tempfile.TemporaryDirectory(prefix="vr-mary-codex-smoke-") as temporary:
            workspace = Path(temporary).resolve()
            auto_native = ""
            auto_options: ConversationOptions | None = None
            for profile in APPROVAL_PRESETS:
                dynamic_tools = ()
                selected_mcp = ()
                if profile == "auto":
                    dynamic_tools = (
                        {
                            "type": "function",
                            "name": "vr_mary_smoke",
                            "description": "Returns a deterministic smoke-test confirmation.",
                            "inputSchema": {
                                "type": "object",
                                "properties": {"message": {"type": "string"}},
                                "required": ["message"],
                            },
                        },
                    )
                    selected_mcp = (mcp_selection,) if mcp_selection else ()
                options = ConversationOptions(
                    model=model,
                    effort="medium",
                    approval_profile=profile,
                    collaboration_mode="default",
                    dynamic_tools=dynamic_tools,
                    mcp_tools=selected_mcp,
                )
                native = provider.start_conversation(
                    f"smoke-{profile}", model, "medium", workspace, options
                )
                native_threads.append(native)
                print(
                    f"thread/start {profile}: {native} "
                    f"sandbox={APPROVAL_PRESETS[profile].sandbox}"
                )
                if profile == "auto":
                    auto_native = native
                    auto_options = options

            if not auto_native or auto_options is None:
                raise RuntimeError("Thread Auto não foi criada.")

            completed = threading.Event()
            dynamic_called = threading.Event()
            mcp_called = threading.Event()
            errors: list[str] = []

            def callback(event: RuntimeEvent) -> None:
                if event.kind == "dynamic_tool_requested":
                    dynamic_called.set()
                    provider.respond_dynamic_tool(
                        str(event.payload.get("request_id") or ""),
                        [{"type": "inputText", "text": '{"smoke":"ok"}'}],
                        True,
                    )
                item = event.payload.get("item") or {}
                if (
                    item.get("type") == "mcpToolCall"
                    and item.get("server") == "node_repl"
                    and item.get("tool") == "js"
                ):
                    mcp_called.set()
                if event.kind == "error":
                    errors.append(event.text)
                if event.kind == "turn_completed":
                    completed.set()

            requested_actions = ["call vr_mary_smoke with message 'ok'"]
            if mcp_selection:
                requested_actions.append("call the MCP tool mcp__node_repl__js with code '1 + 1'")
            prompt = "For an integration smoke test, " + ", then ".join(requested_actions) + ". Reply SMOKE_OK."
            provider.send_message(
                "smoke-auto",
                auto_native,
                model,
                "medium",
                workspace,
                prompt,
                callback,
                auto_options,
            )
            if not completed.wait(180):
                raise RuntimeError("Timeout aguardando o turno Build.")
            if errors:
                raise RuntimeError("; ".join(errors))
            if not dynamic_called.is_set():
                raise RuntimeError("O modelo não chamou a tool dinâmica no smoke test.")
            if mcp_selection and not mcp_called.is_set():
                raise RuntimeError("O modelo não chamou a tool MCP no smoke test.")
            print("Build + dynamic tool + MCP: OK")

            plan_options = ConversationOptions(
                model=model,
                effort="medium",
                approval_profile="auto",
                collaboration_mode="plan",
                dynamic_tools=auto_options.dynamic_tools,
                mcp_tools=auto_options.mcp_tools,
            )
            provider.update_settings("smoke-auto", auto_native, workspace, plan_options)
            completed.clear()
            provider.send_message(
                "smoke-auto",
                auto_native,
                model,
                "medium",
                workspace,
                "Plan mode smoke test. Reply only PLAN_OK and do not call tools.",
                callback,
                plan_options,
            )
            if not completed.wait(180):
                raise RuntimeError("Timeout aguardando o turno Plan.")
            if errors:
                raise RuntimeError("; ".join(errors))
            print("Plan mode: OK")
            for native_id in native_threads:
                provider.delete_thread(native_id)
            native_threads.clear()
            provider.close()
        return 0
    finally:
        for native_id in native_threads:
            try:
                provider.delete_thread(native_id)
            except Exception as exc:  # cleanup must not hide the actual smoke result
                print(f"Aviso ao excluir thread de smoke {native_id}: {exc}")
        provider.close()


if __name__ == "__main__":
    raise SystemExit(main())
