"""Opt-in read-only provider smoke; uses only temporary project and database."""
import argparse
import json
import tempfile
import threading
from collections import Counter
from pathlib import Path

from vrsoft_extractor.mary.config import MarySettings
from vrsoft_extractor.mary.db import MaryDatabase
from vrsoft_extractor.mary.orchestrator import ChatOrchestrator


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true", required=True)
    parser.parse_args()
    result = {"provider": "codex", "turns": []}
    with tempfile.TemporaryDirectory(prefix="mary-intermediate-smoke-") as folder:
        root = Path(folder).resolve()
        settings = MarySettings(app_dir=root, root=root / "project", old_root=root / "legacy")
        db = MaryDatabase(settings.database_path, root=settings.root, backup_portable_migration=False)
        orch = ChatOrchestrator(settings, db)
        try:
            cid = orch.new_conversation("codex", "", approval_profile="supervised", defer_provider_start=True)
            for label in ("ALFA", "BETA"):
                done = threading.Event()
                events = []

                def callback(event):
                    events.append(event)
                    if event.kind == "turn_completed":
                        done.set()
                    if event.kind == "approval_requested":
                        orch.approve(cid, str(event.payload.get("request_id") or ""), False, request=event.payload)

                orch.send(cid, f"Teste de integração: responda somente {label}. Não use ferramentas nem leia ou altere arquivos.", callback, use_vr=False)
                if not done.wait(50):
                    orch.interrupt(cid)
                    raise RuntimeError("Provider smoke timeout")
                orch.drain_turn_finalizations()
                kinds = Counter(e.kind for e in events)
                result["turns"].append({"kinds": dict(kinds), "completed_messages": kinds["assistant_completed"], "errors": kinds["error"]})
            answers = [r for r in db.messages(cid) if r["role"] == "assistant"]
            assert len(answers) == 2, len(answers)
            assert "ALFA" in answers[0]["content"] and "BETA" in answers[1]["content"]
            assert len({r["execution_id"] for r in answers}) == 2
            result["status"] = "passed"
            result["distinct_execution_ids"] = True
        except Exception as exc:
            result["status"] = "not_validated"
            result["error_type"] = type(exc).__name__
        finally:
            orch.close()
    output = Path(__file__).with_name("smoke-provider-result.json")
    output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
